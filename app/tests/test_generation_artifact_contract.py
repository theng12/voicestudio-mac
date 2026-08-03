from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import cache, generation, main, voicestudio_genstudio_integration


QWEN_CUSTOM_REPO = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
QWEN_BASE_REPO = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
CHATTERBOX_REPO = "mlx-community/chatterbox-4bit"


def _tone(seconds: float, sample_rate: int = 1_000) -> np.ndarray:
    samples = round(seconds * sample_rate)
    return 0.3 * np.sin(2 * np.pi * 110 * np.arange(samples) / sample_rate)


def test_qwen_custom_terminal_silence_trim_preserves_normal_interior_pauses(
    tmp_path: Path,
) -> None:
    output = tmp_path / "qwen-custom-terminal-silence.wav"
    sample_rate = 1_000
    # The middle one-second pause is deliberate narration timing.  Only the
    # pathological tail after the second audible phrase may be corrected.
    original = np.concatenate((
        _tone(0.5, sample_rate),
        np.zeros(round(1.0 * sample_rate)),
        _tone(0.5, sample_rate),
        np.zeros(round(3.0 * sample_rate)),
    ))
    sf.write(output, original, sample_rate, subtype="PCM_16")

    removed = generation._trim_qwen_custom_terminal_silence(output, QWEN_CUSTOM_REPO)
    corrected, corrected_rate = sf.read(output, dtype="float32")

    assert corrected_rate == sample_rate
    assert removed == pytest.approx(2.75, abs=0.03)
    assert len(corrected) / sample_rate == pytest.approx(2.25, abs=0.03)
    assert np.max(np.abs(corrected[:500])) > 0.1
    assert np.max(np.abs(corrected[500:1_500])) < 0.0001
    assert np.max(np.abs(corrected[1_500:2_000])) > 0.1


def test_qwen_custom_pathological_tail_updates_final_artifact_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "qwen-uncle-fu.wav"
    sample_rate = 1_000
    # Mirrors the reported shape: a short spoken sample followed by an
    # implausibly long silent tail.  This test does not call a model/provider.
    sf.write(
        output,
        np.concatenate((_tone(4.2295, sample_rate), np.zeros(round(91.7705 * sample_rate)))),
        sample_rate,
        subtype="PCM_16",
    )

    removed = generation._trim_qwen_custom_terminal_silence(output, QWEN_CUSTOM_REPO)
    job = generation.GenerationJob(
        job_id="uncle-fu-trim-evidence",
        mode="txt2speech",
        params={"repo": QWEN_CUSTOM_REPO, "preset_speaker": "Uncle_Fu"},
    )
    generation.GenerationManager._record_final_audio_evidence(job, output)

    assert removed > 90
    assert job.audio_duration_s == pytest.approx(4.48, abs=0.03)
    assert job.audio_duration_ms == round(job.audio_duration_s * 1_000)
    assert job.bytes == output.stat().st_size
    assert job.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()


def test_chatterbox_terminal_blip_does_not_preserve_pathological_silence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "chatterbox-spanish-terminal-blip.wav"
    sample_rate = 1_000
    # Matches the observed Spanish Chatterbox shape: audible speech through
    # 3.749125s, 40.76s of silence, a ~27ms blip, then final silence to 48s.
    speech_end = 3.749125
    blip_start = 44.511
    blip_end = 44.537958
    total = 48.0
    sf.write(
        output,
        np.concatenate((
            _tone(speech_end, sample_rate),
            np.zeros(round((blip_start - speech_end) * sample_rate)),
            _tone(blip_end - blip_start, sample_rate),
            np.zeros(round((total - blip_end) * sample_rate)),
        )),
        sample_rate,
        subtype="PCM_16",
    )

    removed = generation._trim_model_terminal_silence(
        output, CHATTERBOX_REPO, "chatterbox-mlx"
    )
    job = generation.GenerationJob(
        job_id="chatterbox-spanish-trim-evidence",
        mode="txt2speech",
        params={"repo": CHATTERBOX_REPO},
    )
    generation.GenerationManager._record_final_audio_evidence(job, output)

    assert removed > 43
    assert job.audio_duration_s == pytest.approx(4.0, abs=0.03)
    assert job.bytes == output.stat().st_size
    assert job.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()


def test_qwen_custom_short_valid_tail_is_left_byte_for_byte_unchanged(tmp_path: Path) -> None:
    output = tmp_path / "qwen-custom-short-valid.wav"
    sample_rate = 1_000
    sf.write(
        output,
        np.concatenate((_tone(0.5, sample_rate), np.zeros(round(0.2 * sample_rate)))),
        sample_rate,
        subtype="PCM_16",
    )
    before = output.read_bytes()

    assert generation._trim_qwen_custom_terminal_silence(output, QWEN_CUSTOM_REPO) == 0.0
    assert output.read_bytes() == before


def test_terminal_silence_correction_does_not_apply_to_qwen_clone(tmp_path: Path) -> None:
    output = tmp_path / "qwen-base.wav"
    sample_rate = 1_000
    sf.write(
        output,
        np.concatenate((_tone(0.5, sample_rate), np.zeros(round(3.0 * sample_rate)))),
        sample_rate,
        subtype="PCM_16",
    )
    before = output.read_bytes()

    assert generation._trim_qwen_custom_terminal_silence(output, QWEN_BASE_REPO) == 0.0
    assert output.read_bytes() == before


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
    assert result["integration_name"] == "voicestudio_genstudio_integration"
    assert result["integration_version"] == "1.1"
    assert set(voicestudio_genstudio_integration.FINAL_TTS_RESULT_FIELDS) <= set(result)
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


def test_local_generation_serializes_and_persists_worker_resource_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "TTS_AVAILABLE", True)
    monkeypatch.setattr(generation.cache, "snapshot_revision", lambda _repo: "5" * 40)

    class FakeSampler:
        def __init__(self, publish):
            self.publish = publish

        def start(self):
            self.publish({"schema": "voicestudio.resource-telemetry", "live": True})
            return self

        def finish(self, **outcome):
            result = {
                "schema": "voicestudio.resource-telemetry",
                "schema_version": 1,
                "outcome": outcome,
            }
            self.publish(result)
            return result

    monkeypatch.setattr(generation.resource_telemetry, "JobResourceSampler", FakeSampler)
    manager = object.__new__(generation.GenerationManager)
    manager._consecutive_memory_failures = 0
    manager._last_memory_event = None
    manager._restart_scheduled = False
    manager._last_model_activity_at = None
    manager._loaded_model = object()
    manager._persist = lambda: None
    manager._evict_loaded_models = lambda reason="": {}

    def generate(_job, output_path: Path) -> None:
        sf.write(output_path, np.zeros(1000, dtype=np.float32), 1000, subtype="PCM_16")

    manager._dispatch_txt2speech = generate
    job = generation.GenerationJob(
        job_id="resource-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
            "preset_speaker": "Ryan",
        },
    )

    manager._run_txt2speech(job)

    assert job.resource_usage["outcome"]["state"] == "done"
    assert job.resource_usage["outcome"]["model_retained"] is True
    assert job.serialize()["resource_usage"] == job.resource_usage
    restored = generation.GenerationManager._from_disk(
        generation.GenerationManager._to_disk(job)
    )
    assert restored is not None
    assert restored.resource_usage == job.resource_usage


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
