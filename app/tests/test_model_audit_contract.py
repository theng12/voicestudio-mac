from __future__ import annotations

import json
from pathlib import Path

from backend import generation, main, model_audits, transcription


GROUP_A = {
    "mlx-community/Kokoro-82M-bf16": "voice.tts",
    "mlx-community/whisper-large-v3-turbo": "audio.transcription",
}

QWEN_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
REJECTED_GROUP_B = {
    "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit": (
        "049ef77fe8816b536193c0c25f9a214d17921282"
    ),
    "mlx-community/chatterbox-4bit": (
        "f1d7b9696e1b6242e64eb8c4a823b6d1a50425a8"
    ),
}


def test_group_a_records_are_hash_bound_candidates_not_final_approvals() -> None:
    for model_id, operation in GROUP_A.items():
        record = model_audits.audit_record(model_id)
        assert record is not None
        candidate = record["genstudio_candidate"]
        assert candidate["schema"] == "studio.model-audit"
        assert candidate["schema_version"] == 1
        assert candidate["audit_status"] == "passed"
        assert candidate["candidate_for_genstudio"] is True
        assert candidate["approved_operations"] == [operation]
        assert candidate["capacity"] == {"max_concurrency": 1}
        assert candidate["contract_hash"] == model_audits.contract_hash(
            record["contract"]
        )
        assert candidate["runtime_revision"] == record["subject"][
            "checkpoint_revision"
        ]
        assert "approved_for_genstudio" not in json.dumps(record)


def test_kokoro_audit_inventory_exactly_matches_the_runtime_roster() -> None:
    record = model_audits.audit_record("mlx-community/Kokoro-82M-bf16")
    assert record is not None
    groups = record["evidence"]["stock_voice_inventory"]
    audited = {
        voice_id
        for group in groups.values()
        for voice_id in group["voice_ids"]
    }
    runtime = {voice["id"] for voice in generation.KOKORO_VOICES}
    assert audited == runtime
    assert len(audited) == 54
    assert set(groups) == set(generation.LANG_NAMES)
    assert record["contract"]["license"]["spdx"] == "Apache-2.0"
    limits = record["contract"]["input_limits"]
    assert limits["text_max_characters"] == 40_000
    assert limits["long_form_strategy"] == "adapter_managed_long_form"
    assert limits["supports_chunk_progress"] is True
    assert limits["supports_cancellation_between_chunks"] is True


def test_qwen_base_guardrail_contract_requires_requalification() -> None:
    record = model_audits.audit_record(QWEN_BASE)
    assert record is not None
    assert record["subject"]["display_name"] == "Qwen3-TTS 0.6B Base"
    assert record["subject"]["checkpoint_revision"] == (
        "50f45ef0047cde7e84c2ef04326acb8ada2436a7"
    )
    candidate = record["genstudio_candidate"]
    assert candidate["audit_status"] == "conditional"
    assert candidate["candidate_for_genstudio"] is False
    assert candidate["approved_operations"] == ["voice.tts"]
    assert candidate["contract_hash"] == model_audits.contract_hash(
        record["contract"]
    )
    assert candidate["hardware"]["minimum_unified_memory_gb"] == 16
    assert candidate["hardware"]["recommended_unified_memory_gb"] == 24
    assert candidate["adapter"]["version"] == "1.3"
    guardrails = candidate["controls"]["quality_guardrails"]
    assert guardrails["reference_word_alignment"] is True
    assert guardrails["automatic_section_token_ceiling"] is True
    assert guardrails["output_transcript_validation"] is True
    assert guardrails["max_local_quality_retries"] == 1
    assert guardrails["required_local_models"] == [
        "mlx-community/whisper-large-v3-turbo"
    ]
    limits = candidate["input_limits"]
    assert limits["text_max_characters"] == 40_000
    assert limits["private_section_max_characters"] == 288
    assert limits["private_join_pause_milliseconds"] == 180
    assert limits["long_form_strategy"] == "adapter_managed_long_form"
    reference = limits["reference_audio"]
    assert reference["minimum_duration_seconds"] == 3
    assert reference["target_duration_seconds"] == 8
    assert reference["recommended_duration_seconds"] == {"minimum": 8, "maximum": 12}
    assert reference["maximum_duration_seconds"] == 15
    assert reference["transcript"] == "required"
    assert record["evidence"]["supersedes_audit_id"] == (
        "voicestudio-20260803-qwen3-tts-0.6b-base-50f45ef0-pacing288"
    )
    assert record["evidence"]["promotion_gate"]["candidate_for_genstudio"] is False
    assert "approved_for_genstudio" not in json.dumps(record)


def test_rejected_group_b_qualifications_are_closed_and_never_candidates() -> None:
    for model_id, revision in REJECTED_GROUP_B.items():
        record = model_audits.audit_record(model_id)
        assert record is not None
        assert record["subject"]["checkpoint_revision"] == revision
        candidate = record["genstudio_candidate"]
        assert candidate["audit_status"] == "failed"
        assert candidate["candidate_for_genstudio"] is False
        assert candidate["runtime_revision"] == revision
        assert candidate["approved_operations"] == ["voice.tts"]
        assert candidate["contract_hash"] == model_audits.contract_hash(
            record["contract"]
        )
        assert record["evidence"]["human_quality_review"][
            "commercial_decision"
        ] == "rejected"
        assert "approved_for_genstudio" not in json.dumps(record)


def test_rejected_qwen_customvoice_records_exact_preset_roster() -> None:
    record = model_audits.audit_record(
        "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
    )
    assert record is not None
    assert record["contract"]["controls"]["preset_speaker"]["values"] == [
        "Ryan", "Aiden", "Serena", "Vivian", "Uncle_Fu", "Dylan",
        "Eric", "Ono_Anna", "Sohee",
    ]
    assert record["contract"]["input_limits"]["voice_clone_supported"] is False


def test_rejected_chatterbox_records_grounded_language_and_latency_failures() -> None:
    record = model_audits.audit_record("mlx-community/chatterbox-4bit")
    assert record is not None
    assert len(record["contract"]["controls"]["language"]["values"]) == 23
    evidence = record["evidence"]
    assert evidence["language_qualification"]["hebrew"] == (
        "failed_quality_on_8_16_and_24_gb"
    )
    assert evidence["long_form_endurance"]["tiers"]["16"][
        "real_time_factor"
    ] == 3.729


def test_kokoro_adapter_uses_audited_checkpoint_local_voicepacks(
    tmp_path: Path,
) -> None:
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    for voice_id in ("jf_alpha", "jm_kumo"):
        (voices_dir / f"{voice_id}.safetensors").write_bytes(b"voice")

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_snapshot_path = lambda _repo: tmp_path
    kwargs: dict = {}

    manager._mlx_kwargs_voice_picker(
        "kokoro-mlx",
        {"voice": "jf_alpha,jm_kumo", "language": "j"},
        kwargs,
    )

    assert kwargs["lang_code"] == "j"
    assert kwargs["voice"].split(",") == [
        str((voices_dir / "jf_alpha.safetensors").absolute()),
        str((voices_dir / "jm_kumo.safetensors").absolute()),
    ]


def test_kokoro_adapter_preserves_suffix_for_huggingface_voicepack_symlink(
    tmp_path: Path,
) -> None:
    blobs = tmp_path / "blobs"
    voices = tmp_path / "snapshot" / "voices"
    blobs.mkdir()
    voices.mkdir(parents=True)
    blob = blobs / ("a" * 64)
    blob.write_bytes(b"voice")
    voicepack = voices / "bm_lewis.safetensors"
    voicepack.symlink_to(blob)

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_snapshot_path = lambda _repo: tmp_path / "snapshot"
    kwargs: dict = {}

    manager._mlx_kwargs_voice_picker(
        "kokoro-mlx",
        {"voice": "bm_lewis", "language": "b"},
        kwargs,
    )

    assert kwargs["voice"] == str(voicepack.absolute())
    assert kwargs["voice"].endswith(".safetensors")


def test_catalog_exposes_candidate_evidence_without_exposure_authority(
    monkeypatch,
) -> None:
    target = "mlx-community/Kokoro-82M-bf16"
    revision = GROUP_A_RECORDS[target]["runtime_revision"]
    monkeypatch.setattr(
        main,
        "_cache_with_companions",
        lambda repo: {
            "state": "cached" if repo == target else "absent",
            "snapshot_revision": revision if repo == target else None,
        },
    )
    monkeypatch.setattr(
        main.gen_manager,
        "model_runtime_status",
        lambda _model: {
            "loaded": False,
            "runtime_ready": True,
            "cold_load_required_free_memory_gb": 1.0,
            "loaded_required_free_memory_gb": 1.0,
            "required_free_memory_gb": 1.0,
            "memory_eligible": True,
        },
    )
    monkeypatch.setattr(main.manager, "active_for_repo", lambda _repo: None)

    item = {
        row["repo"]: row for row in main.get_catalog()["models"]
    }[target]
    candidate = item["genstudio_candidate"]
    assert candidate["approved_operations"] == ["voice.tts"]
    assert candidate["capacity"] == {"max_concurrency": 1, "available_slots": 1}
    assert "streaming" not in item["capabilities"]
    assert item["min_unified_memory_gb"] == candidate["hardware"][
        "minimum_unified_memory_gb"
    ]
    assert candidate["hardware"]["minimum_unified_memory_gb"] == 8
    assert "8 GB" in item["recommended_hardware"]
    assert item["genstudio_candidate_runtime_match"] is True
    assert "approved_for_genstudio" not in item


def test_transcription_availability_exposes_exact_audited_revisions(
    monkeypatch,
) -> None:
    monkeypatch.setattr(transcription, "_have_mlx_audio_stt", lambda: True)
    monkeypatch.setattr(transcription, "_detect_device", lambda: "mps")
    monkeypatch.setattr(
        transcription.cache,
        "status_snapshot",
        lambda repo: {
            "state": "cached" if repo in GROUP_A_RECORDS else "absent",
            "snapshot_revision": GROUP_A_RECORDS.get(repo, {}).get(
                "runtime_revision"
            ),
        },
    )

    models = {row["repo"]: row for row in transcription.availability()["models"]}
    for repo in ("mlx-community/whisper-large-v3-turbo",):
        assert models[repo]["cached"] is True
        assert models[repo]["genstudio_candidate_runtime_match"] is True
        assert models[repo]["genstudio_candidate"]["approved_operations"] == [
            "audio.transcription"
        ]
        assert models[repo]["genstudio_candidate"]["capacity"] == {
            "max_concurrency": 1,
            "available_slots": 1,
        }
    assert "genstudio_candidate" not in models[
        "mlx-community/whisper-small-mlx"
    ]
    assert "mlx-community/whisper-tiny" not in models


def test_whisper_postroll_is_bounded_by_the_source_media() -> None:
    text, segments = transcription._normalize_segments(
        [
            {
                "start": 0.0,
                "end": 3.36,
                "text": "Voice Studio is ready.",
                "words": [
                    {"word": "Voice", "start": 0.0, "end": 0.4},
                    {"word": "ready.", "start": 2.9, "end": 3.36},
                ],
            },
            {"start": 3.36, "end": 29.1, "text": "."},
            {"start": 29.1, "end": 30.0, "text": "hallucination"},
        ],
        word_timestamps=True,
        audio_duration=3.278,
    )

    assert text == "Voice Studio is ready."
    assert len(segments) == 1
    assert segments[0]["end"] == 3.278
    assert segments[0]["words"][-1]["end"] == 3.278


GROUP_A_RECORDS = {
    model_id: model_audits.candidate_summary(model_id) or {}
    for model_id in GROUP_A
}
