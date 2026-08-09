"""Persistent opt-in Voice Studio model memory policy."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from . import restart_health


SETTINGS_FILE = Path(__file__).resolve().parent / "memory_policy.json"
MODES = {
    "performance": {"idle_seconds": None, "label": "Performance"},
    "balanced": {"idle_seconds": 600, "label": "Balanced"},
    "memory_saver": {"idle_seconds": 120, "label": "Memory Saver"},
    "immediate": {"idle_seconds": 0, "label": "Immediate"},
}
# "performance" pins a loaded model in unified memory forever. That is a fine
# default for an app that owns its machine — and a bad one for the deployment
# that actually exists, where 3-5 Studios share a single 8 GB Mac and none of
# them knows the others are resident. Each Studio ships this same skeleton with
# this same default, so every one of them independently concluded that holding
# its model forever was free.
#
# Measured on the fleet 2026-08-07: 16 of 19 machines sat below the memory
# guard's 3.2 GB floor with 1.5-4.4 GB of swap burned and could not start a job
# at all. The idle-release thread was running the whole time — it just had
# nothing to do, because idle_seconds is None in this mode.
#
# A five-machine production pressure run on 2026-08-09 showed that waiting even
# two minutes is too long for a Mac that must switch between sibling Studios.
# Image throughput was unchanged, while the following Voice job on an M4 16 GB
# fell from 52.7 s to 4.0 s once the prior Studio released immediately. An
# operator's explicit choice, persisted in memory_policy.json, always wins.
DEFAULT_MODE = "immediate"


def default_mode() -> str:
    """Mode to use when the operator has not chosen one."""
    return DEFAULT_MODE


CHECK_INTERVAL_SECONDS = 5

_LOCK = threading.RLock()
_START_LOCK = threading.Lock()
_STARTED = False
_GEN_MANAGER = None
_STT_MANAGER = None
_GPU_LOCK = None
# Every counter below lives in this process and starts at zero on each start.
# A restart therefore erases them while job history survives on disk, so
# `release_count: 0` alone cannot distinguish "the idle-release thread never
# fired" from "it fired, then the service was upgraded an hour ago". status()
# publishes the process start these counters are measured from
# (`counters_since`) so a remote reader can tell the two apart without SSH.
_LAST_RELEASE_AT: float | None = None
_LAST_RELEASE_REASON: str | None = None
_LAST_RELEASE_DETAILS: dict | None = None
_LAST_ERROR: str | None = None
_RELEASE_COUNT = 0
_RELEASING = False


def _read() -> dict:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    mode = raw.get("mode") if isinstance(raw, dict) else None
    return {"mode": mode if mode in MODES else default_mode()}


def save(mode: object) -> dict:
    if not isinstance(mode, str) or mode not in MODES:
        raise HTTPException(400, f"mode must be one of: {', '.join(MODES)}")
    value = {"mode": mode}
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    partial = SETTINGS_FILE.with_suffix(".json.tmp")
    partial.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, SETTINGS_FILE)
    return value


def _active() -> bool:
    return bool(
        (_GEN_MANAGER and _GEN_MANAGER.has_active_jobs())
        or (_STT_MANAGER and _STT_MANAGER.is_active())
    )


def _loaded_models() -> list[list[str]]:
    values: list[list[str]] = []
    if _GEN_MANAGER:
        values.extend([list(item) for item in _GEN_MANAGER.loaded_model_keys()])
    if _STT_MANAGER:
        key = _STT_MANAGER.loaded_model_key()
        if key:
            values.append(list(key))
    return values


def _last_activity() -> float | None:
    values = []
    if _GEN_MANAGER and _GEN_MANAGER.last_activity_at() is not None:
        values.append(_GEN_MANAGER.last_activity_at())
    if _STT_MANAGER and _STT_MANAGER.last_activity_at() is not None:
        values.append(_STT_MANAGER.last_activity_at())
    return max(values) if values else None


def _release(reason: str) -> dict:
    global _LAST_RELEASE_AT, _LAST_RELEASE_REASON, _LAST_RELEASE_DETAILS
    global _LAST_ERROR, _RELEASE_COUNT, _RELEASING
    with _LOCK:
        if _RELEASING:
            raise HTTPException(409, "A memory release is already running")
        if _GEN_MANAGER is None or _STT_MANAGER is None or _GPU_LOCK is None:
            raise HTTPException(503, "Voice Studio memory managers are not ready")
        if _active():
            raise HTTPException(409, "Voice generation or transcription is active; memory was not released")
        _RELEASING = True
    try:
        with _GPU_LOCK:
            if _active():
                raise HTTPException(409, "Voice work started before memory could be released")
            tts = _GEN_MANAGER.release_memory_locked(reason=reason)
            stt = _STT_MANAGER.release_memory_locked(reason=reason)
        details = {
            "released": bool(tts.get("released") or stt.get("released")),
            "models": (tts.get("models") or []) + (stt.get("models") or []),
            "actions": (tts.get("actions") or []) + (stt.get("actions") or []),
            "reason": reason,
        }
        with _LOCK:
            _LAST_RELEASE_AT = time.time()
            _LAST_RELEASE_REASON = reason
            _LAST_RELEASE_DETAILS = details
            _LAST_ERROR = None
            _RELEASE_COUNT += 1
            _RELEASING = False
        print(f"[memory] released voice accelerator memory ({reason}): {details}", flush=True)
        return status()
    except HTTPException:
        raise
    except Exception as exc:
        with _LOCK:
            _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        raise HTTPException(409, f"Memory release deferred: {exc}") from exc
    finally:
        with _LOCK:
            _RELEASING = False


def release_now() -> dict:
    return _release("manual")


def run_due_release(now: float | None = None) -> dict | None:
    current = time.time() if now is None else float(now)
    with _LOCK:
        mode = _read()["mode"]
        threshold = MODES[mode]["idle_seconds"]
        loaded = _loaded_models()
        activity = _last_activity()
        if threshold is None or not loaded or _active() or _RELEASING or activity is None:
            return None
        idle = max(0.0, current - activity)
        if idle < threshold:
            return None
        if _LAST_RELEASE_AT is not None and _LAST_RELEASE_AT >= activity:
            return None
    return _release(f"automatic:{mode}")


def status() -> dict:
    with _LOCK:
        mode = _read()["mode"]
        threshold = MODES[mode]["idle_seconds"]
        loaded = _loaded_models()
        activity = _last_activity()
        idle = max(0.0, time.time() - activity) if loaded and activity is not None else None
        due_at = None
        if threshold is not None and idle is not None:
            due_at = time.time() + max(0, threshold - idle)
        active = _active()
        return {
            "mode": mode,
            "default_mode": default_mode(),
            "idle_seconds": threshold,
            "options": [{"mode": key, **value} for key, value in MODES.items()],
            "loaded_models": loaded,
            "model_idle_seconds": idle,
            "active_work": active,
            "busy": bool(active or _RELEASING),
            "next_release_at": due_at,
            "last_release_at": _LAST_RELEASE_AT,
            "last_release_reason": _LAST_RELEASE_REASON,
            "last_release_details": _LAST_RELEASE_DETAILS,
            "last_error": _LAST_ERROR,
            "release_count": _RELEASE_COUNT,
            # The provenance of every counter above. Without it a remote
            # reader cannot tell a lifetime zero from a since-restart zero.
            "counters_since": restart_health.PROCESS_STARTED_AT,
            "process": restart_health.process_start_snapshot(),
        }


def start_background(gen_manager, stt_manager, gpu_lock) -> None:
    global _GEN_MANAGER, _STT_MANAGER, _GPU_LOCK, _STARTED
    _GEN_MANAGER = gen_manager
    _STT_MANAGER = stt_manager
    _GPU_LOCK = gpu_lock
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True

    def loop() -> None:
        while True:
            time.sleep(CHECK_INTERVAL_SECONDS)
            try:
                run_due_release()
            except HTTPException as exc:
                print(f"[memory] automatic release deferred: {exc.detail}", flush=True)
            except Exception as exc:
                print(f"[memory] automatic release failed: {exc}", flush=True)

    threading.Thread(target=loop, name="memory-policy", daemon=True).start()
