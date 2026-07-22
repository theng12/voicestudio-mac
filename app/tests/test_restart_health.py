from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend import main
from backend.restart_health import restart_rate_snapshot


def _write_events(path: Path, timestamps: list[str]) -> None:
    path.write_text(
        "".join(
            f"[watchdog] {timestamp} no /api/health on :47870 — restarting service\n"
            for timestamp in timestamps
        ),
        encoding="utf-8",
    )


def test_restart_rate_snapshot_is_read_only_and_bounded(tmp_path: Path) -> None:
    log = tmp_path / "watchdog.log"
    _write_events(log, [
        "2026-07-22 11:00:00",
        "2026-07-22 12:00:00",
        "2026-07-20 12:00:00",
        "2026-07-01 12:00:00",
    ])
    before = log.read_bytes()

    snapshot = restart_rate_snapshot(log, now=datetime(2026, 7, 23, 10, 0, 0))

    assert snapshot["status"] == "warning"
    assert snapshot["alert"] is True
    assert snapshot["restarts_24h"] == 2
    assert snapshot["restarts_7d"] == 3
    assert snapshot["last_restart_at"] == "2026-07-22T12:00:00"
    assert log.read_bytes() == before


def test_restart_rate_snapshot_handles_missing_log(tmp_path: Path) -> None:
    snapshot = restart_rate_snapshot(
        tmp_path / "missing.log",
        now=datetime(2026, 7, 23, 10, 0, 0),
    )

    assert snapshot["status"] == "healthy"
    assert snapshot["alert"] is False
    assert snapshot["restarts_24h"] == 0
    assert snapshot["restarts_7d"] == 0
    assert snapshot["last_restart_at"] is None


def test_restart_rate_snapshot_counts_confirmed_failure_restarts(tmp_path: Path) -> None:
    log = tmp_path / "watchdog.log"
    log.write_text(
        "[watchdog] 2026-07-23 09:00:00 health probe failed (1/3); waiting for confirmation\n"
        "[watchdog] 2026-07-23 09:01:00 health probe failed (2/3); waiting for confirmation\n"
        "[watchdog] 2026-07-23 09:02:00 health probe failed 3 consecutive times — restarting service\n",
        encoding="utf-8",
    )

    snapshot = restart_rate_snapshot(log, now=datetime(2026, 7, 23, 10, 0, 0))

    assert snapshot["restarts_24h"] == 1
    assert snapshot["restarts_7d"] == 1
    assert snapshot["last_restart_at"] == "2026-07-23T09:02:00"


def test_restart_rate_message_explains_a_weekly_alert(tmp_path: Path) -> None:
    log = tmp_path / "watchdog.log"
    _write_events(
        log,
        ["2026-07-20 12:00:00"] * 20 + ["2026-07-23 09:00:00"],
    )

    snapshot = restart_rate_snapshot(log, now=datetime(2026, 7, 23, 10, 0, 0))

    assert snapshot["status"] == "critical"
    assert snapshot["restarts_24h"] == 1
    assert snapshot["restarts_7d"] == 21
    assert snapshot["message"] == "21 watchdog restarts in the last 7 days"


def test_health_and_diagnostics_expose_the_same_restart_signal(monkeypatch) -> None:
    expected = {
        "status": "critical",
        "alert": True,
        "restarts_24h": 8,
        "restarts_7d": 12,
        "last_restart_at": "2026-07-23T09:00:00",
        "observed_at": "2026-07-23T10:00:00",
        "message": "8 watchdog restarts in the last 24 hours",
    }
    monkeypatch.setattr(main, "restart_rate_snapshot", lambda: expected.copy())
    monkeypatch.setattr(main, "gen_diagnostics", lambda: {"packages": [], "engines": []})

    assert main.health()["restart_health"] == expected
    assert main.generation_diagnostics()["restart_health"] == expected
