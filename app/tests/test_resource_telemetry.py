from __future__ import annotations

from backend import resource_telemetry


def _sample(*, available: float, used: float, percent: float, swap: float,
            rss: float, pressure: int, mlx_active: float) -> dict:
    labels = {1: "normal", 2: "warning", 4: "urgent", 8: "critical"}
    return {
        "at": 1.0,
        "host": {
            "total_gb": 8.0,
            "available_gb": available,
            "used_gb": used,
            "used_percent": percent,
            "pressure": {
                "supported": True,
                "raw": pressure,
                "level": labels[pressure],
            },
            "swap_used_gb": swap,
            "swap_in_bytes": round(swap * 1_000),
            "swap_out_bytes": round(swap * 2_000),
        },
        "worker": {"rss_gb": rss, "process_count": 2},
        "mlx": {
            "supported": True,
            "active_gb": mlx_active,
            "cache_gb": mlx_active / 2,
            "reported_peak_gb": mlx_active + 0.25,
        },
    }


def test_sampler_reports_observed_peaks_deltas_and_outcome(monkeypatch) -> None:
    snapshots = iter([
        _sample(available=4.0, used=4.0, percent=50, swap=0.1,
                rss=0.4, pressure=1, mlx_active=0.2),
        _sample(available=1.5, used=6.5, percent=81.25, swap=0.4,
                rss=2.7, pressure=4, mlx_active=1.9),
        _sample(available=3.0, used=5.0, percent=62.5, swap=0.3,
                rss=1.1, pressure=1, mlx_active=0.8),
    ])
    monkeypatch.setattr(
        resource_telemetry,
        "_snapshot",
        lambda **_kwargs: next(snapshots),
    )
    published: list[dict] = []
    sampler = resource_telemetry.JobResourceSampler(
        published.append, interval_seconds=60
    ).start()
    sampler._take()

    result = sampler.finish(
        state="done",
        memory_failure=False,
        restart_scheduled=False,
        model_retained=True,
    )

    assert result["schema"] == "voicestudio.resource-telemetry"
    assert result["schema_version"] == 1
    assert result["sampling"]["samples"] == 3
    assert result["host"]["minimum_available_gb"] == 1.5
    assert result["host"]["maximum_used_percent"] == 81.25
    assert result["host"]["peak_pressure_level"] == "urgent"
    assert result["host"]["maximum_swap_used_gb"] == 0.4
    assert result["host"]["swap_used_delta_gb"] == 0.2
    assert result["worker"]["peak_rss_gb"] == 2.7
    assert result["mlx"]["peak_active_gb"] == 1.9
    assert result["outcome"] == {
        "state": "done",
        "memory_failure": False,
        "restart_scheduled": False,
        "model_retained": True,
    }
    assert published[-1] == result


def test_sampler_is_explicit_when_platform_probes_are_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(resource_telemetry, "_snapshot", lambda **_kwargs: None)
    published: list[dict] = []
    sampler = resource_telemetry.JobResourceSampler(
        published.append, interval_seconds=60
    ).start()

    result = sampler.finish(
        state="error",
        memory_failure=True,
        restart_scheduled=True,
        model_retained=False,
    )

    assert result["sampling"]["samples"] == 0
    assert result["host"]["minimum_available_gb"] is None
    assert result["mlx"]["supported"] is False
    assert result["outcome"]["memory_failure"] is True
