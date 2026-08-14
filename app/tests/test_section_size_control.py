from __future__ import annotations

import pytest

from backend import catalog, long_form_policy


QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
QWEN_06B_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"


def test_catalog_publishes_only_the_audited_qwen_17b_control() -> None:
    payload = catalog.serialize_model(catalog.get_model(QWEN_17B_BASE))
    assert payload["long_form_delivery"]["section_size_control"] == {
        "minimum": 230,
        "maximum": 400,
        "step": 1,
        "default_custom": 280,
        "runtime_default": 400,
        "source": "qwen3-17b-production-audit",
    }
    other = catalog.serialize_model(catalog.get_model(QWEN_06B_BASE))
    assert other["long_form_delivery"]["section_size_control"] is None


@pytest.mark.parametrize("requested", [None, 230, 280, 400])
def test_resolve_section_budget_accepts_only_auto_and_audited_values(
    requested: int | None,
) -> None:
    result = catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, requested)
    assert result["section_max_characters"] == (400 if requested is None else requested)
    assert result["source"] == ("audit" if requested is None else "caller_override")


@pytest.mark.parametrize(
    ("requested", "code"),
    [
        (229, "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"),
        (401, "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"),
        (True, "SECTION_MAX_CHARACTERS_INVALID"),
        (280.0, "SECTION_MAX_CHARACTERS_INVALID"),
        ("280", "SECTION_MAX_CHARACTERS_INVALID"),
        (float("inf"), "SECTION_MAX_CHARACTERS_INVALID"),
    ],
)
def test_resolve_section_budget_rejects_invalid_or_out_of_range_values(
    requested: object, code: str
) -> None:
    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, requested)
    assert error.value.code == code


def test_resolve_section_budget_rejects_override_for_model_without_capability() -> None:
    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget("qwen3-tts", QWEN_06B_BASE, 280)
    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"


def test_catalog_fails_closed_when_the_audit_and_capability_disagree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_policy_for = long_form_policy.policy_for

    def mismatched_policy_for(
        family: str,
        repo: str,
        *,
        audited_section_max_characters: object = None,
    ) -> dict | None:
        policy = original_policy_for(
            family,
            repo,
            audited_section_max_characters=audited_section_max_characters,
        )
        if repo == QWEN_17B_BASE and policy is not None:
            return {**policy, "section_max_characters": 399}
        return policy

    monkeypatch.setattr(catalog.long_form_policy, "policy_for", mismatched_policy_for)

    assert catalog.section_size_control_for(QWEN_17B_BASE) is None
    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, 280)
    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
