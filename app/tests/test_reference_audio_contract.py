from __future__ import annotations

import io
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from backend import generation, reference_audio


QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"


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


def test_qwen_17b_private_reference_fails_closed_without_an_audited_profile(
    tmp_path: Path, monkeypatch,
) -> None:
    """An unaudited candidate cannot turn the generic preparation into a claim."""
    monkeypatch.setattr(reference_audio, "ROOT", tmp_path / "references")
    monkeypatch.setattr(reference_audio.model_audits, "input_limits", lambda _repo: {})

    with pytest.raises(reference_audio.ReferenceAudioError) as error:
        reference_audio.prepare(
            audio_bytes=_wav(),
            filename="customer.wav",
            model_id=QWEN_17B_BASE,
            transcript="Exact words.",
        )

    assert error.value.code == "REFERENCE_AUDIO_CONTRACT_UNAVAILABLE"


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


def test_qwen_17b_private_reference_preserves_preparation_evidence(
    tmp_path: Path,
) -> None:
    """A prepared private upload must reach the adapter unchanged and auditable.

    Removing any of the private preparation fields would make the serialized
    GenStudio result lose the prepared duration or its source/derived hashes.
    """
    reference = tmp_path / "prepared-reference.wav"
    reference.write_bytes(b"prepared-private-reference")
    manager = object.__new__(generation.GenerationManager)
    params = {
        "repo": QWEN_17B_BASE,
        "_reference_audio_path": str(reference),
        "_reference_audio_sha256": "a" * 64,
        "_reference_source_sha256": "b" * 64,
        "_reference_preparation_revision": "reference-v1",
        "_reference_duration_s": 8.0,
        "ref_transcript": "Exact prepared words.",
    }
    kwargs: dict = {}

    manager._mlx_kwargs_qwen3(
        SimpleNamespace(repo=QWEN_17B_BASE), params, kwargs, voices_module=None
    )
    result = generation.GenerationJob(
        job_id="prepared-private-reference",
        mode="txt2speech",
        params=params,
    ).serialize()

    assert kwargs == {
        "ref_audio": str(reference),
        "ref_text": "Exact prepared words.",
    }
    assert result["reference_audio_sha256"] == "a" * 64
    assert result["reference_source_sha256"] == "b" * 64
    assert result["reference_preparation_revision"] == "reference-v1"
    assert result["reference_duration_s"] == 8.0


def test_qwen_17b_fleet_voice_is_prepared_before_the_adapter_and_auditable(
    tmp_path: Path, monkeypatch,
) -> None:
    """A raw fleet file must never be the Qwen adapter's reference input.

    This would fail if the saved-voice branch again injected ``reference_path``
    directly, bypassing the same bounded preparation used for private uploads.
    """
    source = tmp_path / "fleet-source.wav"
    source_bytes = b"fleet-owned-source-bytes"
    source.write_bytes(source_bytes)
    prepared = tmp_path / "prepared-reference.wav"
    prepared.write_bytes(b"bounded-normalized-wav")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    calls: list[dict] = []

    def fake_prepare(**kwargs):
        calls.append(kwargs)
        return {
            "path": str(prepared),
            "source_sha256": source_sha,
            "derived_sha256": "c" * 64,
            "preparation_revision": "reference-v1",
            "duration_seconds": 8.0,
            "transcript": "Fleet reference words.",
        }

    voice = SimpleNamespace(audio_sha256=source_sha)
    library = SimpleNamespace(
        get=lambda voice_id: voice if voice_id == "fleet-voice" else None,
        reference_path=lambda voice_id: source,
        transcript=lambda voice_id: "Fleet reference words.",
    )
    monkeypatch.setattr(reference_audio, "prepare", fake_prepare)
    params = {"repo": QWEN_17B_BASE, "voice_library_id": "fleet-voice"}
    kwargs: dict = {}

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_kwargs_qwen3(
        SimpleNamespace(repo=QWEN_17B_BASE),
        params,
        kwargs,
        SimpleNamespace(library=library),
    )
    result = generation.GenerationJob(
        job_id="prepared-fleet-reference",
        mode="txt2speech",
        params=params,
    ).serialize()

    assert calls == [{
        "audio_bytes": source_bytes,
        "filename": "fleet-source.wav",
        "model_id": QWEN_17B_BASE,
        "transcript": "Fleet reference words.",
    }]
    assert kwargs == {"ref_audio": str(prepared), "ref_text": "Fleet reference words."}
    assert result["voice_library_id"] == "fleet-voice"
    assert result["reference_audio_sha256"] == "c" * 64
    assert result["reference_source_sha256"] == source_sha
    assert result["reference_preparation_revision"] == "reference-v1"
    assert result["reference_duration_s"] == 8.0


def test_qwen_17b_fleet_voice_fails_closed_when_preparation_rejects(
    tmp_path: Path, monkeypatch,
) -> None:
    """The adapter must not fall back to the unbounded saved source on reject."""
    source = tmp_path / "fleet-source.wav"
    source.write_bytes(b"fleet-owned-source-bytes")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    library = SimpleNamespace(
        get=lambda _voice_id: SimpleNamespace(audio_sha256=source_sha),
        reference_path=lambda _voice_id: source,
        transcript=lambda _voice_id: "Fleet reference words.",
    )

    def reject(**_kwargs):
        raise reference_audio.ReferenceAudioError(
            "REFERENCE_AUDIO_DURATION_UNSUPPORTED", "The bounded contract rejected it."
        )

    monkeypatch.setattr(reference_audio, "prepare", reject)
    manager = object.__new__(generation.GenerationManager)

    with pytest.raises(ValueError, match="bounded contract rejected"):
        manager._mlx_kwargs_qwen3(
            SimpleNamespace(repo=QWEN_17B_BASE),
            {"repo": QWEN_17B_BASE, "voice_library_id": "fleet-voice"},
            {},
            SimpleNamespace(library=library),
        )


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
