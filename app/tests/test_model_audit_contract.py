from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend import catalog, generation, main, model_audits, transcription


GROUP_A = {
    "mlx-community/Kokoro-82M-bf16": "voice.tts",
    "mlx-community/whisper-large-v3-turbo": "audio.transcription",
}

QWEN_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
QWEN_17B_BOOTSTRAP = (
    Path(__file__).resolve().parents[2]
    / "model-audits"
    / "2026-08-14-qwen3-17b"
    / "mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json"
)
QWEN_17B_V1 = (
    Path(__file__).resolve().parents[2]
    / "model-audits"
    / "2026-08-14-qwen3-17b-production"
    / "mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json"
)
QWEN_17B_V2 = (
    Path(__file__).resolve().parents[2]
    / "model-audits"
    / "2026-08-15-qwen3-17b-production-v2"
    / "mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json"
)
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


def test_qwen_17b_bootstrap_record_is_preserved_as_conditional_evidence() -> None:
    """Regression: promotion must not rewrite the installed 2.1.2 evidence."""
    record = json.loads(QWEN_17B_BOOTSTRAP.read_text(encoding="utf-8"))
    assert record["audit_id"] == (
        "voicestudio-20260814-qwen3-tts-1.7b-base-bootstrap-v1"
    )
    assert record["subject"]["checkpoint_revision"] == (
        "e7dd0585652209fa0d7783659aad4e8a324de11c"
    )
    candidate = record["genstudio_candidate"]
    assert candidate["audit_status"] == "conditional"
    assert candidate["candidate_for_genstudio"] is False
    assert candidate["contract_hash"] == model_audits.contract_hash(
        record["contract"]
    )
    assert candidate["runtime_revision"] == record["subject"]["checkpoint_revision"]
    assert candidate["adapter"] == {
        "id": "voicestudio.mlx-audio.qwen3-tts-base",
        "version": "1.4",
        "runtime": "mlx-audio 0.4.7+2c9461f5d8315fa8e7013ab2729495b2bb83d384",
    }
    assert candidate["controls"]["language"]["values"] == [
        "en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it",
    ]
    assert candidate["controls"]["voice_clone"] == {
        "type": "reference_audio_with_exact_transcript",
        "required": True,
        "x_vector_only_fallback": False,
    }
    guardrails = candidate["controls"]["quality_guardrails"]
    assert guardrails["validator_revision"] == "voicestudio.qwen-clone-quality.v1"
    assert guardrails["terminal_gate"] == {
        "revision": "voicestudio.qwen-clone-quality.v2",
        "scope": "long_form_2gram_multiset",
        "ordered_word_timestamp_window": 24,
        "maximum_hard_mismatches": 1,
        "fails_closed_without_aligned_suffix": True,
    }
    limits = candidate["input_limits"]
    assert limits["private_section_max_characters"] == 288
    assert {
        key: limits[key]
        for key in (
            "private_join_pause_milliseconds",
            "private_paragraph_join_pause_milliseconds",
            "private_soft_join_pause_milliseconds",
            "private_edge_destructive_trim",
            "private_speech_crossfade",
        )
    } == {
        "private_join_pause_milliseconds": 300,
        "private_paragraph_join_pause_milliseconds": 600,
        "private_soft_join_pause_milliseconds": 180,
        "private_edge_destructive_trim": False,
        "private_speech_crossfade": False,
    }
    assert limits["reference_audio"] == {
        "accepted_extensions": ["wav", "mp3", "flac", "m4a", "aac", "ogg", "opus", "webm"],
        "minimum_duration_seconds": 3,
        "target_duration_seconds": 8,
        "recommended_duration_seconds": {"minimum": 8, "maximum": 12},
        "maximum_duration_seconds": 15,
        "max_audio_bytes": 25000000,
        "sample_rate_hz": 24000,
        "channels": 1,
        "transcript": "required",
        "timestamped_transcript_segments": "required_when_model_specific_selection_is_needed",
        "selection": "speech-aware and word-boundary-aligned",
    }
    assert candidate["hardware"] == {
        "platform": "Apple Silicon",
        "minimum_unified_memory_gb": 16,
        "recommended_unified_memory_gb": 24,
        "ineligible_unified_memory_gb": [8],
    }
    assert record["contract"]["license"] == {
        "spdx": "Apache-2.0",
        "commercial_use": True,
    }
    evidence = record["evidence"]
    assert evidence["pre_release_memory_observation"]["status"] == (
        "preliminary_not_qualification"
    )
    assert evidence["pre_release_memory_observation"]["peak_mlx_memory_gb"] == 9.083
    assert evidence["implementation_verification"]["source_static_verification"] == {
        "status": "passed",
        "focused_tests": {"passed": 83},
        "full_tests": {"passed": 417, "skipped": 2},
        "strict_audits": [
            "audit_truth.py --strict",
            "audit_contract_runtime.py --strict",
        ],
        "release_checks": [
            "release_metadata_check.py",
            "compileall",
            "pip check",
            "install/update JavaScript syntax",
            "startup-service Bash syntax",
            "git diff --check",
        ],
    }
    assert evidence["implementation_verification"]["live_model_generation"] == (
        "not run on a new 2.1.2 canary"
    )
    assert evidence["promotion_gate"]["candidate_for_genstudio"] is False
    assert evidence["promotion_gate"]["status"] == "pending_canary_qualification"
    assert "approved_for_genstudio" not in json.dumps(record)


def test_qwen_v1_is_byte_stable_and_v2_is_the_runtime_source() -> None:
    assert hashlib.sha256(QWEN_17B_V1.read_bytes()).hexdigest() == (
        "b45e061379df0d8ee9e2d8dc0754108b280db5293f9c2fe7d5b4cab2a5b74e76"
    )
    record = model_audits.audit_record(QWEN_17B_BASE)
    assert record is not None
    assert record["audit_id"] == (
        "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2"
    )
    assert model_audits.qwen_17b_production_v2_limits(QWEN_17B_BASE) == {
        "private_section_max_characters": 400,
        "default_private_section_max_characters": 280,
    }


@pytest.mark.parametrize("default", [None, True, 229, 401, 400.0])
def test_invalid_v2_default_fails_closed(default, monkeypatch, tmp_path) -> None:
    record = json.loads(QWEN_17B_V2.read_text(encoding="utf-8"))
    record["contract"]["input_limits"]["default_private_section_max_characters"] = default
    record["genstudio_candidate"]["input_limits"] = record["contract"]["input_limits"]
    record["genstudio_candidate"]["contract_hash"] = model_audits.contract_hash(
        record["contract"]
    )
    root = tmp_path / "2026-08-15-qwen3-17b-production-v2"
    root.mkdir(parents=True)
    (root / QWEN_17B_V2.name).write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(model_audits, "AUDIT_ROOT", tmp_path)
    assert model_audits.qwen_17b_production_v2_limits(QWEN_17B_BASE) == {}


def test_qwen_17b_passed_production_audit_is_latest_and_drives_catalog_limits() -> None:
    """Regression: a passed promotion must surface only the measured 5k/400 contract."""
    record = model_audits.audit_record(QWEN_17B_BASE)
    assert record is not None
    assert record["audit_id"] == (
        "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2"
    )
    candidate = record["genstudio_candidate"]
    assert candidate["audit_status"] == "passed"
    assert candidate["candidate_for_genstudio"] is True
    assert candidate["contract_hash"] == model_audits.contract_hash(record["contract"])
    assert candidate["runtime_revision"] == "e7dd0585652209fa0d7783659aad4e8a324de11c"
    assert candidate["adapter"] == {
        "id": "voicestudio.mlx-audio.qwen3-tts-base",
        "version": "1.4",
        "runtime": "mlx-audio 0.4.7+2c9461f5d8315fa8e7013ab2729495b2bb83d384",
    }
    assert candidate["controls"]["language"]["values"] == [
        "en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it",
    ]
    assert "km" not in candidate["controls"]["language"]["values"]
    assert "th" not in candidate["controls"]["language"]["values"]
    guardrails = candidate["controls"]["quality_guardrails"]
    assert guardrails["validator_revision"] == "voicestudio.qwen-clone-quality.v1"
    assert guardrails["max_local_quality_retries"] == 1
    assert guardrails["retry_section_max_characters"] == 230
    assert guardrails["terminal_gate"]["revision"] == "voicestudio.qwen-clone-quality.v2"
    limits = candidate["input_limits"]
    assert limits["text_max_characters"] == 5_000
    assert limits["private_section_max_characters"] == 400
    assert limits["default_private_section_max_characters"] == 280
    assert limits["private_edge_destructive_trim"] is False
    assert limits["private_speech_crossfade"] is False
    assert limits["reference_audio"]["transcript"] == "required"
    assert limits["reference_audio"]["minimum_duration_seconds"] == 3
    assert limits["reference_audio"]["target_duration_seconds"] == 8
    assert limits["reference_audio"]["recommended_duration_seconds"] == {
        "minimum": 8,
        "maximum": 12,
    }
    assert candidate["hardware"] == {
        "platform": "Apple Silicon",
        "minimum_unified_memory_gb": 16,
        "recommended_unified_memory_gb": 24,
        "ineligible_unified_memory_gb": [8],
    }
    assert candidate["capacity"] == {"max_concurrency": 1}
    assert record["contract"]["license"] == {
        "spdx": "Apache-2.0",
        "commercial_use": True,
    }
    assert record["evidence"]["supersedes_audit_id"] == (
        "voicestudio-20260814-qwen3-tts-1.7b-base-production-v1"
    )
    evidence = record["evidence"]
    assert evidence["qualified_runtime"] == {
        "voice_studio_version": "2.1.2",
        "commit": "433fccebf08583aa8a61e88fc8804541ec61818b",
        "target": "terranash-0201",
        "hardware": "Apple M2, 17.18 GB unified memory",
        "checkpoint_revision": "e7dd0585652209fa0d7783659aad4e8a324de11c",
        "cache": {"complete_bytes": 3104164936, "incomplete_bytes": 0},
    }
    canary = evidence["five_thousand_character_canary"]
    assert canary["hub_batch_id"] == "dc6fc58779"
    assert canary["worker_job_id"] == "0df456ec1ed0"
    assert canary["seed"] == 23
    assert canary["section_max_characters"] == 400
    assert canary["quality_attempts"] == 1
    assert canary["quality_retry_count"] == 0
    assert canary["validator"] == {
        "revision": "voicestudio.qwen-clone-quality.v1",
        "branch": "edit_distance",
        "expected_tokens": 869,
        "observed_tokens": 869,
        "ter": 0.0127,
        "cer": 0.0114,
        "aligned_words": 867,
        "v2_terminal_gate": "not_applicable_below_2048_tokens",
    }
    assert canary["independent_remote_asr"] == {
        "coverage_percent": 100.0,
        "deletions": 0,
        "compound_tokenization_caveat": "snowcaps to snow caps accounts for apparent extra snow",
    }
    assert canary["terminal_sentinel"] == "exact final sentinel; no repeated tail"
    assert canary["runtime_seconds"] == 339.104
    assert canary["audio_seconds"] == 305.92
    assert canary["memory"] == {
        "peak_mlx_gb": 9.026,
        "minimum_free_gb": 1.905,
        "pressure": "normal",
        "swap_delta_gb": 0.0,
        "memory_failure_or_restart": False,
    }
    assert evidence["rejected_boundaries"]["ten_thousand_characters"] == {
        "hub_batch_id": "ec806a61a9",
        "worker_job_id": "d2456790cecb",
        "recommendation": "fail; never publish",
        "reason": "unexplained extra life plus missing at; snow may be compound-tokenization",
    }
    assert evidence["rejected_boundaries"]["twenty_five_thousand_characters"] == (
        "rejected/informative only; not promotion evidence"
    )
    assert evidence["rejected_boundaries"]["malformed_fixtures"] == (
        "rejected/informative only; not promotion evidence"
    )
    assert evidence["language_gates"]["khmer"] == "rejected and unsupported"
    assert evidence["language_gates"]["thai"] == "experimental and unsupported"
    assert evidence["human_quality_review"] == {
        "qwen_1_7b_quality_percent": 95,
        "commercial_decision": "production-acceptable",
    }
    assert evidence["paid_cloud_provider_calls"] == 0
    model = catalog.get_model(QWEN_17B_BASE)
    assert model is not None
    published = catalog.serialize_model(model)
    assert published["execution_contract"]["qualification_source"] == "audit"
    assert published["execution_contract"]["text_max_characters"] == 5_000
    assert published["execution_contract"]["private_section_max_characters"] == 400


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


def test_omnivoice_word_safe_edges_are_published_as_a_new_hash_bound_contract() -> None:
    record = model_audits.audit_record("mlx-community/OmniVoice-bfloat16")
    assert record is not None
    assert record["audit_id"] == (
        "voicestudio-20260813-omnivoice-6119f707-word-safe-fades-v4"
    )
    candidate = record["genstudio_candidate"]
    assert candidate["audit_id"] == record["audit_id"]
    assert candidate["adapter"]["version"] == "1.4"
    assert candidate["contract_hash"] == model_audits.contract_hash(
        record["contract"]
    )
    for contract in (record["contract"], candidate):
        limits = contract["input_limits"]
        assert limits["private_edge_destructive_trim"] is False
        assert limits["private_edge_fade_milliseconds"] == 10
        assert limits["private_join_pause_milliseconds"] == 300
        assert limits["private_paragraph_join_pause_milliseconds"] == 600
        assert limits["private_soft_join_pause_milliseconds"] == 180
    review = record["evidence"]["edge_cleanup_review"]
    assert review["observed_artifact_range_milliseconds"] == {"minimum": 17, "maximum": 270}
    assert review["speech_preservation"] == (
        "all section edges keep their original frame bounds"
    )
    regression = record["evidence"]["edge_cleanup_regression"]
    assert regression["missing_expected_word"] == "The"
    assert regression["unexpected_observed_word"] == "D"


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
