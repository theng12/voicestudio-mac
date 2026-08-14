"""The contract-vs-runtime validator: does the record match the adapter?

Every other audit check in this repository is self-consistent by construction
(the contract hash is computed over the contract; the candidate block is copied
from the contract). A record copied wholesale from another model passes all of
them. These tests exercise the one check that does not: comparing the record's
claims against the code that will actually run.

The mutation tests below reproduce the four fields that were wrong in the
superseded OmniVoice record shipped in v1.32.8 — three of them Qwen3-TTS Base's
values — and assert the validator catches each one.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import audit_contract_runtime as acr  # noqa: E402


OMNIVOICE_RECORD = (
    ROOT
    / "model-audits"
    / "2026-08-08-omnivoice"
    / "mlx-community--OmniVoice-bfloat16.audit.json"
)
QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"


@pytest.fixture(scope="module")
def sources() -> dict:
    return acr.load_sources(ROOT)


@pytest.fixture(scope="module")
def omnivoice_record() -> dict:
    return json.loads(OMNIVOICE_RECORD.read_text(encoding="utf-8"))


def _validate(record: dict, sources: dict) -> dict:
    return acr.validate_record(record, **sources)


def _status(result: dict, check_id: str) -> str:
    for check in result["checks"]:
        if check["id"] == check_id:
            return check["status"]
    raise AssertionError(f"no check {check_id!r} in {[c['id'] for c in result['checks']]}")


# ─── the shipped state ─────────────────────────────────────────────────────

def test_every_installed_audit_record_agrees_with_the_adapter_it_describes() -> None:
    """CI gate: no shipped record may contradict the code it claims to describe."""
    report = acr.build_report(ROOT)
    assert report["records"], "no audit records were validated"
    assert report["mismatch_count"] == 0, json.dumps(
        report["mismatches"], indent=2, ensure_ascii=False
    )


def test_omnivoice_record_passes_every_check_the_validator_can_make(
    omnivoice_record, sources
) -> None:
    result = _validate(omnivoice_record, sources)
    assert result["resolved"] == {
        "family": "omnivoice",
        "engine_mode": "omnivoice",
        "adapter_function": "_mlx_kwargs_omnivoice",
        "long_form_policy_source": "runtime_default",
    }
    assert result["mismatches"] == []
    assert result["not_checkable"] == []
    assert result["resolution_notes"] == []


# ─── the validator must publish its own blind spots ────────────────────────

def test_result_names_what_it_does_not_verify(omnivoice_record, sources) -> None:
    """A 'passed' that hides its blind spots is what caused this incident."""
    result = _validate(omnivoice_record, sources)
    covered_text = json.dumps(result["not_covered"])
    for field in (
        "audit_status",
        "hardware",
        "quality",
        "license",
        "permission_acknowledged",
        "text_max_characters",
    ):
        assert field in covered_text, f"non-coverage list never mentions {field}"
    # It is part of the returned result, not only a code comment or printout.
    assert result["not_covered"] is acr.NOT_COVERED
    assert acr.build_report(ROOT)["not_covered"] is acr.NOT_COVERED


def test_the_commercial_text_ceiling_is_bounded_but_never_called_a_gap(
    omnivoice_record, sources
) -> None:
    """25,000 is a chosen ceiling. The only claim made is that it is reachable."""
    result = _validate(omnivoice_record, sources)
    check = next(c for c in result["checks"] if c["id"] == "text_max_within_api_cap")
    assert check["status"] == acr.OK
    assert check["claimed"] == 25_000
    assert check["expected"] == "<= 40000"
    # Sitting below the API cap is never reported as a deficiency.
    assert "commercial decision" in check["detail"]


def test_a_ceiling_above_the_api_cap_is_unfulfillable_and_is_reported(
    omnivoice_record, sources
) -> None:
    mutated = copy.deepcopy(omnivoice_record)
    mutated["contract"]["input_limits"]["text_max_characters"] = 60_000
    assert _status(_validate(mutated, sources), "text_max_within_api_cap") == acr.MISMATCH


# ─── the four fields that were wrong in the superseded record ──────────────

KNOWN_BAD = {
    "reference_window": (
        "an 8/12/15 s reference window (Qwen3-TTS Base's), "
        "against ref_audio_max_duration_s = 10.0"
    ),
    "join_pause": "private_join_pause_milliseconds 180 (Qwen's), against 300",
    "language_control": (
        "a 10-value controls.language enum, against an adapter that passes no "
        "language kwarg and a catalog that enumerates none"
    ),
    "voice_clone_required": (
        "controls.voice_clone.required true, against a guard that raises only "
        "when the reference AND the design prompt are both absent"
    ),
    "section_budget": (
        "private_section_max_characters 360, which catalog.py would feed "
        "straight into the runtime and silently change generation"
    ),
}


def _mutate(record: dict, check_id: str) -> dict:
    mutated = copy.deepcopy(record)
    contract = mutated["contract"]
    if check_id == "reference_window":
        contract["controls"]["voice_clone"]["minimum_duration_seconds"] = 8
        contract["controls"]["voice_clone"]["maximum_duration_seconds"] = 15
        contract["controls"]["voice_clone"]["recommended_duration_seconds"] = {
            "minimum": 8,
            "maximum": 15,
        }
        contract["input_limits"]["reference_audio"]["maximum_duration_seconds"] = 15
    elif check_id == "join_pause":
        contract["input_limits"]["private_join_pause_milliseconds"] = 180
    elif check_id == "language_control":
        contract["controls"]["language"] = {
            "type": "enum",
            "values": ["en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
        }
    elif check_id == "voice_clone_required":
        contract["controls"]["voice_clone"]["required"] = True
    elif check_id == "section_budget":
        contract["input_limits"]["private_section_max_characters"] = 360
    else:  # pragma: no cover - guard against a typo in the parametrisation
        raise AssertionError(check_id)
    return mutated


@pytest.mark.parametrize("check_id", sorted(KNOWN_BAD))
def test_a_record_mutated_to_a_known_bad_value_fails(
    check_id, omnivoice_record, sources
) -> None:
    baseline = _validate(omnivoice_record, sources)
    assert _status(baseline, check_id) == acr.OK, "baseline must start clean"

    result = _validate(_mutate(omnivoice_record, check_id), sources)
    assert _status(result, check_id) == acr.MISMATCH, (
        f"validator accepted {KNOWN_BAD[check_id]}"
    )
    reported = {c["id"] for c in result["mismatches"]}
    assert check_id in reported


def test_the_section_budget_mismatch_is_the_highest_severity(
    omnivoice_record, sources
) -> None:
    """catalog.py feeds this value into the runtime, so a wrong one changes
    generation behaviour on every machine that installs the release."""
    result = _validate(_mutate(omnivoice_record, "section_budget"), sources)
    check = next(c for c in result["checks"] if c["id"] == "section_budget")
    assert check["severity"] == "critical"
    assert check["expected"] == 288
    assert check["claimed"] == 360


def test_the_expectation_is_the_family_default_not_the_audited_value(
    omnivoice_record, sources
) -> None:
    """Guards against the validator becoming another self-consistency check.

    ``policy_for`` accepts an audited override; if the validator passed the
    audited number in, the comparison would always succeed.
    """
    policy = sources["long_form_policy"]
    audited = policy.policy_for(
        "omnivoice",
        "mlx-community/OmniVoice-bfloat16",
        audited_section_max_characters=360,
    )
    assert audited["section_max_characters"] == 360
    assert audited["source"] == "model_audit"

    result = _validate(_mutate(omnivoice_record, "section_budget"), sources)
    check = next(c for c in result["checks"] if c["id"] == "section_budget")
    assert check["status"] == acr.MISMATCH


def test_qwen_17b_assembly_claims_are_verified_against_runtime(sources) -> None:
    """A candidate cannot claim Qwen's approved joins or lossless assembly.

    Each mutation below represents a contract that would look internally
    consistent after hashing, but would misdescribe the code running on a
    worker. Removing the runtime-assembly check would make every mutation pass.
    """
    record = {
        "subject": {"model_id": QWEN_17B_BASE},
        "contract": {
            "input_limits": {
                "private_join_pause_milliseconds": 300,
                "private_paragraph_join_pause_milliseconds": 600,
                "private_soft_join_pause_milliseconds": 180,
                "private_edge_destructive_trim": False,
                "private_speech_crossfade": False,
            },
        },
    }

    assert _status(_validate(record, sources), "long_form_assembly") == acr.OK

    for key, value in (
        ("private_join_pause_milliseconds", 180),
        ("private_paragraph_join_pause_milliseconds", 300),
        ("private_soft_join_pause_milliseconds", 0),
        ("private_edge_destructive_trim", True),
        ("private_speech_crossfade", True),
    ):
        mutated = copy.deepcopy(record)
        mutated["contract"]["input_limits"][key] = value
        assert _status(_validate(mutated, sources), "long_form_assembly") == acr.MISMATCH


# ─── graceful degradation ──────────────────────────────────────────────────

def test_an_unintrospectable_model_reports_not_checkable_never_passed(
    omnivoice_record, sources
) -> None:
    mutated = copy.deepcopy(omnivoice_record)
    mutated["subject"]["model_id"] = "example/not-in-this-catalog"
    result = _validate(mutated, sources)

    assert result["resolved"]["family"] is None
    assert result["mismatches"] == []
    adapter_checks = {"reference_window", "voice_clone_required", "language_control"}
    for check in result["checks"]:
        if check["id"] in adapter_checks:
            assert check["status"] == acr.NOT_CHECKABLE
    assert result["resolution_notes"], "silent non-coverage is the failure mode"
    assert "unverified, not passed" in " ".join(result["resolution_notes"])


# ─── the derivations themselves ────────────────────────────────────────────

def test_expectations_are_read_from_the_code_not_retyped(sources) -> None:
    """If these were constants in the validator it would be the same copy bug."""
    adapters = sources["adapters"]
    mode, fn = adapters.resolve("omnivoice")
    assert mode == "omnivoice"
    assert fn is not None and fn.name == "_mlx_kwargs_omnivoice"

    assignments = acr._gen_kwargs_assignments(fn)
    assert assignments["ref_audio_max_duration_s"] == [10.0]
    assert not set(assignments) & acr._LANGUAGE_KWARG_KEYS

    # The reference alone does not gate the call: voice design also satisfies it.
    assert acr._reference_requirement(fn) is False

    assert sources["api_text_cap"] == 40_000
    assert sources["catalog"].get("mlx-community/OmniVoice-bfloat16") == {
        "family": "omnivoice",
        "languages": [],
    }
