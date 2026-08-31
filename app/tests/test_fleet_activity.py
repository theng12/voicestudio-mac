import threading
import time

from fastapi.testclient import TestClient

from backend import main
from backend.generation import GenerationJob, GenerationManager
from backend.transcription import TranscriptionManager, _GEN_LOCK


def _manager(*jobs: GenerationJob) -> GenerationManager:
    manager = GenerationManager.__new__(GenerationManager)
    manager._lock = threading.Lock()
    manager._jobs = {job.job_id: job for job in jobs}
    return manager


def test_activity_snapshot_reports_explicit_provenance_without_private_data():
    manager = _manager(
        GenerationJob(
            "hub", "txt2speech", {
                "repo": "org/voice", "client_request_id": "studiohub:b:0",
                "text": "secret prompt", "_reference_audio_path": "/private/ref.wav",
            }, state="running", progress=0.5, started_at=20.0,
            chunk_index=2, chunk_total=4, origin="hub",
            origin_device="Studio Hub KH · PPS",
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
    assert result["active"]["source"] == "direct"
    assert result["active"]["origin"] == "hub"
    assert result["active"]["origin_device"] == "Studio Hub KH · PPS"
    assert result["active"]["model"] == "org/voice"
    assert result["active"]["chunk_index"] == 2
    assert result["active"]["chunk_total"] == 4
    assert result["active"]["updated_at"] == 25.0
    assert result["latest"]["source"] == "direct"
    assert result["latest"]["origin"] == "unknown"
    assert "origin_device" not in result["latest"]
    assert result["latest"]["runtime_s"] == 4.0
    assert "secret" not in repr(result)
    assert "/private" not in repr(result)


def test_activity_snapshot_bounds_provenance_and_loads_legacy_history_as_unknown():
    device = "trusted-device-" + "x" * 200
    job = GenerationJob(
        "bounded", "txt2speech", {"repo": "org/voice", "text": "private text"},
        state="done", started_at=float("nan"), finished_at=float("inf"),
        error="/private/error", origin="api", origin_device=device,
    )

    result = GenerationManager._activity_projection(job, observed_at=20.0)
    legacy = GenerationManager._from_disk({
        "job_id": "legacy",
        "mode": "txt2speech",
        "params": {
            "repo": "legacy/voice", "text": "private text",
            "ref_transcript": "private transcript", "_reference_audio_path": "/private/ref.wav",
        },
        "state": "done",
        "progress": 1.0,
    })

    assert result["origin"] == "api"
    assert result["origin_device"] == device[:160]
    assert result["started_at"] is None
    assert result["finished_at"] is None
    assert result["runtime_s"] is None
    assert "private" not in repr(result)
    assert legacy is not None
    assert legacy.origin == "unknown"
    assert legacy.origin_device is None


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


def test_activity_snapshot_reports_safe_latest_error_and_normalizes_invalid_evidence():
    error_manager = _manager(
        GenerationJob(
            "failed", "txt2speech", {"repo": "error/model", "text": "private prompt"},
            state="error", progress=0.7, created_at=float("inf"),
            started_at=float("nan"), finished_at="not-a-time",
            error="RuntimeError: /Users/private/secret transcript",
            error_code="SAFE_CODE",
        ),
    )

    result = error_manager.activity_snapshot(observed_at=10.0)
    latest = result["latest"]

    assert latest["id"] == "failed"
    assert latest["error"] == "Generation failed"
    assert latest["error_code"] == "SAFE_CODE"
    assert latest["created_at"] == 0.0
    assert latest["started_at"] is None
    assert latest["finished_at"] is None
    assert latest["runtime_s"] is None
    assert "private prompt" not in repr(result)
    assert "RuntimeError" not in repr(result)
    assert "/Users/private" not in repr(result)

    malformed_manager = _manager(
        GenerationJob(
            "malformed", "txt2speech", {"repo": "error/model"},
            state="error", finished_at=11.0, error_code="/private/code",
        ),
    )

    malformed = malformed_manager.activity_snapshot(observed_at=12.0)

    assert malformed["latest"]["error_code"] is None


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


def test_transcription_activity_is_live_then_retained_without_polling_private_text(monkeypatch):
    manager = TranscriptionManager()
    inference_started = threading.Event()
    release_inference = threading.Event()
    result = {}

    def fake_transcribe(*_args, **_kwargs):
        inference_started.set()
        assert release_inference.wait(timeout=2)
        return {
            "text": "private subtitle transcript",
            "language": "en",
            "duration": 12.5,
            "model": "org/whisper",
            "segments": [],
            "srt": "1\n00:00:00,000 --> 00:00:01,000\nprivate subtitle transcript\n",
            "vtt": "WEBVTT\n",
            "elapsed_seconds": 1.25,
            "resource_telemetry": None,
        }

    monkeypatch.setattr(manager, "transcribe", fake_transcribe)

    def run():
        result.update(manager.transcribe_job(
            "/private/source.wav",
            model_repo="org/whisper",
            activity_id="stt-job-1",
            origin="local_ui",
        ))

    thread = threading.Thread(target=run)
    thread.start()
    assert inference_started.wait(timeout=2)

    active = manager.activity_snapshot(observed_at=50.0)
    assert active["active"] == {
        "id": "stt-job-1",
        "state": "running",
        "model": "org/whisper",
        "operation": "transcription",
        "progress": None,
        "created_at": active["active"]["created_at"],
        "started_at": active["active"]["started_at"],
        "updated_at": 50.0,
        "source": "direct",
        "origin": "local_ui",
    }
    assert "private subtitle transcript" not in repr(active)
    assert "/private/source.wav" not in repr(active)

    release_inference.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result["task_id"] == "stt-job-1"

    latest = manager.activity_snapshot()["latest"]
    assert latest["id"] == "stt-job-1"
    assert latest["state"] == "done"
    assert latest["operation"] == "transcription"
    assert latest["runtime_s"] >= 0
    assert "private subtitle transcript" not in repr(latest)
    assert manager.get_activity("stt-job-1").params["text"] == "private subtitle transcript"


def test_transcription_waiting_for_tts_remains_queued_until_gpu_lock_is_acquired(monkeypatch):
    manager = TranscriptionManager()
    inference_started = threading.Event()
    release_inference = threading.Event()
    lock_flags = []

    def fake_transcribe(*_args, **kwargs):
        lock_flags.append(kwargs.get("_lock_already_held"))
        inference_started.set()
        assert release_inference.wait(timeout=2)
        return {"text": "done", "language": "en"}

    monkeypatch.setattr(manager, "transcribe", fake_transcribe)
    _GEN_LOCK.acquire()
    first_phase_ok = False
    try:
        thread = threading.Thread(target=lambda: manager.transcribe_job(
            "/tmp/input.wav", model_repo="org/whisper", activity_id="stt-waiting",
        ))
        thread.start()
        deadline = time.time() + 2
        queued = None
        while time.time() < deadline:
            queued = manager.activity_snapshot()["active"]
            if queued is not None:
                break
            time.sleep(0.01)
        assert queued["state"] == "queued"
        assert not inference_started.is_set()
        first_phase_ok = True
    finally:
        _GEN_LOCK.release()
        if not first_phase_ok:
            release_inference.set()
            thread.join(timeout=2)

    assert inference_started.wait(timeout=2)
    assert manager.activity_snapshot()["active"]["state"] == "running"
    assert lock_flags == [True]
    release_inference.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_fleet_activity_merges_speech_and_transcription_and_details_resolve(monkeypatch):
    speech = _manager(GenerationJob(
        "speech-queued", "txt2speech", {"repo": "org/voice"},
        state="queued", created_at=20.0,
    ))
    transcription = TranscriptionManager()
    job = transcription._start_activity(
        "stt-running", "org/whisper", origin="api", origin_device=None,
    )
    transcription._mark_activity_running(job)
    job.params["text"] = "on-demand transcript"
    monkeypatch.setattr(main, "gen_manager", speech)
    monkeypatch.setattr(main, "stt_manager", transcription)

    client = TestClient(main.app, headers={"X-Studio-Token": main.FLEET_TOKEN})
    payload = client.get("/api/fleet/activity").json()
    details = client.get("/api/fleet/jobs/stt-running/details")

    assert payload["active"]["id"] == "stt-running"
    assert payload["active"]["operation"] == "transcription"
    assert details.status_code == 200
    assert details.json()["job"]["operation"] == "transcription"
    assert details.json()["inputs"]["text"] == "on-demand transcript"
