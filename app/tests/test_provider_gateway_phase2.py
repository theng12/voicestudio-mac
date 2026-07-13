from __future__ import annotations

import json

import httpx
import pytest

from backend import generation, providers


def test_genaipro_adapter_contract(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.host == "genaipro.io":
            assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path == "/api/v1/labs/voices":
            assert request.url.params["page_size"] == "100"
            return httpx.Response(200, json=[{
                "voice_id": "voice-123",
                "name": "Warm narrator",
                "language": "en",
                "gender": "male",
                "preview_url": "https://media.genaipro.io/preview.mp3",
            }])
        if request.url.path == "/api/v1/labs/task" and request.method == "POST":
            body = json.loads(request.content)
            assert body["input"] == "Hello from Voice Studio"
            assert body["voice_id"] == "voice-123"
            assert body["model_id"] == "eleven_v3"
            assert body["speed"] == 1.2
            return httpx.Response(200, json={"task_id": "task-456"})
        if request.url.path == "/api/v1/labs/task/task-456" and request.method == "GET":
            return httpx.Response(200, json={
                "id": "task-456",
                "status": "completed",
                "result": "https://media.genaipro.io/audio/task-456.mp3",
            })
        if request.url.path == "/audio/task-456.mp3":
            return httpx.Response(
                200,
                content=b"ID3-audio",
                headers={"content-type": "audio/mpeg"},
            )
        if request.url.path == "/api/v2/me":
            return httpx.Response(200, json={"username": "tester", "balance": 42})
        if request.url.path == "/api/v1/labs/task/task-456" and request.method == "DELETE":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": "unexpected request"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def mock_client(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(providers.httpx, "Client", mock_client)
    adapter = providers.GenAIProAdapter()

    assert [model.id for model in adapter.list_models("test-token")] == [
        "eleven_multilingual_v2",
        "eleven_turbo_v2_5",
        "eleven_flash_v2_5",
        "eleven_v3",
    ]
    assert adapter.list_voices("test-token") == [{
        "id": "voice-123",
        "label": "Warm narrator",
        "lang": "en",
        "gender": "male",
        "preview_url": "https://media.genaipro.io/preview.mp3",
    }]
    submitted = adapter.submit(
        "test-token",
        "Hello from Voice Studio",
        "eleven_v3",
        "voice-123",
        {"speed": 3.0},
    )
    assert submitted.task_id == "task-456"
    polled = adapter.poll("test-token", submitted.task_id)
    assert polled.done is True
    assert polled.audio == b"ID3-audio"
    assert polled.mime == "audio/mpeg"
    assert adapter.test("test-token") == (True, "Connected as tester · balance 42.")
    adapter.cancel("test-token", submitted.task_id)
    assert ("DELETE", "/api/v1/labs/task/task-456") in seen

    with pytest.raises(RuntimeError, match="untrusted audio URL"):
        providers._download_provider_audio(
            "GenAIPro",
            "http://127.0.0.1/private",
            allowed_host_suffixes=("genaipro.io",),
        )


def test_async_cloud_job_persists_and_resumes_without_resubmit(tmp_path, monkeypatch) -> None:
    class RecallAdapter(providers.TTSAdapter):
        is_async = True

        def __init__(self) -> None:
            self.submit_calls = 0
            self.poll_calls = 0

        def submit(self, api_key, text, model, voice, params):
            self.submit_calls += 1
            return providers.SubmitResult(task_id="should-not-submit")

        def poll(self, api_key, task_id, metadata=None):
            self.poll_calls += 1
            assert task_id == "existing-paid-task"
            assert metadata == {"status_url": "https://provider.test/status"}
            return providers.PollResult(
                done=True,
                audio=b"ID3-recalled",
                mime="audio/mpeg",
                progress=1.0,
            )

        def test(self, api_key):
            return True, "ok"

    adapter = RecallAdapter()
    provider = providers.Provider(
        key="recall-test",
        name="Recall test",
        adapter=adapter,
        env_var="VOICESTUDIO_RECALL_TEST_KEY",
        supports_live_listing=False,
        curated_models=(providers.CloudModel("model", "Model"),),
    )
    output_dir = tmp_path / "output"
    history_file = output_dir / ".history.json"
    monkeypatch.setitem(providers.PROVIDERS, provider.key, provider)
    monkeypatch.setattr(providers, "is_live", lambda key: key == provider.key)
    monkeypatch.setattr(providers, "get_api_key", lambda key: "test-key")
    monkeypatch.setattr(generation, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(generation, "HISTORY_FILE", history_file)
    monkeypatch.setattr(generation, "TTS_AVAILABLE", False)

    first_manager = generation.GenerationManager()
    active = generation.GenerationJob(
        job_id="recover-job",
        mode="txt2speech",
        params={
            "repo": "provider:recall-test:model",
            "text": "Resume me",
            "voice": "voice-1",
        },
        state="running",
        provider="recall-test",
        provider_task_id="existing-paid-task",
        provider_task_meta={"status_url": "https://provider.test/status"},
    )
    first_manager._jobs[active.job_id] = active
    first_manager._persist()
    persisted = json.loads(history_file.read_text())["jobs"]
    assert persisted[0]["provider_task_id"] == "existing-paid-task"
    assert persisted[0]["provider_task_meta"] == {
        "status_url": "https://provider.test/status"
    }
    assert persisted[0]["state"] == "running"

    recovered_manager = generation.GenerationManager()
    recovered = recovered_manager.get("recover-job")
    assert recovered is not None
    assert recovered.thread is not None
    recovered.thread.join(timeout=2)

    assert recovered.state == "done"
    assert recovered.output_path is not None
    assert (output_dir / "recover-job.mp3").read_bytes() == b"ID3-recalled"
    assert adapter.submit_calls == 0
    assert adapter.poll_calls == 1


def test_fish_audio_adapter_contract(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer fish-token"
        if request.url.path == "/model":
            own_only = request.url.params.get("self") == "true"
            item = {
                "_id": "own-voice" if own_only else "public-voice",
                "type": "tts",
                "title": "My voice" if own_only else "Public narrator",
                "state": "trained",
                "tags": ["female"] if own_only else ["male"],
                "languages": ["en"],
                "samples": [{"audio": "https://audio.fish.audio/preview.mp3"}],
            }
            return httpx.Response(200, json={"items": [item], "has_more": False})
        if request.url.path == "/v1/tts":
            assert request.headers["model"] == "s2-pro"
            body = json.loads(request.content)
            assert body["reference_id"] == "own-voice"
            assert body["prosody"]["speed"] == 2.0
            return httpx.Response(
                200,
                content=b"ID3-fish",
                headers={"content-type": "audio/mpeg"},
            )
        if request.url.path == "/wallet/self/api-credit":
            return httpx.Response(200, json={"credit": "12.5"})
        return httpx.Response(404, json={"message": "unexpected request"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def mock_client(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(providers.httpx, "Client", mock_client)
    adapter = providers.FishAudioAdapter()

    voices = adapter.list_voices("fish-token")
    assert [voice["id"] for voice in voices] == ["own-voice", "public-voice"]
    audio, mime = adapter.synthesize(
        "fish-token", "Hello", "s2-pro", "own-voice", {"speed": 9}
    )
    assert (audio, mime) == (b"ID3-fish", "audio/mpeg")
    assert adapter.test("fish-token") == (True, "Connected · credit 12.5.")


def test_fal_audio_adapter_contract(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.host in {"queue.fal.run", "fal.run"}:
            assert request.headers["authorization"] == "Key fal-token"
        if request.method == "POST" and request.url.path.endswith(
            "/fal-ai/elevenlabs/tts/eleven-v3"
        ):
            body = json.loads(request.content)
            assert body["text"] == "Hello from fal"
            assert body["voice"] == "Aria"
            return httpx.Response(200, json={
                "request_id": "fal-task-1",
                "status_url": "https://queue.fal.run/tasks/fal-task-1/status",
                "response_url": "https://queue.fal.run/tasks/fal-task-1/result",
                "cancel_url": "https://queue.fal.run/tasks/fal-task-1/cancel",
            })
        if request.url.path == "/tasks/fal-task-1/status":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if request.url.path == "/tasks/fal-task-1/result":
            return httpx.Response(200, json={
                "audio": {"url": "https://v3.fal.media/files/fal-task-1.mp3"}
            })
        if request.url.path == "/files/fal-task-1.mp3":
            return httpx.Response(
                200,
                content=b"ID3-fal",
                headers={"content-type": "audio/mpeg"},
            )
        if request.url.path == "/tasks/fal-task-1/cancel":
            return httpx.Response(200, json={"ok": True})
        if request.url.host == "fal.run":
            return httpx.Response(200, json={"title": "ElevenLabs TTS"})
        return httpx.Response(404, json={"detail": "unexpected request"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def mock_client(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(providers.httpx, "Client", mock_client)
    adapter = providers.FalAudioAdapter()
    assert "Aria" in [voice["id"] for voice in adapter.list_voices("fal-token")]
    submitted = adapter.submit(
        "fal-token",
        "Hello from fal",
        "fal-ai/elevenlabs/tts/eleven-v3",
        "Aria",
        {"speed": 1.0},
    )
    assert submitted.task_id == "fal-task-1"
    assert submitted.metadata["status_url"].endswith("/status")
    result = adapter.poll("fal-token", submitted.task_id, submitted.metadata)
    assert result.done is True
    assert (result.audio, result.mime) == (b"ID3-fal", "audio/mpeg")
    adapter.cancel("fal-token", submitted.task_id, submitted.metadata)
    assert any(method == "PUT" and url.endswith("/cancel") for method, url in seen)
    assert adapter.test("fal-token") == (True, "Connected.")


def test_kie_audio_adapter_contract(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.kie.ai":
            assert request.headers["authorization"] == "Bearer kie-token"
        if request.url.path == "/api/v1/jobs/createTask":
            body = json.loads(request.content)
            assert body["model"] == "elevenlabs/text-to-speech-turbo-2-5"
            assert body["input"]["voice"] == "Rachel"
            return httpx.Response(200, json={
                "code": 200,
                "msg": "success",
                "data": {"taskId": "kie-task-1"},
            })
        if request.url.path == "/api/v1/jobs/recordInfo":
            assert request.url.params["taskId"] == "kie-task-1"
            return httpx.Response(200, json={
                "code": 200,
                "data": {
                    "state": "success",
                    "progress": 100,
                    "resultJson": json.dumps({
                        "resultUrls": [
                            "https://file.aiquickdraw.com/audio/kie-task-1.mp3"
                        ]
                    }),
                },
            })
        if request.url.path == "/audio/kie-task-1.mp3":
            return httpx.Response(
                200,
                content=b"ID3-kie",
                headers={"content-type": "audio/mpeg"},
            )
        if request.url.path == "/api/v1/chat/credit":
            return httpx.Response(200, json={"code": 200, "data": 88})
        return httpx.Response(404, json={"msg": "unexpected request"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def mock_client(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(providers.httpx, "Client", mock_client)
    adapter = providers.KieAudioAdapter()
    submitted = adapter.submit(
        "kie-token",
        "Hello from Kie",
        "elevenlabs/text-to-speech-turbo-2-5",
        "Rachel",
        {"speed": 1.0},
    )
    assert submitted.task_id == "kie-task-1"
    result = adapter.poll("kie-token", submitted.task_id)
    assert result.done is True
    assert (result.audio, result.mime) == (b"ID3-kie", "audio/mpeg")
    assert adapter.test("kie-token") == (True, "Connected · credit 88.")


def test_output_storage_includes_cloud_mp3(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    (tmp_path / "local.wav").write_bytes(b"wav")
    (tmp_path / "cloud.mp3").write_bytes(b"mp3-data")
    (tmp_path / ".history.json").write_text("{}")

    manager = generation.GenerationManager()
    stats = manager.output_stats()

    assert stats["count"] == 2
    assert stats["bytes"] == 11
    pruned = manager.prune_outputs(keep_last=1)
    assert pruned["deleted"] == 1
