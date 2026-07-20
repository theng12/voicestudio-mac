from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import cache, generation, main


def test_final_wav_evidence_is_derived_from_published_bytes(tmp_path: Path) -> None:
    output = tmp_path / "final.wav"
    sf.write(output, np.zeros(24_000, dtype=np.float32), 24_000, subtype="PCM_16")
    job = generation.GenerationJob(
        job_id="artifact-proof",
        mode="txt2speech",
        params={"repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"},
    )

    generation.GenerationManager._record_final_audio_evidence(job, output)

    result = job.serialize()
    assert result["media_type"] == "audio/wav"
    assert result["format"] == "wav"
    assert result["bytes"] == output.stat().st_size
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result["audio_duration_s"] == pytest.approx(1.0)
    assert result["audio_duration_ms"] == 1000
    assert result["sample_rate_hz"] == 24_000
    assert result["channels"] == 1


def test_failed_generation_never_publishes_a_partial_final_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "TTS_AVAILABLE", True)
    manager = object.__new__(generation.GenerationManager)
    manager._consecutive_memory_failures = 0
    manager._last_memory_event = None
    manager._restart_scheduled = False
    manager._last_model_activity_at = None
    manager._persist = lambda: None
    manager._evict_loaded_models = lambda reason="": {}

    def fail_after_writing(_job, output_path: Path) -> None:
        sf.write(output_path, np.zeros(200, dtype=np.float32), 1000, subtype="PCM_16")
        raise RuntimeError("section 2 failed")

    manager._dispatch_txt2speech = fail_after_writing
    job = generation.GenerationJob(
        job_id="failed-long-form",
        mode="txt2speech",
        params={"repo": "mlx-community/VoxCPM2-4bit"},
    )

    manager._run_txt2speech(job)

    assert job.state == "error"
    assert job.output_path is None
    assert not (tmp_path / "failed-long-form.wav").exists()
    assert list(tmp_path.glob(".failed-long-form*.wav")) == []


def test_success_is_atomically_published_only_after_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "TTS_AVAILABLE", True)
    monkeypatch.setattr(generation.cache, "snapshot_revision", lambda _repo: "4" * 40)
    manager = object.__new__(generation.GenerationManager)
    manager._consecutive_memory_failures = 0
    manager._last_memory_event = None
    manager._restart_scheduled = False
    manager._last_model_activity_at = None
    manager._persist = lambda: None
    manager._evict_loaded_models = lambda reason="": {}
    observed: list[tuple[bool, bool]] = []

    def generate(_job, output_path: Path) -> None:
        final_path = tmp_path / "successful-long-form.wav"
        observed.append((output_path.name.startswith(".successful-long-form"), final_path.exists()))
        sf.write(output_path, np.zeros(1000, dtype=np.float32), 1000, subtype="PCM_16")

    manager._dispatch_txt2speech = generate
    job = generation.GenerationJob(
        job_id="successful-long-form",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
            "preset_speaker": "Ryan",
        },
    )

    manager._run_txt2speech(job)

    final_path = tmp_path / "successful-long-form.wav"
    assert observed == [(True, False)]
    assert job.state == "done"
    assert job.output_path == str(final_path.resolve())
    assert final_path.exists()
    assert list(tmp_path.glob(".successful-long-form*.wav")) == []
    assert job.sha256 == hashlib.sha256(final_path.read_bytes()).hexdigest()


def test_catalog_reports_runtime_cache_load_and_memory_truth(monkeypatch) -> None:
    target = "mlx-community/VoxCPM2-4bit"
    monkeypatch.setattr(
        cache,
        "status_snapshot",
        lambda repo: {"state": "cached" if repo == target else "absent"},
    )
    monkeypatch.setattr(
        cache,
        "cache_state",
        lambda repo: "cached" if repo == target else "absent",
    )
    monkeypatch.setattr(
        main.gen_manager,
        "loaded_model_keys",
        lambda: [(target, "tts-mlx")],
    )
    monkeypatch.setattr(main.gen_manager, "runtime_ready_for_family", lambda family: True)
    monkeypatch.setattr(
        generation,
        "_memory_snapshot",
        lambda: {"total_gb": 8.0, "available_gb": 3.0, "used_gb": 5.0, "percent": 62.5},
    )

    models = {item["repo"]: item for item in main.get_catalog()["models"]}
    vox = models[target]

    assert vox["loaded"] is True
    assert vox["runtime_ready"] is True
    assert vox["available"] is True
    assert vox["cold_load_required_free_memory_gb"] == 3.55
    assert vox["loaded_required_free_memory_gb"] == 2.75
    assert vox["required_free_memory_gb"] == 2.75
    assert vox["memory_eligible"] is True


def test_health_reports_busy_loaded_models_and_live_memory(monkeypatch) -> None:
    monkeypatch.setattr(main.gen_manager, "has_active_jobs", lambda: True)
    monkeypatch.setattr(
        main.gen_manager,
        "loaded_model_keys",
        lambda: [("mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit", "tts-mlx")],
    )
    monkeypatch.setattr(
        generation,
        "_memory_snapshot",
        lambda: {"total_gb": 8.0, "available_gb": 3.2, "used_gb": 4.8, "percent": 60.0},
    )

    health = main.health()

    assert health["busy"] is True
    assert health["loaded_models"] == [
        ["mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit", "tts-mlx"]
    ]
    assert health["memory"]["available_gb"] == 3.2
