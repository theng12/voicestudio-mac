"""Best-effort resource evidence for one local generation job.

Voice Studio owns this measurement because it owns the model process.  The
sampler deliberately reports observations rather than deriving a RAM minimum;
qualification tooling can compare the same evidence across 8/16/24 GB Macs.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Optional


SCHEMA = "voicestudio.resource-telemetry"
SCHEMA_VERSION = 1
DEFAULT_INTERVAL_SECONDS = 0.5


def _gb(value: int | float) -> float:
    return round(float(value) / 1_000_000_000, 3)


def _pressure_level() -> dict[str, Any]:
    """Return Darwin's kernel memory-pressure level without spawning a process.

    Darwin uses bit values 1/2/4/8 for normal/warning/urgent/critical.  Unknown
    platforms and kernels remain explicit instead of being guessed from a RAM
    percentage.
    """
    try:
        value = ctypes.c_int(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.sysctlbyname(
            b"kern.memorystatus_vm_pressure_level",
            ctypes.byref(value),
            ctypes.byref(size),
            None,
            0,
        )
        if result != 0:
            raise OSError(ctypes.get_errno(), "sysctlbyname failed")
        labels = {1: "normal", 2: "warning", 4: "urgent", 8: "critical"}
        return {"supported": True, "raw": int(value.value),
                "level": labels.get(int(value.value), "unknown")}
    except Exception:
        return {"supported": False, "raw": None, "level": "unavailable"}


def _mlx_snapshot(*, reset_peak: bool = False) -> dict[str, Any]:
    try:
        import mlx.core as mx

        active = int(mx.get_active_memory())
        cache = int(mx.get_cache_memory())
        if reset_peak:
            mx.reset_peak_memory()
        peak = int(mx.get_peak_memory())
        return {
            "supported": True,
            "active_gb": _gb(active),
            "cache_gb": _gb(cache),
            "reported_peak_gb": _gb(peak),
        }
    except Exception:
        return {
            "supported": False,
            "active_gb": None,
            "cache_gb": None,
            "reported_peak_gb": None,
        }


def _snapshot(*, reset_mlx_peak: bool = False) -> Optional[dict[str, Any]]:
    try:
        import psutil

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        root = psutil.Process(os.getpid())
        try:
            processes = [root, *root.children(recursive=True)]
        except psutil.Error:
            processes = [root]
        rss = 0
        count = 0
        for process in processes:
            try:
                rss += int(process.memory_info().rss)
                count += 1
            except psutil.Error:
                continue
        return {
            "at": time.time(),
            "host": {
                "total_gb": _gb(vm.total),
                "available_gb": _gb(vm.available),
                "used_gb": _gb(vm.used),
                "used_percent": round(float(vm.percent), 2),
                "pressure": _pressure_level(),
                "swap_used_gb": _gb(swap.used),
                "swap_in_bytes": int(swap.sin),
                "swap_out_bytes": int(swap.sout),
            },
            "worker": {"rss_gb": _gb(rss), "process_count": count},
            "mlx": _mlx_snapshot(reset_peak=reset_mlx_peak),
        }
    except Exception:
        return None


class JobResourceSampler:
    """Sample one serialized local generation and publish a compact summary."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._publish = publish
        self._interval = max(0.1, float(interval_seconds))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._started_at = time.time()
        self._finished_at: Optional[float] = None
        self._samples = 0
        self._start: Optional[dict[str, Any]] = None
        self._last: Optional[dict[str, Any]] = None
        self._min_available: Optional[float] = None
        self._max_host_used: Optional[float] = None
        self._max_host_percent: Optional[float] = None
        self._max_swap: Optional[float] = None
        self._peak_worker_rss: Optional[float] = None
        self._peak_process_count = 0
        self._peak_mlx_active: Optional[float] = None
        self._peak_mlx_cache: Optional[float] = None
        self._peak_mlx_reported: Optional[float] = None
        self._peak_pressure_raw: Optional[int] = None
        self._peak_pressure_level = "unavailable"

    def start(self) -> "JobResourceSampler":
        self._take(reset_mlx_peak=True)
        self._thread = threading.Thread(
            target=self._run,
            name="voice-job-resource-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._take()

    def _take(self, *, reset_mlx_peak: bool = False) -> None:
        sample = _snapshot(reset_mlx_peak=reset_mlx_peak)
        if sample is None:
            return
        with self._lock:
            if self._start is None:
                self._start = sample
            self._last = sample
            self._samples += 1
            host = sample["host"]
            worker = sample["worker"]
            mlx = sample["mlx"]
            self._min_available = min(
                host["available_gb"],
                self._min_available if self._min_available is not None else host["available_gb"],
            )
            self._max_host_used = max(
                host["used_gb"],
                self._max_host_used if self._max_host_used is not None else host["used_gb"],
            )
            self._max_host_percent = max(
                host["used_percent"],
                self._max_host_percent if self._max_host_percent is not None else host["used_percent"],
            )
            self._max_swap = max(
                host["swap_used_gb"],
                self._max_swap if self._max_swap is not None else host["swap_used_gb"],
            )
            self._peak_worker_rss = max(
                worker["rss_gb"],
                self._peak_worker_rss if self._peak_worker_rss is not None else worker["rss_gb"],
            )
            self._peak_process_count = max(self._peak_process_count, worker["process_count"])
            if mlx["supported"]:
                for attr, key in (
                    ("_peak_mlx_active", "active_gb"),
                    ("_peak_mlx_cache", "cache_gb"),
                    ("_peak_mlx_reported", "reported_peak_gb"),
                ):
                    value = mlx[key]
                    previous = getattr(self, attr)
                    setattr(self, attr, max(value, previous if previous is not None else value))
            pressure = host["pressure"]
            if pressure["supported"] and pressure["raw"] is not None:
                raw = int(pressure["raw"])
                if self._peak_pressure_raw is None or raw > self._peak_pressure_raw:
                    self._peak_pressure_raw = raw
                    self._peak_pressure_level = str(pressure["level"])
            payload = self._summary_locked()
        self._publish(payload)

    def _summary_locked(self) -> dict[str, Any]:
        start = self._start or {}
        last = self._last or start
        start_host = start.get("host") or {}
        end_host = last.get("host") or {}
        start_worker = start.get("worker") or {}
        end_worker = last.get("worker") or {}
        start_mlx = start.get("mlx") or {"supported": False}
        end_mlx = last.get("mlx") or start_mlx
        swap_start = start_host.get("swap_used_gb")
        swap_end = end_host.get("swap_used_gb")
        swap_in_start = start_host.get("swap_in_bytes")
        swap_out_start = start_host.get("swap_out_bytes")
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "sampling": {
                "interval_seconds": self._interval,
                "samples": self._samples,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
            },
            "host": {
                "total_gb": start_host.get("total_gb"),
                "available_gb_start": start_host.get("available_gb"),
                "minimum_available_gb": self._min_available,
                "available_gb_end": end_host.get("available_gb"),
                "maximum_used_gb": self._max_host_used,
                "maximum_used_percent": self._max_host_percent,
                "pressure_level_start": (start_host.get("pressure") or {}).get("level"),
                "peak_pressure_level": self._peak_pressure_level,
                "peak_pressure_raw": self._peak_pressure_raw,
                "pressure_level_end": (end_host.get("pressure") or {}).get("level"),
                "swap_used_gb_start": swap_start,
                "maximum_swap_used_gb": self._max_swap,
                "swap_used_gb_end": swap_end,
                "swap_used_delta_gb": (
                    round(float(swap_end) - float(swap_start), 3)
                    if swap_start is not None and swap_end is not None else None
                ),
                "swap_in_delta_bytes": (
                    int(end_host.get("swap_in_bytes", 0)) - int(swap_in_start)
                    if swap_in_start is not None else None
                ),
                "swap_out_delta_bytes": (
                    int(end_host.get("swap_out_bytes", 0)) - int(swap_out_start)
                    if swap_out_start is not None else None
                ),
            },
            "worker": {
                "rss_gb_start": start_worker.get("rss_gb"),
                "peak_rss_gb": self._peak_worker_rss,
                "rss_gb_end": end_worker.get("rss_gb"),
                "peak_process_count": self._peak_process_count,
            },
            "mlx": {
                "supported": bool(start_mlx.get("supported") or end_mlx.get("supported")),
                "active_gb_start": start_mlx.get("active_gb"),
                "peak_active_gb": self._peak_mlx_active,
                "peak_cache_gb": self._peak_mlx_cache,
                "reported_peak_gb": self._peak_mlx_reported,
                "active_gb_end": end_mlx.get("active_gb"),
                "cache_gb_end": end_mlx.get("cache_gb"),
            },
        }

    def finish(self, *, state: str, memory_failure: bool,
               restart_scheduled: bool, model_retained: bool) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval * 3))
        self._take()
        with self._lock:
            self._finished_at = time.time()
            result = self._summary_locked()
            result["sampling"]["finished_at"] = self._finished_at
            result["outcome"] = {
                "state": state,
                "memory_failure": bool(memory_failure),
                "restart_scheduled": bool(restart_scheduled),
                "model_retained": bool(model_retained),
            }
        self._publish(result)
        return result
