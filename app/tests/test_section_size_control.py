from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import catalog, generation, long_form_policy, main
from backend.main import FLEET_TOKEN


QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
QWEN_06B_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"


@pytest.fixture
def queued_txt2speech_params(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    monkeypatch.setattr(main.gen_manager, "is_available", lambda: True)
    monkeypatch.setattr(main.cache, "cache_state", lambda _repo: "cached")
    monkeypatch.setattr(
        main.gen_manager,
        "start_txt2speech",
        lambda params: captured.append(params) or SimpleNamespace(serialize=lambda: {}),
    )
    return captured


def _client() -> TestClient:
    return TestClient(main.app, headers={"X-Studio-Token": FLEET_TOKEN})


@pytest.mark.parametrize(
    ("requested", "include_control"),
    [(230, True), (280, True), (400, True), (None, True), (None, False)],
)
def test_txt2speech_endpoint_canonicalizes_section_budget_before_queueing(
    queued_txt2speech_params: list[dict], requested: int | None, include_control: bool,
) -> None:
    payload = {"repo": QWEN_17B_BASE, "text": "A bounded request."}
    if include_control:
        payload["section_max_characters"] = requested

    response = _client().post("/api/generate/txt2speech", json=payload)

    assert response.status_code == 200
    assert len(queued_txt2speech_params) == 1
    assert queued_txt2speech_params[0]["_resolved_section_max_characters"] == (
        requested or 400
    )
    assert "section_max_characters" not in queued_txt2speech_params[0]


@pytest.mark.parametrize(
    ("repo", "requested", "code"),
    [
        (QWEN_06B_BASE, 280, "SECTION_MAX_CHARACTERS_UNSUPPORTED"),
        (QWEN_17B_BASE, 229, "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"),
        (QWEN_17B_BASE, 401, "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"),
    ],
)
def test_txt2speech_endpoint_rejects_unresolved_section_budget(
    queued_txt2speech_params: list[dict], repo: str, requested: int, code: str,
) -> None:
    response = _client().post("/api/generate/txt2speech", json={
        "repo": repo,
        "text": "A rejected request.",
        "section_max_characters": requested,
    })

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert queued_txt2speech_params == []


@pytest.mark.parametrize(
    ("repo", "requested", "code"),
    [
        (QWEN_06B_BASE, 280, "SECTION_MAX_CHARACTERS_UNSUPPORTED"),
        (QWEN_17B_BASE, 229, "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"),
        (QWEN_17B_BASE, 401, "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"),
    ],
)
def test_reference_endpoint_rejects_section_budget_before_preparing_audio(
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
    repo: str,
    requested: int,
    code: str,
) -> None:
    prepared = False

    def prepare(**_kwargs):
        nonlocal prepared
        prepared = True
        return {
            "path": "/private/reference.wav",
            "derived_sha256": "a" * 64,
            "source_sha256": "b" * 64,
            "preparation_revision": "test-v1",
            "duration_seconds": 3.0,
            "transcript": "Prepared reference.",
        }

    monkeypatch.setattr(main.reference_audio, "prepare", prepare)
    response = _client().post(
        "/api/generate/txt2speech/reference",
        data={"request_json": json.dumps({
            "repo": repo,
            "text": "A rejected reference request.",
            "section_max_characters": requested,
        })},
        files={"audio": ("reference.wav", b"RIFF", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert prepared is False
    assert queued_txt2speech_params == []


def test_reference_endpoint_canonicalizes_section_budget_before_queueing(
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
) -> None:
    monkeypatch.setattr(main.reference_audio, "prepare", lambda **_kwargs: {
        "path": "/private/reference.wav",
        "derived_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "preparation_revision": "test-v1",
        "duration_seconds": 3.0,
        "transcript": "Prepared reference.",
    })
    response = _client().post(
        "/api/generate/txt2speech/reference",
        data={"request_json": json.dumps({
            "repo": QWEN_17B_BASE,
            "text": "A bounded reference request.",
            "section_max_characters": 280,
        })},
        files={"audio": ("reference.wav", b"RIFF", "audio/wav")},
    )

    assert response.status_code == 200
    assert queued_txt2speech_params[0]["_resolved_section_max_characters"] == 280
    assert "section_max_characters" not in queued_txt2speech_params[0]


class _InertThread:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass


def _inert_generation_manager() -> generation.GenerationManager:
    manager = object.__new__(generation.GenerationManager)
    manager._lock = threading.RLock()
    manager._jobs = {}
    return manager


def test_internal_queueing_canonicalizes_a_qwen_section_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)

    job = manager.start_txt2speech({
        "repo": QWEN_17B_BASE,
        "text": "An internal bounded request.",
        "section_max_characters": 280,
    })

    assert job.params["_resolved_section_max_characters"] == 280
    assert "section_max_characters" not in job.params


def test_internal_queueing_rejects_an_out_of_range_qwen_section_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)

    with pytest.raises(catalog.SectionSizeControlError) as error:
        manager.start_txt2speech({
            "repo": QWEN_17B_BASE,
            "text": "An invalid internal request.",
            "section_max_characters": 401,
        })

    assert error.value.code == "SECTION_MAX_CHARACTERS_OUT_OF_RANGE"
    assert manager._jobs == {}


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


def test_resolve_section_budget_rejects_capability_from_another_model() -> None:
    capability = catalog.section_size_control_for(QWEN_17B_BASE)

    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget(
            "qwen3-tts", QWEN_06B_BASE, 280, capability=capability
        )

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


def test_resolve_section_budget_rejects_a_stale_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = catalog.section_size_control_for(QWEN_17B_BASE)
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

    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget(
            "qwen3-tts", QWEN_17B_BASE, 280, capability=capability
        )

    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
