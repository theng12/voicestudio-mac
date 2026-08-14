from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import catalog, generation, long_form_policy, main, model_audits, qwen_quality
from backend.main import FLEET_TOKEN


QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
QWEN_06B_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
F5_TTS = "SWivid/F5-TTS"
BARK = "mlx-community/bark"
ROOT = Path(__file__).resolve().parents[2]
QWEN_17B_V2 = (
    ROOT
    / "model-audits"
    / "2026-08-15-qwen3-17b-production-v2"
    / "mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json"
)


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
        280 if requested is None else requested
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


def test_internal_queueing_keeps_qwen_06b_private_fallback_for_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)
    text = " ".join(
        f"Fallback validation sentence {index} remains independently bounded."
        for index in range(1, 30)
    )

    job = manager.start_txt2speech({"repo": QWEN_06B_BASE, "text": text})

    assert job.params["_resolved_section_max_characters"] == 288
    assert "section_max_characters" not in job.params
    chunks = generation._internal_mlx_text_chunks(
        "qwen3-tts", QWEN_06B_BASE, text, max_chars_override=288,
    )
    expected = round(
        sum(qwen_quality.automatic_duration_limit(chunk, 1.0) for chunk in chunks)
        + (len(chunks) - 1) * 0.18,
        3,
    )
    assert generation.GenerationManager._qwen_job_duration_limit(job) == expected


def test_omitted_control_for_a_non_qwen_model_keeps_the_normal_queue_path(
    queued_txt2speech_params: list[dict],
) -> None:
    response = _client().post("/api/generate/txt2speech", json={
        "repo": BARK,
        "text": "A normal non-Qwen request.",
    })

    assert response.status_code == 200
    assert len(queued_txt2speech_params) == 1
    assert queued_txt2speech_params[0]["section_max_characters"] is None
    assert "_resolved_section_max_characters" not in queued_txt2speech_params[0]


def test_omitted_control_for_a_non_qwen_model_prepares_reference_audio(
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
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
            "repo": F5_TTS,
            "text": "A normal reference request.",
        })},
        files={"audio": ("reference.wav", b"RIFF", "audio/wav")},
    )

    assert response.status_code == 200
    assert prepared is True
    assert queued_txt2speech_params[0]["section_max_characters"] is None
    assert "_resolved_section_max_characters" not in queued_txt2speech_params[0]


@pytest.mark.parametrize("repo", [BARK, F5_TTS])
def test_non_qwen_section_override_remains_fail_closed(
    queued_txt2speech_params: list[dict], repo: str,
) -> None:
    response = _client().post("/api/generate/txt2speech", json={
        "repo": repo,
        "text": "An unsupported override.",
        "section_max_characters": 280,
    })

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
    assert queued_txt2speech_params == []


def test_internal_queueing_without_a_non_qwen_override_stays_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)

    job = manager.start_txt2speech({
        "repo": F5_TTS,
        "text": "An ordinary internal F5 request.",
    })

    assert "section_max_characters" not in job.params
    assert "_resolved_section_max_characters" not in job.params


def test_auto_budget_fails_closed_when_audit_capability_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
) -> None:
    original_policy_for = long_form_policy.policy_for

    def mismatched_policy_for(
        family: str,
        repo: str,
        *,
        audited_section_max_characters: object = None,
        audited_default_section_max_characters: object = None,
    ) -> dict | None:
        policy = original_policy_for(
            family,
            repo,
            audited_section_max_characters=audited_section_max_characters,
            audited_default_section_max_characters=audited_default_section_max_characters,
        )
        if repo == QWEN_17B_BASE and policy is not None:
            return {**policy, "section_max_characters": 399}
        return policy

    monkeypatch.setattr(catalog.long_form_policy, "policy_for", mismatched_policy_for)
    response = _client().post("/api/generate/txt2speech", json={
        "repo": QWEN_17B_BASE,
        "text": "A mismatch-safe Auto request.",
    })
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
    assert queued_txt2speech_params == []
    with pytest.raises(catalog.SectionSizeControlError) as error:
        manager.start_txt2speech({
            "repo": QWEN_17B_BASE,
            "text": "A mismatch-safe internal request.",
            "_resolved_section_max_characters": 399,
        })
    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"


def test_missing_v2_rejects_auto_across_endpoint_and_manager(
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
) -> None:
    monkeypatch.setattr(
        catalog.model_audits, "qwen_17b_production_v2_limits", lambda _repo: {}
    )
    response = _client().post("/api/generate/txt2speech", json={
        "repo": QWEN_17B_BASE,
        "text": "A missing-audit Auto request.",
    })
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
    assert queued_txt2speech_params == []
    with pytest.raises(catalog.SectionSizeControlError) as error:
        manager.start_txt2speech({
            "repo": QWEN_17B_BASE,
            "text": "A missing-audit internal request.",
            "_resolved_section_max_characters": 280,
        })
    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"


@pytest.mark.parametrize(
    ("audit_status", "candidate_for_genstudio"),
    [
        ("passed", False),
        ("conditional", True),
        ("failed", True),
        ("revoked", True),
    ],
)
def test_non_production_v2_evidence_cannot_publish_or_queue_section_budgets(
    audit_status: str,
    candidate_for_genstudio: bool,
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
    tmp_path: Path,
) -> None:
    """Only passed, GenStudio-candidate v2 evidence authorizes this control."""
    record = json.loads(QWEN_17B_V2.read_text(encoding="utf-8"))
    record["genstudio_candidate"]["audit_status"] = audit_status
    record["genstudio_candidate"]["candidate_for_genstudio"] = candidate_for_genstudio
    root = tmp_path / "2026-08-15-qwen3-17b-production-v2"
    root.mkdir()
    (root / QWEN_17B_V2.name).write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(model_audits, "AUDIT_ROOT", tmp_path)

    assert model_audits.qwen_17b_production_v2_limits(QWEN_17B_BASE) == {}
    assert catalog.section_size_control_for(QWEN_17B_BASE) is None

    auto = _client().post("/api/generate/txt2speech", json={
        "repo": QWEN_17B_BASE,
        "text": "An unauthorized Auto request.",
    })
    custom = _client().post("/api/generate/txt2speech", json={
        "repo": QWEN_17B_BASE,
        "text": "An unauthorized Custom request.",
        "section_max_characters": 280,
    })

    assert auto.status_code == 422
    assert auto.json()["detail"]["code"] == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
    assert custom.status_code == 422
    assert custom.json()["detail"]["code"] == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
    assert queued_txt2speech_params == []


def test_manager_rejects_a_forged_private_auto_budget_when_capability_disagrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_policy_for = long_form_policy.policy_for

    def mismatched_policy_for(
        family: str,
        repo: str,
        *,
        audited_section_max_characters: object = None,
        audited_default_section_max_characters: object = None,
    ) -> dict | None:
        policy = original_policy_for(
            family,
            repo,
            audited_section_max_characters=audited_section_max_characters,
            audited_default_section_max_characters=audited_default_section_max_characters,
        )
        if repo == QWEN_17B_BASE and policy is not None:
            return {**policy, "section_max_characters": 399}
        return policy

    monkeypatch.setattr(catalog.long_form_policy, "policy_for", mismatched_policy_for)
    manager = _inert_generation_manager()
    monkeypatch.setattr(generation.threading, "Thread", _InertThread)

    with pytest.raises(catalog.SectionSizeControlError) as error:
        manager.start_txt2speech({
            "repo": QWEN_17B_BASE,
            "text": "A forged private request.",
            "_resolved_section_max_characters": 400,
        })

    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"


def test_custom_budget_stays_capability_gated_when_audit_and_capability_disagree(
    monkeypatch: pytest.MonkeyPatch,
    queued_txt2speech_params: list[dict],
) -> None:
    original_policy_for = long_form_policy.policy_for

    def mismatched_policy_for(
        family: str,
        repo: str,
        *,
        audited_section_max_characters: object = None,
        audited_default_section_max_characters: object = None,
    ) -> dict | None:
        policy = original_policy_for(
            family,
            repo,
            audited_section_max_characters=audited_section_max_characters,
            audited_default_section_max_characters=audited_default_section_max_characters,
        )
        if repo == QWEN_17B_BASE and policy is not None:
            return {**policy, "section_max_characters": 399}
        return policy

    monkeypatch.setattr(catalog.long_form_policy, "policy_for", mismatched_policy_for)
    response = _client().post("/api/generate/txt2speech", json={
        "repo": QWEN_17B_BASE,
        "text": "A capability-gated Custom request.",
        "section_max_characters": 280,
    })

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
    assert queued_txt2speech_params == []


def test_catalog_publishes_only_the_audited_qwen_17b_control() -> None:
    payload = catalog.serialize_model(catalog.get_model(QWEN_17B_BASE))
    assert payload["long_form_delivery"]["section_size_control"] == {
        "minimum": 230,
        "maximum": 400,
        "step": 1,
        "default_custom": 280,
        "runtime_default": 280,
        "source": "qwen3-17b-production-v2-audit",
    }
    other = catalog.serialize_model(catalog.get_model(QWEN_06B_BASE))
    assert other["long_form_delivery"]["section_size_control"] is None


def test_frontend_custom_400_is_valid_and_auto_omits_the_override() -> None:
    script = ROOT / "app" / "frontend" / "app.js"
    probe = r"""
const fs = require('fs');
const vm = require('vm');
const submitted = [];
global.fetch = async (_url, options) => {
  submitted.push(JSON.parse(options.body));
  return { ok: true, json: async () => ({ job: {} }) };
};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));

(async () => {
  const app = studio();
  const repo = 'mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit';
  app.models = [{
    repo,
    family: 'qwen3-tts',
    cache: { state: 'cached' },
    long_form_delivery: {
      section_size_control: {
        minimum: 230,
        maximum: 400,
        step: 1,
        default_custom: 280,
        runtime_default: 280,
      },
    },
  }];
  app.gen.available = true;
  app.gen.repo = repo;
  app.gen.text = 'A bounded Qwen request.';
  app.gen.voice_library_id = 'saved-voice';
  app._requestNotificationPermission = () => {};
  app.pushToast = () => {};

  app.gen.section_size_mode = 'auto';
  app.gen.section_max_characters = 400;
  await app.submitGenerate();
  await new Promise(resolve => setTimeout(resolve, 310));

  app.gen.section_size_mode = 'custom';
  app.gen.section_max_characters = 400;
  const custom400IsValid = app.sectionSizeIsValid;
  await app.submitGenerate();

  process.stdout.write(JSON.stringify({ submitted, custom400IsValid }));
})();
"""
    result = subprocess.run(
        ["node", "-e", probe, str(script)],
        capture_output=True,
        text=True,
        check=True,
    )
    observed = json.loads(result.stdout)

    assert observed["custom400IsValid"] is True
    assert "section_max_characters" not in observed["submitted"][0]
    assert observed["submitted"][1]["section_max_characters"] == 400


def test_readme_documents_the_audited_section_size_control_contract() -> None:
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())

    assert "### Qwen 1.7B Base section size" in readme
    assert "`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`" in readme
    assert "Auto keeps the audited 280-character section size" in readme
    assert "Custom accepts whole numbers from 230 through 400" in readme
    assert "safety maximum remains 400" in readme
    assert "retry uses 230" in readme
    assert "300/600/180 ms" in readme
    assert "omit `section_max_characters` for Auto" in readme
    assert "send an integer `section_max_characters` for Custom" in readme


@pytest.mark.parametrize(
    ("requested", "expected", "source"),
    [
        (None, 280, "audit"),
        (230, 230, "caller_override"),
        (280, 280, "caller_override"),
        (400, 400, "caller_override"),
    ],
)
def test_qwen_v2_resolves_auto_and_custom(
    requested: int | None, expected: int, source: str,
) -> None:
    result = catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, requested)
    assert result["section_max_characters"] == expected
    assert result["source"] == source


def test_missing_v2_never_falls_back_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        catalog.model_audits, "qwen_17b_production_v2_limits", lambda _repo: {}
    )

    assert catalog.section_size_control_for(QWEN_17B_BASE) is None
    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, 280)
    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"


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
        audited_default_section_max_characters: object = None,
    ) -> dict | None:
        policy = original_policy_for(
            family,
            repo,
            audited_section_max_characters=audited_section_max_characters,
            audited_default_section_max_characters=audited_default_section_max_characters,
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
        audited_default_section_max_characters: object = None,
    ) -> dict | None:
        policy = original_policy_for(
            family,
            repo,
            audited_section_max_characters=audited_section_max_characters,
            audited_default_section_max_characters=audited_default_section_max_characters,
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
