from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import catalog, generation, qwen_quality


def _stt(text: str, *, duration: float = 12.0, words: bool = True) -> dict:
    return {
        "text": text,
        "model": qwen_quality.WHISPER_REPO,
        "duration": duration,
        "segments": [{
            "start": 0.0,
            "end": duration,
            "text": text,
            "words": ([{"word": word, "start": 0.0, "end": 0.2} for word in text.split()]
                      if words else []),
        }],
    }


def test_matching_reference_requires_and_preserves_word_alignment() -> None:
    expected = "Aiden reads this clean reference at a calm and natural pace."
    evidence = qwen_quality.validate_reference(expected, _stt(expected))

    assert evidence["accepted"] is True
    assert evidence["word_timestamp_count"] == len(expected.split())
    assert "Aiden" not in str(evidence)


def test_reference_mismatch_is_a_stable_machine_readable_failure() -> None:
    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_reference(
            "The exact reference transcript belongs here.",
            _stt("Completely unrelated words were spoken in the audio."),
        )

    assert caught.value.code == "QWEN_REFERENCE_TRANSCRIPT_MISMATCH"
    assert caught.value.evidence["token_error_rate"] > 0.35


def test_reference_without_word_timestamps_is_rejected() -> None:
    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_reference("Aligned words are required.", _stt(
            "Aligned words are required.", words=False
        ))

    assert caught.value.code == "QWEN_REFERENCE_ALIGNMENT_UNAVAILABLE"


def test_automatic_budget_stops_the_observed_96_second_exhaustion() -> None:
    text = (
        "A professional narrator reads a clear production passage with stable "
        "pacing, accurate wording, and no repeated phrases. " * 2
    )
    limit = qwen_quality.automatic_duration_limit(text)
    tokens = qwen_quality.max_tokens_for_text(text)

    assert 20.0 < limit < 70.0
    assert tokens < 1200


def test_catalog_publishes_qwen_guardrail_dependency() -> None:
    model = catalog.get_model("mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit")
    guardrails = catalog.serialize_model(model)["execution_contract"]["quality_guardrails"]

    assert guardrails["output_transcript_validation"] is True
    assert guardrails["required_local_models"] == [qwen_quality.WHISPER_REPO]
    assert guardrails["max_local_quality_retries"] == 1


def test_output_repetition_is_rejected_even_inside_duration_budget() -> None:
    expected = "The ship crossed the quiet sea before sunrise."
    repeated = " ".join(["The ship crossed the quiet sea"] * 8)
    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(
            expected,
            _stt(repeated, duration=20.0),
            max_duration_s=30.0,
        )

    assert caught.value.code in {
        "QWEN_OUTPUT_TEXT_MISMATCH",
        "QWEN_OUTPUT_REPETITION_DETECTED",
    }


def test_long_form_comparison_uses_bounded_ngram_evidence() -> None:
    expected = "Ancient sailors crossed the open sea under a field of stars. " * 700
    evidence = qwen_quality.validate_output(
        expected,
        _stt(expected, duration=2_400.0),
        max_duration_s=3_000.0,
    )

    assert evidence["accepted"] is True
    assert evidence["comparison_method"]["tokens"] == "2-gram-multiset"
    assert evidence["comparison_method"]["characters"] == "4-gram-multiset"


def test_job_owned_reference_validation_attaches_redacted_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    from backend import transcription

    reference = tmp_path / "aiden.wav"
    reference.write_bytes(b"immutable-reference")
    transcript = "Aiden reads a calm and accurately aligned reference."
    manager = object.__new__(generation.GenerationManager)
    monkeypatch.setattr(manager, "_evict_loaded_models", lambda _reason: {})
    monkeypatch.setattr(qwen_quality, "cached_reference_evidence", lambda _key: None)
    monkeypatch.setattr(qwen_quality, "save_reference_evidence", lambda _key, _value: None)
    monkeypatch.setattr(
        transcription.manager,
        "transcribe_locked",
        lambda *_args, **_kwargs: _stt(transcript),
    )
    monkeypatch.setattr(
        transcription.manager,
        "release_memory_locked",
        lambda _reason: {},
    )
    job = generation.GenerationJob(
        job_id="reference-proof",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
            "text": "Generate this line.",
            "ref_transcript": transcript,
            "_reference_audio_path": str(reference),
        },
    )

    with generation._GEN_LOCK:
        manager._validate_qwen_reference_locked(job)

    evidence = job.params["_qwen_reference_validation"]
    assert evidence["accepted"] is True
    assert transcript not in str(evidence)


class _Sampler:
    def __init__(self, publish):
        self.publish = publish

    def start(self):
        return self

    def finish(self, **kwargs):
        return {"outcome": kwargs}


def test_rejected_local_qwen_output_retries_once_with_safer_settings(
    monkeypatch, tmp_path: Path
) -> None:
    manager = object.__new__(generation.GenerationManager)
    manager._last_model_activity_at = None
    manager._consecutive_memory_failures = 0
    manager._restart_scheduled = False
    manager._loaded_model = None
    attempts = []

    def dispatch(job, path):
        attempts.append((
            job.params.get("_qwen_attempt_seed", job.params.get("seed")),
            job.params.get("_qwen_section_max_characters"),
        ))
        sf.write(path, np.zeros(2400, dtype=np.float32), 24000)

    def validate(job, _path):
        if len(attempts) == 1:
            raise qwen_quality.QwenQualityError(
                "QWEN_OUTPUT_TEXT_MISMATCH",
                "rejected control output",
                {"validator_revision": qwen_quality.VALIDATOR_REVISION},
            )
        job.quality_validation = {"accepted": True}

    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "TTS_AVAILABLE", True)
    monkeypatch.setattr(generation.resource_telemetry, "JobResourceSampler", _Sampler)
    monkeypatch.setattr(manager, "_dispatch_txt2speech", dispatch)
    monkeypatch.setattr(manager, "_validate_qwen_reference_locked", lambda _job: None)
    monkeypatch.setattr(manager, "_validate_qwen_output_locked", validate)
    monkeypatch.setattr(manager, "_record_local_revision_evidence", lambda _job: None)
    monkeypatch.setattr(manager, "_record_final_audio_evidence", lambda _job, _path: None)
    monkeypatch.setattr(manager, "_evict_loaded_models", lambda _reason: {})
    monkeypatch.setattr(manager, "_persist", lambda: None)

    job = generation.GenerationJob(
        job_id="quality-retry",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
            "voice_library_id": "aiden",
            "text": "A controlled local result.",
            "seed": 41,
            "_qwen_reference_validation": {"accepted": True},
        },
    )
    manager._run_txt2speech(job)

    assert job.state == "done"
    assert job.quality_retry_count == 1
    assert job.quality_validation == {"accepted": True}
    assert attempts == [(41, None), (42, qwen_quality.RETRY_SECTION_MAX_CHARACTERS)]
