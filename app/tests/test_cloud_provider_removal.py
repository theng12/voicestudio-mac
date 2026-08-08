"""Voice Studio is local-only since 1.33.0.

Removing the cloud audio gateway is only safe if the ways *into* it fail
cleanly. A saved preset, a bookmarked Generate URL, or a Studio Hub batch item
built before the removal can still carry a synthetic `provider:<key>:<model>`
repo id. That request must get a truthful 400 rather than fall through to a
local-catalog lookup and surface as "Unknown repo". Provider endpoints,
persisted settings, voice metadata, and job history must stay absent too.
"""
import json

from fastapi.testclient import TestClient

from backend import main, settings
from backend.main import FLEET_TOKEN, app


CLOUD_REPO = "provider:elevenlabs:eleven_multilingual_v2"


def _client() -> TestClient:
    return TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})


def test_replayed_cloud_repo_is_rejected_with_a_clear_message() -> None:
    response = _client().post(
        "/api/generate/txt2speech",
        json={"repo": CLOUD_REPO, "text": "hello"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "no longer supported" in detail
    assert "local model" in detail


def test_replayed_cloud_repo_is_rejected_before_the_engine_check() -> None:
    """The answer must not depend on whether the generation stack is installed.

    A 503 "engine not installed" would send the caller off to reinstall
    something that was never the problem.
    """
    response = _client().post(
        "/api/generate/txt2speech",
        json={"repo": CLOUD_REPO, "text": "hello"},
    )
    assert response.status_code == 400


def test_provider_endpoints_are_gone() -> None:
    client = _client()
    for path in (
        "/api/providers",
        "/api/providers/elevenlabs/models/live",
        "/api/providers/elevenlabs/voices/live",
        "/api/providers/elevenlabs/accounts",
    ):
        assert client.get(path).status_code == 404, path
    # The write endpoint is gone entirely, not merely refusing — no route matches.
    assert client.put(
        "/api/voices/does-not-exist/providers", json={"providers": []}
    ).status_code == 404


def test_catalog_only_publishes_local_models() -> None:
    models = _client().get("/api/catalog").json()["models"]
    assert models
    assert {model["kind"] for model in models} == {"local"}
    assert not any(str(model["repo"]).startswith("provider:") for model in models)
    assert not any(model["cache"].get("state") == "cloud" for model in models)


def test_the_providers_module_is_gone() -> None:
    assert not hasattr(main, "providers")


def test_voice_schema_drops_legacy_provider_metadata(tmp_path) -> None:
    from backend.voices import Voice, VoiceLibrary

    payload = {
        "id": "deadbeef",
        "name": "Local voice",
        "language": "en",
        "gender": "m",
        "providers": [{"provider": "elevenlabs", "voice_id": "abc123"}],
    }
    (tmp_path / "metadata.json").write_text(json.dumps(payload))
    voice = VoiceLibrary._load_voice(tmp_path)
    assert voice is not None
    assert "providers" not in Voice.__dataclass_fields__
    assert "providers" not in voice.serialize()


def test_archived_cloud_history_is_discarded() -> None:
    from backend.generation import GenerationManager

    job = GenerationManager._from_disk(
        {
            "job_id": "2ca617ce8d68",
            "mode": "txt2speech",
            "state": "done",
            "provider": "elevenlabs",
            "provider_account_id": "2c970ccf500e",
            "provider_task_id": None,
            "provider_task_meta": {},
            "params": {"repo": CLOUD_REPO, "text": "archived"},
            "progress": 1.0,
        }
    )
    assert job is None


def test_history_load_rewrites_legacy_provider_rows(tmp_path, monkeypatch) -> None:
    from backend import generation

    path = tmp_path / ".history.json"
    path.write_text(json.dumps({"jobs": [
        {
            "job_id": "cloud",
            "state": "done",
            "provider": "elevenlabs",
            "params": {"repo": CLOUD_REPO, "text": "discard"},
        },
        {
            "job_id": "local",
            "state": "done",
            "provider": None,
            "provider_task_meta": {},
            "params": {"repo": "local/model", "text": "keep"},
        },
    ]}))
    monkeypatch.setattr(generation, "HISTORY_FILE", path)
    manager = generation.GenerationManager()

    assert [job.job_id for job in manager.list_jobs()] == ["local"]
    rows = json.loads(path.read_text())["jobs"]
    assert [row["job_id"] for row in rows] == ["local"]
    assert not any(key.startswith("provider") for key in rows[0])


def test_removed_cloud_settings_are_scrubbed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "hf_token": "hf_local_download_token",
        "providers": {"elevenlabs": {"api_key": "discard-me"}},
    }))
    monkeypatch.setattr(settings, "_PATH", path)
    monkeypatch.setattr(settings, "_cache", {})
    monkeypatch.setattr(settings, "_loaded", False)

    assert settings.get_hf_token() == "hf_local_download_token"
    assert json.loads(path.read_text()) == {"hf_token": "hf_local_download_token"}
