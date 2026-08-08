"""Voice Studio is local-only since 1.33.0.

Removing the cloud audio gateway is only safe if the ways *into* it fail
cleanly. A saved preset, a bookmarked Generate URL, or a Studio Hub batch item
built before the removal can still carry a synthetic `provider:<key>:<model>`
repo id. That request must get a truthful 400 rather than fall through to a
local-catalog lookup and surface as "Unknown repo", and the provider endpoints
must be gone rather than half-present.
"""
from fastapi.testclient import TestClient

from backend import main
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


def test_recorded_provider_voice_ids_are_still_read_and_published() -> None:
    """The owner's own clones carry Fish and ElevenLabs ids in their metadata.

    `app/voices/` is machine-local and gitignored, so this asserts the contract
    rather than the data: the field survives a round trip through the loader and
    reaches the API response. Those ElevenLabs ids may be the only local record
    of them, so removing the editing UI must not quietly drop them.
    """
    from backend.voices import Voice, library

    tags = [
        {"provider": "elevenlabs", "voice_id": "abc123"},
        {"provider": "fish", "voice_id": "def456"},
    ]
    voice = Voice(
        id="deadbeef", name="Archived", language="en", gender="m", providers=tags
    )
    assert voice.serialize()["providers"] == tags
    # Normalisation still accepts what is already on disk.
    assert library._normalize_provider_tags(tags) == tags
    # Every voice actually present on this machine still loads.
    for existing in library.list():
        assert isinstance(existing.providers, list)


def test_archived_cloud_history_still_loads() -> None:
    """The one real ElevenLabs job predates the removal and must survive it.

    `GenerationJob.provider*` stays in the schema precisely so `_from_disk`
    keeps accepting rows written by the gateway.
    """
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
    assert job is not None
    assert job.provider == "elevenlabs"
    assert job.serialize()["provider"] == "elevenlabs"
