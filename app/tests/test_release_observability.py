"""Evidence a fleet probe needs before it can trust the release telemetry.

Two blind spots, both found by a read-only sweep of 19 fleet machines:

1. All 13 8 GB machines reported `release_count: 0`. That is ambiguous between
   "the idle-release thread never fired" and "a restart zeroed an in-process
   counter while job history persisted to disk" — and the v1.32.5 rollout
   required a restart. `restart_health` could not settle it: it only parses
   the watchdog log, so an upgrade or a `launchctl` bounce leaves no trace.
2. `outcome.model_retained` read False on all 19 machines, including one whose
   own release log recorded `cleared mlx_audio_model` — i.e. OmniVoice was
   provably resident and later evicted. The telemetry check asked for
   `self._loaded_model`, an attribute no engine sets.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

from fastapi.testclient import TestClient

from backend import generation, memory_policy, restart_health, transcription
from backend.main import FLEET_TOKEN, app
from backend.restart_health import process_start_snapshot, restart_rate_snapshot

from test_memory_policy import GenerationManager, TranscriptionManager, _reset


# ───────────── fix 1: the process start that makes a counter readable ─────────────


def test_process_start_snapshot_reports_an_absolute_start_and_a_derived_uptime(
    monkeypatch,
) -> None:
    started = datetime(2026, 8, 8, 1, 0, 0).timestamp()
    monkeypatch.setattr(restart_health, "PROCESS_STARTED_AT", started)

    snapshot = process_start_snapshot(now=started + 3725.5)

    # The absolute epoch is the anchor — directly comparable with the other
    # absolute timestamps this API publishes (last_release_at, next_release_at).
    assert snapshot["started_at"] == started
    assert snapshot["started_at_iso"] == "2026-08-08T01:00:00"
    # The duration is derived for readability only, never the sole reading.
    assert snapshot["uptime_seconds"] == 3725.5
    assert snapshot["pid"] > 0


def test_uptime_never_goes_negative_when_the_clock_moves_backwards(monkeypatch) -> None:
    monkeypatch.setattr(restart_health, "PROCESS_STARTED_AT", 2_000.0)
    assert process_start_snapshot(now=1_000.0)["uptime_seconds"] == 0.0


def test_watchdog_silence_is_not_evidence_of_a_long_lived_process(
    tmp_path: Path, monkeypatch
) -> None:
    """The exact ambiguity the fleet sweep hit: an empty watchdog log says
    "no watchdog restarts", which reads like a long uptime and is not. Only the
    process snapshot can contradict it."""
    empty_log = tmp_path / "watchdog.log"
    empty_log.write_text("", encoding="utf-8")
    restarts = restart_rate_snapshot(empty_log, now=datetime(2026, 8, 8, 12, 0, 0))
    assert restarts["last_restart_at"] is None
    assert restarts["restarts_7d"] == 0

    # …yet this process started 40 seconds ago, because an upgrade restarted it.
    now = time.time()
    monkeypatch.setattr(restart_health, "PROCESS_STARTED_AT", now - 40.0)
    assert process_start_snapshot(now=now)["uptime_seconds"] == 40.0


def test_health_publishes_process_start_beside_the_watchdog_history() -> None:
    client = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
    body = client.get("/api/health").json()

    assert body["ok"] is True
    process = body["process"]
    assert isinstance(process["started_at"], float)
    assert process["uptime_seconds"] >= 0
    assert process["started_at_iso"]
    # Kept as separate readings on purpose: one is "what restarted us", the
    # other is "when did we start", and only the second is always populated.
    assert "restart_health" in body
    assert body["restart_health"] is not body["process"]


def test_memory_policy_anchors_its_counters_to_the_process_start(
    tmp_path, monkeypatch
) -> None:
    started = 1_700_000_000.0
    monkeypatch.setattr(restart_health, "PROCESS_STARTED_AT", started)
    _reset(monkeypatch, tmp_path)

    idle = memory_policy.status()
    # A bare `release_count: 0` was unreadable remotely. It now arrives with the
    # process start it was counted from, so a reader can tell a lifetime zero
    # from a zero that a restart produced minutes ago.
    assert idle["release_count"] == 0
    assert idle["counters_since"] == started
    assert idle["process"]["started_at"] == started
    assert idle["process"]["uptime_seconds"] > 0

    released = memory_policy.release_now()
    assert released["release_count"] == 1
    # The anchor does not move when the counter does — it belongs to the process.
    assert released["counters_since"] == started


def test_counters_and_process_snapshot_cannot_drift_apart(tmp_path, monkeypatch) -> None:
    """memory_policy must read the live anchor, not a value bound at import."""
    monkeypatch.setattr(restart_health, "PROCESS_STARTED_AT", 1_234.5)
    _reset(monkeypatch, tmp_path)
    status = memory_policy.status()
    assert status["counters_since"] == status["process"]["started_at"] == 1_234.5


def test_settings_ui_reads_the_release_count_against_the_process_start() -> None:
    root = Path(__file__).resolve().parents[1]
    markup = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (root / "frontend" / "app.js").read_text(encoding="utf-8")

    # The tile used to render the raw integer, which is exactly the unreadable
    # form the fleet sweep tripped over.
    assert 'x-text="memoryPolicy.release_count || 0"' not in markup
    assert "memoryPolicyReleaseCountLabel()" in markup
    assert "memoryPolicyUptimeLabel()" in markup
    assert "memoryPolicyReleaseCountLabel()" in script
    assert "memoryPolicyUptimeLabel()" in script
    assert "counters_since" in script


# ───────────── fix 2: model_retained on the MLX path ─────────────


def _bare_generation_manager() -> generation.GenerationManager:
    """A manager with only its cache slots, bypassing history/cloud resume."""
    manager = generation.GenerationManager.__new__(generation.GenerationManager)
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
    return manager


def test_model_retained_now_sees_a_resident_mlx_model() -> None:
    """OmniVoice runs on the MLX engine, which parks its model on
    `_mlx_audio_model`. The old check read `_loaded_model` — an attribute that
    has never existed — so every OmniVoice job reported model_retained False."""
    manager = _bare_generation_manager()
    manager._mlx_audio_model = object()
    manager._mlx_audio_model_repo = "mlx-community/OmniVoice-0.5B"

    assert manager.loaded_model_keys() == [("mlx-community/OmniVoice-0.5B", "tts-mlx")]
    assert manager.has_loaded_model() is True
    # The exact expression that shipped: it could only ever answer False.
    assert getattr(manager, "_loaded_model", None) is None


def test_model_retained_also_sees_the_f5_engine_and_an_evicted_cache() -> None:
    manager = _bare_generation_manager()
    assert manager.has_loaded_model() is False

    manager._f5_tts_model = object()
    manager._f5_tts_model_repo = "SWivid/F5-TTS"
    assert manager.has_loaded_model() is True

    manager._evict_loaded_models("test-eviction")
    assert manager.has_loaded_model() is False


def test_telemetry_and_release_policy_share_one_definition_of_loaded(
    monkeypatch, tmp_path
) -> None:
    """The release path already identifies the MLX model correctly — it logs
    `cleared mlx_audio_model`. Telemetry must answer from the same accessor
    rather than inventing a second notion of "loaded"."""
    manager = _bare_generation_manager()
    stt = TranscriptionManager(loaded=False)
    _reset(monkeypatch, tmp_path, manager, stt)

    for repo in (None, "mlx-community/OmniVoice-0.5B"):
        manager._mlx_audio_model = object() if repo else None
        manager._mlx_audio_model_repo = repo
        assert bool(memory_policy._loaded_models()) == manager.has_loaded_model()


def test_transcription_retention_uses_the_same_accessor_as_the_release_path() -> None:
    manager = transcription.TranscriptionManager()
    assert manager.has_loaded_model() is False

    manager._model = object()
    # A model without a repo is not what memory_policy would release, so a bare
    # `self._model is not None` disagreed with the policy in this state.
    assert manager.loaded_model_key() is None
    assert manager.has_loaded_model() is False

    manager._model_repo = "mlx-community/whisper-large-v3-turbo"
    assert manager.has_loaded_model() is True


def test_no_engine_attribute_is_probed_that_no_engine_sets() -> None:
    """Guard against reintroducing a private-attribute guess in either
    telemetry site. Residency questions go through has_loaded_model()."""
    backend = Path(__file__).resolve().parents[1] / "backend"
    for name in ("generation.py", "transcription.py"):
        lines = (backend / name).read_text(encoding="utf-8").splitlines()
        sites = [i for i, line in enumerate(lines) if "model_retained=(" in line]
        assert sites, f"{name} no longer reports model_retained"
        for index in sites:
            expression = " ".join(lines[index:index + 4])
            assert "has_loaded_model()" in expression, expression
            assert "getattr(" not in expression, expression
        assert 'getattr(self, "_loaded_model"' not in "\n".join(lines)


def test_release_policy_still_only_reports_it_did_not_change(tmp_path, monkeypatch) -> None:
    """This branch is observability only: the release decision itself must be
    untouched, so a loaded idle model still releases exactly on the threshold."""
    gen, stt = GenerationManager(), TranscriptionManager()
    _reset(monkeypatch, tmp_path, gen, stt)
    memory_policy.save("balanced")
    assert memory_policy.run_due_release(now=699) is None
    assert memory_policy.run_due_release(now=700) is not None
    assert gen.releases == stt.releases == 1


def test_status_still_reports_a_running_release_as_busy(tmp_path, monkeypatch) -> None:
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(memory_policy, "_RELEASING", True)
    assert memory_policy.status()["busy"] is True
    assert memory_policy.status()["counters_since"] is not None
