from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import catalog, generation, qwen_quality, transcription


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


def _long_form_with_sentinel(*, repeated: bool = False) -> str:
    body = (
        "The harbor keeper records each lantern before the evening tide returns. "
        * 320
        if repeated
        else " ".join(
            f"Marker {index} records a distinct harbor observation before sunset."
            for index in range(1, 420)
        )
    )
    sentinel = (
        "At dawn the final courier carries amber maps beyond quiet cliffs while "
        "patient sailors count twenty four silver bells beside the northern beacon."
    )
    return f"{body} {sentinel}"


def test_long_form_repeated_source_accepts_exact_ordered_terminal_words() -> None:
    expected = _long_form_with_sentinel(repeated=True)

    evidence = qwen_quality.validate_output(
        expected,
        _stt(expected, duration=2_400.0),
        max_duration_s=3_000.0,
    )

    assert evidence["accepted"] is True
    assert evidence["validator_revision"] == "voicestudio.qwen-clone-quality.v1"
    assert evidence["terminal_gate"] == {
        "revision": "voicestudio.qwen-clone-quality.v2",
        "window_size": 24,
        "aligned_word_count": len(expected.split()),
        "spelling_variant_count": 0,
        "hard_mismatch_count": 0,
        "accepted": True,
    }


def test_long_form_terminal_spelling_variant_is_accepted_without_transcript_evidence() -> None:
    expected = _long_form_with_sentinel(repeated=True)
    observed = expected.replace("sailors", "sailours", 1)

    evidence = qwen_quality.validate_output(
        expected,
        _stt(observed, duration=2_400.0),
        max_duration_s=3_000.0,
    )

    assert evidence["accepted"] is True
    assert evidence["terminal_gate"]["spelling_variant_count"] == 1
    assert evidence["terminal_gate"]["hard_mismatch_count"] == 0
    assert "sailors" not in str(evidence)
    assert "sailours" not in str(evidence)


@pytest.mark.parametrize(
    ("observed_builder", "minimum_hard_mismatches"),
    [
        (lambda text: " ".join(text.split()[:-3]), 3),
        (lambda text: f"{text} this was a pretty tight", 5),
        (
            lambda text: " ".join(
                [*text.split()[:-2], text.split()[-1], text.split()[-2]]
            ),
            2,
        ),
    ],
    ids=["missing-final-words", "extra-terminal-phrase", "terminal-order-corruption"],
)
def test_long_form_terminal_misalignment_is_rejected(
    observed_builder, minimum_hard_mismatches: int
) -> None:
    expected = _long_form_with_sentinel(repeated=True)

    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(
            expected,
            _stt(observed_builder(expected), duration=2_400.0),
            max_duration_s=3_000.0,
        )

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"
    assert caught.value.evidence["terminal_gate"]["hard_mismatch_count"] >= minimum_hard_mismatches
    assert caught.value.evidence["terminal_gate"]["accepted"] is False


def test_long_form_gate_uses_retained_word_timestamps_not_padded_segment_text() -> None:
    expected = _long_form_with_sentinel(repeated=True)
    result = _stt(expected, duration=2_400.0)
    result["segments"][0]["text"] = f"{expected} this was a pretty tight"

    evidence = qwen_quality.validate_output(expected, result, max_duration_s=3_000.0)

    assert evidence["accepted"] is True
    result["segments"][0]["words"].extend(
        {"word": word, "start": 2_399.0, "end": 2_399.1}
        for word in "this was a pretty tight".split()
    )
    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(expected, result, max_duration_s=3_000.0)

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"


def test_long_form_without_retained_word_timestamps_fails_closed() -> None:
    expected = _long_form_with_sentinel(repeated=True)

    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(
            expected,
            _stt(expected, duration=2_400.0, words=False),
            max_duration_s=3_000.0,
        )

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"
    assert caught.value.evidence["terminal_gate"] == {
        "revision": "voicestudio.qwen-clone-quality.v2",
        "window_size": 24,
        "aligned_word_count": 0,
        "spelling_variant_count": 0,
        "hard_mismatch_count": 24,
        "accepted": False,
    }


def test_approximately_25k_long_form_uses_bounded_terminal_comparison(monkeypatch) -> None:
    expected = _long_form_with_sentinel()
    assert 20_000 < len(expected) < 30_000
    original_distance = qwen_quality._distance

    def reject_request_sized_distance(left, right):
        if max(len(left), len(right)) > 24:
            raise AssertionError("long-form terminal validation must stay bounded")
        return original_distance(left, right)

    monkeypatch.setattr(qwen_quality, "_distance", reject_request_sized_distance)
    evidence = qwen_quality.validate_output(
        expected,
        _stt(expected, duration=12_000.0),
        max_duration_s=13_000.0,
    )

    assert evidence["accepted"] is True
    assert evidence["comparison_method"] == {
        "tokens": "2-gram-multiset",
        "characters": "4-gram-multiset",
    }
    assert evidence["terminal_gate"]["window_size"] == 24
    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(
            expected,
            _stt(f"{expected} this was a pretty tight", duration=12_000.0),
            max_duration_s=13_000.0,
        )

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"


def test_existing_short_form_qwen_audit_contract_remains_v1() -> None:
    expected = "The existing audited Qwen clone path retains its short response contract."

    evidence = qwen_quality.validate_output(
        expected,
        _stt(expected, duration=12.0),
        max_duration_s=30.0,
    )

    assert evidence["accepted"] is True
    assert evidence["validator_revision"] == "voicestudio.qwen-clone-quality.v1"
    assert "terminal_gate" not in evidence


@pytest.mark.parametrize(
    "mutate_word",
    [
        lambda word, _duration: word.pop("start"),
        lambda word, _duration: word.pop("end"),
        lambda word, _duration: word.update(start=float("nan")),
        lambda word, _duration: word.update(end=float("inf")),
        lambda word, duration: word.update(start=duration),
        lambda word, duration: word.update(end=duration + 0.1),
        lambda word, _duration: word.update(start=1.0, end=0.9),
    ],
    ids=[
        "missing-start",
        "missing-end",
        "nonfinite-start",
        "nonfinite-end",
        "start-at-eof",
        "end-after-eof",
        "reversed-range",
    ],
)
def test_long_form_gate_fails_closed_for_invalid_word_timestamps(mutate_word) -> None:
    expected = _long_form_with_sentinel(repeated=True)
    result = _stt(expected, duration=2_400.0)
    mutate_word(result["segments"][0]["words"][-1], result["duration"])

    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(expected, result, max_duration_s=3_000.0)

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"
    assert caught.value.evidence["terminal_gate"]["accepted"] is False


def test_long_form_gate_fails_closed_for_descending_word_timestamps() -> None:
    expected = _long_form_with_sentinel(repeated=True)
    result = _stt(expected, duration=2_400.0)
    words = result["segments"][0]["words"]
    words[-2].update(start=1.0, end=1.1)
    words[-1].update(start=0.9, end=1.0)

    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(expected, result, max_duration_s=3_000.0)

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"
    assert caught.value.evidence["terminal_gate"]["accepted"] is False


@pytest.mark.parametrize(
    "mutate_word",
    [
        lambda word: word.pop("start"),
        lambda word: word.pop("end"),
        lambda word: word.update(start=float("nan")),
        lambda word: word.update(end=float("inf")),
        lambda word: word.update(start=1.0, end=0.9),
    ],
    ids=[
        "missing-start",
        "missing-end",
        "nonfinite-start",
        "nonfinite-end",
        "reversed-range",
    ],
)
def test_normalization_drops_invalid_word_timestamp_before_long_form_gate(mutate_word) -> None:
    expected = _long_form_with_sentinel(repeated=True)
    raw_words = [
        {"word": word, "start": 0.0, "end": 0.2}
        for word in expected.split()
    ]
    mutate_word(raw_words[-1])
    normalized_text, segments = transcription._normalize_segments(
        [{
            "start": 0.0,
            "end": 2_400.0,
            "text": expected,
            "words": raw_words,
        }],
        word_timestamps=True,
        audio_duration=2_400.0,
    )

    with pytest.raises(qwen_quality.QwenQualityError) as caught:
        qwen_quality.validate_output(
            expected,
            {
                "text": normalized_text,
                "duration": 2_400.0,
                "segments": segments,
            },
            max_duration_s=3_000.0,
        )

    assert caught.value.code == "QWEN_OUTPUT_TEXT_MISMATCH"
    assert caught.value.evidence["terminal_gate"]["accepted"] is False


def test_job_owned_reference_validation_attaches_redacted_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    from backend import transcription

    reference = tmp_path / "aiden.wav"
    reference.write_bytes(b"immutable-reference")
    transcript = "Aiden reads a calm and accurately aligned reference."
    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
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
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
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
    assert [entry["accepted"] for entry in job.quality_retry_history] == [False, True]
    assert job.quality_retry_history[0]["rejection_code"] == "QWEN_OUTPUT_TEXT_MISMATCH"


def test_qwen_output_mismatch_on_retry_is_terminal_and_preserves_attempt_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
    manager._last_model_activity_at = None
    manager._consecutive_memory_failures = 0
    manager._restart_scheduled = False
    manager._loaded_model = None
    attempts = []
    text = " ".join(
        f"Controlled recovery sentence {index} remains transcript bound."
        for index in range(1, 9)
    )

    def dispatch(job, path):
        attempts.append({
            "seed": job.params.get("_qwen_attempt_seed", job.params.get("seed")),
            "section_max": job.params.get("_qwen_section_max_characters"),
            "repo": job.params["repo"],
            "text": job.params["text"],
            "voice_library_id": job.params.get("voice_library_id"),
        })
        sf.write(path, np.zeros(2400, dtype=np.float32), 24000)

    def validate(_job, _path):
        raise qwen_quality.QwenQualityError(
            "QWEN_OUTPUT_TEXT_MISMATCH",
            "deterministic recovery control mismatch",
            {
                "validator_revision": qwen_quality.VALIDATOR_REVISION,
                "kind": "output",
                "expected_tokens": len(text.split()),
                "observed_tokens": 0,
            },
        )

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
        job_id="quality-retry-terminal",
        mode="txt2speech",
        params={
            "repo": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
            "voice_library_id": "aiden",
            "text": text,
            "seed": 41,
            "_qwen_reference_validation": {"accepted": True},
        },
    )
    manager._run_txt2speech(job)

    assert job.state == "error"
    assert job.error_code == "QWEN_OUTPUT_TEXT_MISMATCH"
    assert job.quality_retry_count == 1
    assert job.output_path is None
    assert list(tmp_path.iterdir()) == []
    assert [attempt["seed"] for attempt in attempts] == [41, 42]
    assert [attempt["section_max"] for attempt in attempts] == [
        None,
        qwen_quality.RETRY_SECTION_MAX_CHARACTERS,
    ]
    assert all(attempt["repo"] == job.params["repo"] for attempt in attempts)
    assert all(attempt["text"] == text for attempt in attempts)
    assert all(attempt["voice_library_id"] == "aiden" for attempt in attempts)
    assert len(job.quality_retry_history) == 2
    assert [entry["attempt"] for entry in job.quality_retry_history] == [1, 2]
    assert [entry["rejection_code"] for entry in job.quality_retry_history] == [
        "QWEN_OUTPUT_TEXT_MISMATCH",
        "QWEN_OUTPUT_TEXT_MISMATCH",
    ]
    assert all("text" not in entry and "path" not in entry for entry in job.quality_retry_history)
    assert generation.GenerationManager._to_disk(job)["quality_retry_history"] == (
        job.quality_retry_history
    )
    assert job.serialize()["quality_retry_history"] == job.quality_retry_history
