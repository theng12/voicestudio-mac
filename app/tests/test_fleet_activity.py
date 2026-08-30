import threading

from fastapi.testclient import TestClient

from backend import main
from backend.generation import GenerationJob, GenerationManager


def _manager(*jobs: GenerationJob) -> GenerationManager:
    manager = GenerationManager.__new__(GenerationManager)
    manager._lock = threading.Lock()
    manager._jobs = {job.job_id: job for job in jobs}
    return manager


def test_activity_snapshot_classifies_hub_and_direct_jobs_without_private_data():
    manager = _manager(
        GenerationJob(
            "hub", "txt2speech", {
                "repo": "org/voice", "client_request_id": "studiohub:b:0",
                "text": "secret prompt", "_reference_audio_path": "/private/ref.wav",
            }, state="running", progress=0.5, started_at=20.0,
            chunk_index=2, chunk_total=4,
        ),
        GenerationJob(
            "direct", "txt2speech", {
                "repo": "org/voice", "text": "secret prompt",
                "ref_transcript": "secret transcript", "output_path": "/private/out.wav",
            }, state="done", progress=1.0, started_at=10.0, finished_at=14.0,
        ),
    )

    result = manager.activity_snapshot(observed_at=25.0)

    assert result["schema"] == "kh-studio.activity.v1"
    assert result["studio"] == "voice"
    assert result["active"]["source"] == "job"
    assert result["active"]["model"] == "org/voice"
    assert result["active"]["chunk_index"] == 2
    assert result["active"]["chunk_total"] == 4
    assert result["active"]["updated_at"] == 25.0
    assert result["latest"]["source"] == "direct"
    assert result["latest"]["runtime_s"] == 4.0
    assert "secret" not in repr(result)
    assert "/private" not in repr(result)


def test_activity_snapshot_supports_all_states_and_clamps_malformed_progress():
    manager = _manager(
        GenerationJob("queued", "txt2speech", {"repo": "queued/model"}, state="queued", progress="bad", created_at=1.0),
        GenerationJob("done", "txt2speech", {"repo": "done/model"}, state="done", progress=2.0, started_at=2.0, finished_at=3.0),
        GenerationJob("error", "txt2speech", {"repo": "error/model"}, state="error", progress=-1.0, finished_at=4.0, error="/private/secret", error_code="SAFE_CODE"),
        GenerationJob("cancelled", "txt2speech", {"repo": "cancelled/model"}, state="cancelled", progress=None, finished_at=5.0),
    )

    result = manager.activity_snapshot(observed_at=10.0)

    assert result["active"]["state"] == "queued"
    assert result["active"]["progress"] == 0.0
    assert result["latest"]["id"] == "cancelled"
    assert result["latest"]["progress"] == 0.0
    assert result["latest"]["runtime_s"] is None
    assert result["latest"]["error"] is None
    assert "SAFE_CODE" not in repr(result)
    assert "/private" not in repr(result)


def test_activity_snapshot_prefers_running_job_over_newer_queued_job():
    manager = _manager(
        GenerationJob(
            "running", "txt2speech", {"repo": "running/model"},
            state="running", progress=0.6, started_at=11.0, created_at=10.0,
        ),
        GenerationJob(
            "queued", "txt2speech", {"repo": "queued/model"},
            state="queued", progress=0.0, created_at=20.0,
        ),
    )

    result = manager.activity_snapshot(observed_at=25.0)

    assert result["active"]["id"] == "running"


def test_activity_route_is_authenticated_and_returns_sanitized_snapshot(monkeypatch):
    manager = _manager(
        GenerationJob(
            "run", "txt2speech", {
                "repo": "org/model", "text": "private prompt",
                "_reference_audio_path": "/private/reference.wav",
            }, state="running", progress=2.0, started_at=20.0,
        ),
    )
    monkeypatch.setattr(main, "gen_manager", manager)

    public = TestClient(main.app)
    assert public.get("/api/fleet/activity").status_code == 401

    client = TestClient(main.app, headers={"X-Studio-Token": main.FLEET_TOKEN})
    response = client.get("/api/fleet/activity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "kh-studio.activity.v1"
    assert payload["studio"] == "voice"
    assert payload["active"]["progress"] == 1.0
    assert payload["active"]["model"] == "org/model"
    assert "private prompt" not in response.text
    assert "/private/reference.wav" not in response.text
