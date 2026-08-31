import base64
import json
import logging

import pytest
from fastapi.testclient import TestClient

from backend import fleet_auth, job_details, main
from backend.generation import GenerationJob, GenerationManager
from backend.job_details import JobMediaError, build_job_details, resolve_job_media


WAV_BYTES = b"RIFF" + bytes(range(64))


def voice_job(tmp_path):
    output = tmp_path / "output" / "job-1.wav"
    prepared = tmp_path / "prepared" / "reference.wav"
    saved = tmp_path / "voices" / "voice-1" / "reference.wav"
    output.parent.mkdir()
    prepared.parent.mkdir()
    saved.parent.mkdir(parents=True)
    output.write_bytes(WAV_BYTES)
    prepared.write_bytes(WAV_BYTES)
    saved.write_bytes(WAV_BYTES)
    return GenerationJob(
        "job-1", "txt2speech", {
            "repo": "org/model", "text": "Narration text",
            "ref_transcript": "Reference words", "voice_library_id": "voice-1",
            "language": "en", "speed": 1.0, "instruct": "calm",
            "_reference_audio_path": str(prepared),
            "_reference_audio_sha256": "a" * 64,
            "_reference_source_sha256": "b" * 64,
            "client_request_id": "studiohub:private-request",
            "token": "private-credential",
        }, state="done", output_path=str(output), origin="api",
        started_at=10.0, finished_at=18.0, chunk_index=1, chunk_total=3,
        sha256="c" * 64, client_request_params={"secret": "private"},
        quality_validation={"internal": "private"},
        quality_retry_history=[{"internal": "private"}],
    )


@pytest.fixture
def configured_job(tmp_path, monkeypatch):
    job = voice_job(tmp_path)
    monkeypatch.setattr(job_details, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(job_details.reference_audio, "ROOT", tmp_path / "prepared")
    monkeypatch.setattr(job_details.voices, "VOICES_DIR", tmp_path / "voices")
    monkeypatch.setattr(
        job_details.voices.library,
        "reference_path",
        lambda voice_id: (
            tmp_path / "voices" / voice_id / "reference.wav"
            if voice_id == "voice-1" else None
        ),
    )
    return job


def test_voice_detail_projection_is_allowlisted_and_path_free(configured_job):
    details = build_job_details(configured_job, "fleet-secret", now=100)

    assert details["schema"] == "kh-studio.job-details.v1"
    assert details["studio"] == "voice"
    assert details["job"] == {
        "id": "job-1",
        "state": "done",
        "model": "org/model",
        "operation": "txt2speech",
        "created_at": configured_job.created_at,
        "started_at": 10.0,
        "finished_at": 18.0,
        "runtime_s": 8.0,
        "origin": "api",
        "origin_device": None,
    }
    assert details["inputs"] == {
        "prompt": None,
        "negative_prompt": None,
        "text": "Narration text",
        "reference_transcript": "Reference words",
        "parameters": {
            "voice_library_id": "voice-1",
            "language": "en",
            "speed": 1.0,
            "instruct": "calm",
            "chunk_index": 1,
            "chunk_total": 3,
        },
    }
    assert len(details["references"]) == 1
    assert len(details["outputs"]) == 1
    for item, kind, name in (
        (details["references"][0], "reference", "reference.wav"),
        (details["outputs"][0], "output", "job-1.wav"),
    ):
        assert item == {
            "kind": kind,
            "name": name,
            "media_type": "audio/wav",
            "size_bytes": len(WAV_BYTES),
            "duration_s": None,
            "handle": item["handle"],
            "expires_at": 400,
        }
        assert item["handle"]
        assert "job-1" not in item["handle"]
        assert name not in item["handle"]

    serialized = json.dumps(details)
    for private in (
        "_reference_audio_path", "_reference_audio_sha256",
        "_reference_source_sha256", "client_request_id",
        "client_request_params", "quality_validation", "quality_retry_history",
        "private-credential", configured_job.params["_reference_audio_path"],
        configured_job.output_path, "a" * 64, "b" * 64, "c" * 64,
    ):
        assert private not in serialized


@pytest.mark.parametrize(
    ("state", "progress", "expected"),
    (
        ("running", 0.42, 0.42),
        ("queued", 2.0, 1.0),
        ("running", -1.0, 0.0),
        ("running", float("nan"), 0.0),
        ("running", "legacy", 0.0),
    ),
)
def test_active_voice_detail_progress_is_bounded(
    configured_job, state, progress, expected,
):
    configured_job.state = state
    configured_job.progress = progress

    details = build_job_details(configured_job, "fleet-secret", now=100)

    assert details["job"]["progress"] == expected


def test_transcription_details_label_the_result_as_transcription_without_media():
    from backend.transcription import TranscriptionActivityJob

    job = TranscriptionActivityJob(
        job_id="stt-1", model="org/whisper", state="done",
        params={
            "repo": "org/whisper", "text": "Subtitle transcript",
            "language": "en", "word_timestamps": True,
            "input_filename": "episode.wav",
        },
        origin="local_ui", created_at=10.0, started_at=11.0, finished_at=13.0,
    )

    details = build_job_details(job, "fleet-secret", now=20.0)

    assert details["job"]["operation"] == "transcription"
    assert details["inputs"]["text"] == "Subtitle transcript"
    assert details["inputs"]["parameters"] == {
        "language": "en", "word_timestamps": True, "input_filename": "episode.wav",
    }
    assert details["references"] == []
    assert details["outputs"] == []


def test_saved_library_reference_is_used_only_without_a_private_reference(configured_job):
    saved_job = GenerationJob(
        "saved-job", "txt2speech", {
            "repo": "org/model", "text": "Saved voice",
            "voice_library_id": "voice-1",
        }, state="done",
    )

    details = build_job_details(saved_job, "fleet-secret", now=100)
    target = resolve_job_media(
        saved_job, details["references"][0]["handle"], "fleet-secret", now=100,
    )

    assert details["references"][0]["name"] == "reference.wav"
    assert target.path == (job_details.voices.VOICES_DIR / "voice-1" / "reference.wav").resolve()


@pytest.mark.parametrize(
    ("collection", "root", "expected"),
    (
        ("references", "prepared", "reference.wav"),
        ("outputs", "output", "job-1.wav"),
    ),
)
def test_signed_handles_resolve_only_the_recorded_media(
    configured_job, collection, root, expected,
):
    details = build_job_details(configured_job, "fleet-secret", now=100)
    handle = details[collection][0]["handle"]

    target = resolve_job_media(configured_job, handle, "fleet-secret", now=100)

    expected_root = (
        job_details.reference_audio.ROOT if root == "prepared" else job_details.OUTPUT_DIR
    )
    assert target.path == (expected_root / expected).resolve()
    assert target.media_type == "audio/wav"
    assert target.name == expected


def test_handle_expires_after_exactly_300_seconds(configured_job):
    handle = build_job_details(configured_job, "fleet-secret", now=100)["outputs"][0]["handle"]

    assert resolve_job_media(configured_job, handle, "fleet-secret", now=399.999).path.name == "job-1.wav"
    with pytest.raises(JobMediaError, match="handle_expired"):
        resolve_job_media(configured_job, handle, "fleet-secret", now=400)
    with pytest.raises(JobMediaError, match="handle_expired"):
        resolve_job_media(configured_job, handle, "fleet-secret", now=401)


def test_tampered_handle_is_permission_denied(configured_job):
    handle = build_job_details(configured_job, "fleet-secret", now=100)["outputs"][0]["handle"]
    tampered = handle[:-1] + ("A" if handle[-1] != "A" else "B")

    with pytest.raises(JobMediaError, match="permission_denied"):
        resolve_job_media(configured_job, tampered, "fleet-secret", now=100)


def test_pruned_media_returns_media_removed_even_with_fresh_handle(configured_job):
    output = job_details.OUTPUT_DIR / "job-1.wav"
    output.unlink()
    fresh_handle = build_job_details(configured_job, "fleet-secret", now=100)["outputs"][0]["handle"]

    with pytest.raises(JobMediaError, match="media_removed"):
        resolve_job_media(configured_job, fresh_handle, "fleet-secret", now=100)


def test_outside_root_media_is_never_issued_a_handle(configured_job, tmp_path, monkeypatch):
    outside = tmp_path / "outside.wav"
    outside.write_bytes(WAV_BYTES)
    private_job = GenerationJob(
        "outside-private", "txt2speech",
        {"_reference_audio_path": str(outside)}, output_path=str(outside),
    )
    saved_job = GenerationJob(
        "outside-saved", "txt2speech", {"voice_library_id": "voice-1"},
    )
    monkeypatch.setattr(
        job_details.voices.library, "reference_path", lambda _voice_id: outside,
    )

    private_details = build_job_details(private_job, "fleet-secret", now=100)
    saved_details = build_job_details(saved_job, "fleet-secret", now=100)

    assert private_details["references"] == []
    assert private_details["outputs"] == []
    assert saved_details["references"] == []


def test_symlink_under_approved_root_is_rejected_at_access(configured_job, tmp_path):
    reference = job_details.reference_audio.ROOT / "reference.wav"
    handle = build_job_details(configured_job, "fleet-secret", now=100)["references"][0]["handle"]
    outside = tmp_path / "outside.wav"
    outside.write_bytes(WAV_BYTES)
    reference.unlink()
    reference.symlink_to(outside)

    with pytest.raises(JobMediaError, match="media_removed"):
        resolve_job_media(configured_job, handle, "fleet-secret", now=100)


def test_symlinked_approved_root_is_rejected_at_access(tmp_path, monkeypatch):
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    output = outside_root / "job-root-link.wav"
    output.write_bytes(WAV_BYTES)
    linked_root = tmp_path / "linked-output"
    linked_root.symlink_to(outside_root, target_is_directory=True)
    monkeypatch.setattr(job_details, "OUTPUT_DIR", linked_root)
    job = GenerationJob(
        "job-root-link", "txt2speech", {}, state="done",
        output_path=str(linked_root / output.name),
    )
    handle = build_job_details(job, "fleet-secret", now=100)["outputs"][0]["handle"]

    with pytest.raises(JobMediaError, match="media_removed"):
        resolve_job_media(job, handle, "fleet-secret", now=100)


def test_handle_is_bound_to_job_kind_and_index(configured_job):
    handle = build_job_details(configured_job, "fleet-secret", now=100)["references"][0]["handle"]
    other = GenerationJob(
        "job-2", configured_job.mode, configured_job.params,
        state="done", output_path=configured_job.output_path,
    )

    with pytest.raises(JobMediaError, match="permission_denied"):
        resolve_job_media(other, handle, "fleet-secret", now=100)

    payload, signature = handle.split(".", 1)
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    for key, value in (("k", "output"), ("i", 1)):
        changed = dict(decoded, **{key: value})
        encoded = base64.urlsafe_b64encode(
            json.dumps(changed, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=").decode()
        with pytest.raises(JobMediaError, match="permission_denied"):
            resolve_job_media(configured_job, f"{encoded}.{signature}", "fleet-secret", now=100)


def test_fleet_detail_and_media_http_contract(configured_job, monkeypatch, caplog):
    manager = GenerationManager.__new__(GenerationManager)
    manager._jobs = {configured_job.job_id: configured_job}
    monkeypatch.setattr(main, "gen_manager", manager)
    monkeypatch.setattr(fleet_auth, "load_token", lambda: "fleet-secret")

    assert TestClient(main.app).get(
        "/api/fleet/jobs/job-1/details",
        headers={"host": "worker.example"},
    ).status_code == 401

    client = TestClient(
        main.app,
        headers={"X-Studio-Token": "fleet-secret", "host": "worker.example"},
    )
    missing = client.get("/api/fleet/jobs/missing/details")
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "job_not_found"}}

    details_response = client.get("/api/fleet/jobs/job-1/details")
    assert details_response.status_code == 200
    handle = details_response.json()["outputs"][0]["handle"]

    inline = client.get(f"/api/fleet/jobs/job-1/media/{handle}")
    assert inline.status_code == 200
    assert inline.content == WAV_BYTES
    assert inline.headers["content-disposition"].startswith("inline;")

    ranged = client.get(
        f"/api/fleet/jobs/job-1/media/{handle}",
        headers={"Range": "bytes=0-0"},
    )
    assert ranged.status_code == 206
    assert ranged.content == WAV_BYTES[:1]
    assert ranged.headers["content-range"] == f"bytes 0-0/{len(WAV_BYTES)}"

    download = client.get(f"/api/fleet/jobs/job-1/media/{handle}?download=true")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")

    for response in (details_response, inline, ranged, download):
        assert response.headers["cache-control"] == "no-store, private, max-age=0"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"

    (job_details.OUTPUT_DIR / "job-1.wav").unlink()
    removed = client.get(f"/api/fleet/jobs/job-1/media/{handle}")
    assert removed.status_code == 410
    assert removed.json() == {"detail": {"code": "media_removed"}}

    private_values = (
        configured_job.params["text"], configured_job.output_path,
        "fleet-secret", handle,
    )
    with caplog.at_level(logging.WARNING):
        denied = client.get(f"/api/fleet/jobs/job-1/media/{handle}x")
    assert denied.status_code == 403
    assert denied.json() == {"detail": {"code": "permission_denied"}}
    for value in private_values:
        assert value not in denied.text
        assert value not in caplog.text


def test_fleet_detail_and_media_errors_always_set_private_no_store_headers(
    configured_job, monkeypatch,
):
    manager = GenerationManager.__new__(GenerationManager)
    manager._jobs = {configured_job.job_id: configured_job}
    monkeypatch.setattr(main, "gen_manager", manager)
    monkeypatch.setattr(fleet_auth, "load_token", lambda: "fleet-secret")
    unauthorized = TestClient(main.app).get(
        "/api/fleet/jobs/job-1/details", headers={"host": "worker.example"},
    )
    client = TestClient(
        main.app,
        headers={"X-Studio-Token": "fleet-secret", "host": "worker.example"},
    )
    missing_details = client.get("/api/fleet/jobs/missing/details")
    missing_media = client.get("/api/fleet/jobs/missing/media/not-a-handle")
    handle = client.get("/api/fleet/jobs/job-1/details").json()["outputs"][0]["handle"]
    denied = client.get(f"/api/fleet/jobs/job-1/media/{handle}x")
    expired_handle = build_job_details(
        configured_job, "fleet-secret", now=0,
    )["outputs"][0]["handle"]
    expired = client.get(f"/api/fleet/jobs/job-1/media/{expired_handle}")
    (job_details.OUTPUT_DIR / "job-1.wav").unlink()
    removed = client.get(f"/api/fleet/jobs/job-1/media/{handle}")

    assert [response.status_code for response in (
        unauthorized, missing_details, missing_media, denied, expired, removed,
    )] == [401, 404, 404, 403, 410, 410]
    assert missing_details.json() == {"detail": {"code": "job_not_found"}}
    assert missing_media.json() == {"detail": {"code": "job_not_found"}}
    assert denied.json() == {"detail": {"code": "permission_denied"}}
    assert expired.json() == {"detail": {"code": "handle_expired"}}
    assert removed.json() == {"detail": {"code": "media_removed"}}
    for response in (
        unauthorized, missing_details, missing_media, denied, expired, removed,
    ):
        assert response.headers["cache-control"] == "no-store, private, max-age=0"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
