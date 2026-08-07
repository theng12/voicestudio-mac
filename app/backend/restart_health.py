"""Read-only restart evidence for operators and Studio Hub.

Two independent kinds of evidence live here because a reader needs both to
answer one question — "did this process restart?":

* `restart_rate_snapshot()` parses the watchdog log, so it only ever sees
  restarts the *watchdog* performed. A deliberate upgrade, a `launchctl`
  bounce, or an operator restarting the service by hand leaves no line in that
  log at all, so `last_restart_at: null` is not evidence of a long-lived
  process.
* `process_start_snapshot()` reports when *this* process actually started,
  whatever caused it. That is the only reading that makes an in-process
  counter interpretable: `release_count: 0` means "never fired" only if the
  process has been up long enough for it to have fired.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os
import re
import time


LAUNCHER_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_LOG = LAUNCHER_ROOT / "logs" / "service" / "watchdog.log"
_MAX_LOG_BYTES = 256 * 1024
_RESTART_LINE = re.compile(
    r"^\[watchdog\] (?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?:no /api/health\b|health probe failed \d+ consecutive times\b)"
)


def _resolve_process_started_at() -> float:
    """Best-effort true process start, resolved once at first import.

    `psutil` reports the kernel's own create time, which is correct even if
    this module is imported late during startup. Import time is the fallback
    so a base-only install still gets a usable — slightly late — anchor.
    """
    try:
        import psutil

        return float(psutil.Process(os.getpid()).create_time())
    except Exception:
        return time.time()


PROCESS_STARTED_AT = _resolve_process_started_at()


def process_start_snapshot(*, now: float | None = None) -> dict:
    """Return when this process started, so in-process counters can be read.

    The absolute epoch timestamp is the primary value: it is directly
    comparable with the other absolute timestamps this API already publishes
    (`last_release_at`, `next_release_at`, job `started_at`), and it does not
    drift between the moment a probe is served and the moment it is read.
    `uptime_seconds` is derived from it purely for human readability — a
    reader should never have to subtract epochs by hand to learn that a
    zeroed counter belongs to a process that has only been up for 40 seconds.
    """
    current = time.time() if now is None else float(now)
    return {
        "pid": os.getpid(),
        "started_at": PROCESS_STARTED_AT,
        "started_at_iso": datetime.fromtimestamp(PROCESS_STARTED_AT).isoformat(
            timespec="seconds"
        ),
        "uptime_seconds": round(max(0.0, current - PROCESS_STARTED_AT), 3),
    }


def _tail_text(path: Path) -> str:
    """Read a bounded tail so a busy health probe never scans an unbounded log."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _MAX_LOG_BYTES))
            raw = handle.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def restart_rate_snapshot(
    path: Path = WATCHDOG_LOG,
    *,
    now: datetime | None = None,
) -> dict:
    """Return bounded restart counts without changing watchdog or service state."""
    observed_at = now or datetime.now()
    events: list[datetime] = []
    for line in _tail_text(path).splitlines():
        match = _RESTART_LINE.match(line.strip())
        if not match:
            continue
        try:
            event = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
            if event <= observed_at:
                events.append(event)
        except ValueError:
            continue

    last_day = observed_at - timedelta(hours=24)
    last_week = observed_at - timedelta(days=7)
    restarts_24h = sum(event >= last_day for event in events)
    restarts_7d = sum(event >= last_week for event in events)

    if restarts_24h >= 6 or restarts_7d >= 20:
        status = "critical"
    elif restarts_24h >= 2 or restarts_7d >= 5:
        status = "warning"
    else:
        status = "healthy"

    if restarts_24h >= 2 or (restarts_24h and restarts_7d == restarts_24h):
        message = f"{restarts_24h} watchdog restarts in the last 24 hours"
    elif restarts_7d:
        message = f"{restarts_7d} watchdog restarts in the last 7 days"
    else:
        message = "No watchdog restarts observed in the last 7 days"

    return {
        "status": status,
        "alert": status in {"warning", "critical"},
        "restarts_24h": restarts_24h,
        "restarts_7d": restarts_7d,
        "last_restart_at": max(events).isoformat(timespec="seconds") if events else None,
        "observed_at": observed_at.isoformat(timespec="seconds"),
        "message": message,
    }
