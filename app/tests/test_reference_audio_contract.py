from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import generation, reference_audio


def _wav(seconds: float = 8.0, sample_rate: int = 24_000) -> bytes:
    silence = np.zeros(sample_rate, dtype=np.float32)
    count = max(1, round((seconds - 1.0) * sample_rate))
    t = np.arange(count, dtype=np.float32) / sample_rate
    speech = 0.2 * np.sin(2 * np.pi * 220 * t)
    out = io.BytesIO()
    sf.write(out, np.concatenate((silence, speech)), sample_rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


def test_reference_preparation_uses_audited_duration_profile(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(reference_audio, "ROOT", tmp_path / "references")
    monkeypatch.setattr(
        reference_audio.model_audits,
        "input_limits",
        lambda _repo: {"reference_audio": {
            "minimum_duration_seconds": 2,
            "maximum_duration_seconds": 4,
            "sample_rate_hz": 16_000,
            "transcript": "optional",
        }},
    )

    prepared = reference_audio.prepare(
        audio_bytes=_wav(), filename="customer.wav", model_id="model/a"
    )

    assert prepared["source_duration_seconds"] == pytest.approx(8.0, abs=0.02)
    assert prepared["duration_seconds"] == pytest.approx(4.0, abs=0.02)
    assert prepared["sample_rate_hz"] == 16_000
    assert Path(prepared["path"]).is_file()
    assert prepared["source_sha256"] != prepared["derived_sha256"]


def test_required_transcript_cannot_be_reused_after_unaligned_cut(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(reference_audio, "ROOT", tmp_path / "references")
    monkeypatch.setattr(
        reference_audio.model_audits,
        "input_limits",
        lambda _repo: {"reference_audio": {
            "minimum_duration_seconds": 2,
            "maximum_duration_seconds": 4,
            "transcript": "required",
        }},
    )

    with pytest.raises(reference_audio.ReferenceAudioError) as error:
        reference_audio.prepare(
            audio_bytes=_wav(), filename="customer.wav", model_id="model/a",
            transcript="This transcript describes the complete recording.",
        )

    assert error.value.code == "REFERENCE_TRANSCRIPT_ALIGNMENT_REQUIRED"


def test_timed_transcript_is_sliced_with_the_selected_reference(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(reference_audio, "ROOT", tmp_path / "references")
    monkeypatch.setattr(
        reference_audio.model_audits,
        "input_limits",
        lambda _repo: {"reference_audio": {
            "minimum_duration_seconds": 2,
            "maximum_duration_seconds": 4,
            "transcript": "required",
        }},
    )

    prepared = reference_audio.prepare(
        audio_bytes=_wav(), filename="customer.wav", model_id="model/a",
        transcript_segments=[
            {"start": 1.0, "end": 2.5, "text": "First sentence."},
            {"start": 2.5, "end": 4.5, "text": "Second sentence."},
            {"start": 4.5, "end": 7.5, "text": "Third sentence."},
        ],
    )

    assert prepared["duration_seconds"] <= 4.01
    assert prepared["transcript"] == "First sentence. Second sentence."


def test_qwen_audit_drives_reference_preparation_contract(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(reference_audio, "ROOT", tmp_path / "references")
    model_id = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"

    prepared = reference_audio.prepare(
        audio_bytes=_wav(seconds=10),
        filename="customer.wav",
        model_id=model_id,
        transcript="These exact words cover the selected ten second reference.",
    )

    assert 8 <= prepared["duration_seconds"] <= 10
    assert prepared["sample_rate_hz"] == 24_000
    assert prepared["profile"]["target_duration_seconds"] == 8
    assert prepared["profile"]["recommended_duration_seconds"] == {
        "minimum": 8,
        "maximum": 12,
    }
    assert prepared["profile"]["transcript"] == "required"


def test_private_reference_path_never_enters_public_job_payload(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        generation.model_audits,
        "input_limits",
        lambda _repo: {"long_form_strategy": "adapter_managed_long_form"},
    )
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"private")
    job = generation.GenerationJob(
        job_id="private-reference",
        mode="txt2speech",
        params={
            "repo": "model/a",
            "text": "hello",
            "_reference_audio_path": str(reference),
            "_reference_audio_sha256": "a" * 64,
            "_reference_source_sha256": "b" * 64,
            "_reference_preparation_revision": "prep-v1",
            "_reference_duration_s": 4.0,
        },
        chunk_total=3,
    )

    result = job.serialize()

    assert "_reference_audio_path" not in result["params"]
    assert str(reference) not in str(result)
    assert result["reference_audio_sha256"] == "a" * 64
    assert result["reference_source_sha256"] == "b" * 64
    assert result["long_form_strategy"] == "adapter_managed_long_form"
    assert result["chunk_total"] == 3


def test_private_reference_is_injected_without_a_library_voice(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"private")
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}

    manager._inject_voice_clone(
        "",
        {"_reference_audio_path": str(reference), "ref_transcript": "Exact words."},
        kwargs,
        voices_module=None,
        fallback_transcript=".",
    )

    assert kwargs == {"ref_audio": str(reference), "ref_text": "Exact words."}


def test_audited_private_section_budget_overrides_family_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        generation.model_audits,
        "input_limits",
        lambda _repo: {"private_section_max_characters": 120},
    )
    text = "Sentence number one is deliberately substantial. " * 10

    chunks = generation._internal_mlx_text_chunks("chatterbox-mlx", "model/a", text)

    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)


def test_terminal_long_form_strategy_comes_from_audit_not_chunk_count(monkeypatch) -> None:
    monkeypatch.setattr(
        generation.model_audits,
        "input_limits",
        lambda _repo: {"long_form_strategy": "adapter_managed_long_form"},
    )
    job = generation.GenerationJob(
        job_id="job-audited-strategy",
        mode="txt2speech",
        params={"repo": "model/a", "text": "A short request."},
        chunk_total=1,
    )

    assert job.serialize()["long_form_strategy"] == "adapter_managed_long_form"
