from __future__ import annotations

import time
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from backend import generation, main, providers, voices


def _settings_store(monkeypatch, entry: dict) -> dict:
    store = {"elevenlabs": dict(entry)}

    monkeypatch.delenv("VOICESTUDIO_ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(providers, "_all", lambda: store)

    def write(key: str, patch: dict) -> None:
        current = dict(store.get(key, {}))
        current.update(patch)
        store[key] = current

    monkeypatch.setattr(providers, "_write", write)
    providers._el_health.clear()
    providers._live_cache.clear()
    providers._voice_cache.clear()
    return store


def test_legacy_key_migrates_to_named_pool_without_exposing_secrets(monkeypatch) -> None:
    store = _settings_store(monkeypatch, {
        "api_key": "sk_legacy_secret_1234",
        "paid": True,
        "enabled": True,
    })

    assert providers.elevenlabs_accounts()[0]["id"] == "primary"
    added = providers.add_elevenlabs_account("Second plan", "sk_second_secret_5678")

    assert store["elevenlabs"]["api_key"] == ""
    assert [item["id"] for item in store["elevenlabs"]["accounts"]] == [
        "primary", added["id"],
    ]
    public = providers.public_elevenlabs_accounts()
    assert len(public) == 2
    assert all("api_key" not in item for item in public)
    assert public[0]["key_masked"].endswith("1234")
    assert "secret" not in repr(public)


def test_pool_prefers_most_remaining_credits_and_skips_exhausted(monkeypatch) -> None:
    now = time.time()
    accounts = [
        {"id": "small", "label": "Small", "api_key": "key-small", "enabled": True},
        {"id": "large", "label": "Large", "api_key": "key-large", "enabled": True},
        {"id": "empty", "label": "Empty", "api_key": "key-empty", "enabled": True},
    ]
    monkeypatch.setattr(providers, "elevenlabs_accounts", lambda: accounts)
    providers._el_health.clear()
    providers._el_health.update({
        "small": {"status": "ready", "remaining": 100, "last_checked": now},
        "large": {"status": "ready", "remaining": 900, "last_checked": now},
        "empty": {"status": "exhausted", "remaining": 0, "last_checked": now},
    })

    assert [item["id"] for item in providers.elevenlabs_candidates()] == [
        "large", "small",
    ]


def test_voice_can_map_a_different_native_id_for_each_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    voice_dir = tmp_path / "sharedvoice1"
    voice_dir.mkdir()
    (voice_dir / voices.METADATA_FILENAME).write_text(
        '{"id":"sharedvoice1","name":"Shared","language":"en","gender":"n"}'
    )
    library = voices.VoiceLibrary()

    updated = library.update("sharedvoice1", providers=[
        {"provider": "elevenlabs", "account_id": "account-a", "voice_id": "voice-a"},
        {"provider": "elevenlabs", "account_id": "account-b", "voice_id": "voice-b"},
    ])

    assert updated is not None
    assert updated.providers == [
        {"provider": "elevenlabs", "voice_id": "voice-a", "account_id": "account-a"},
        {"provider": "elevenlabs", "voice_id": "voice-b", "account_id": "account-b"},
    ]


def test_generation_fails_over_to_next_mapped_account_on_exhausted_quota(tmp_path, monkeypatch) -> None:
    accounts = [
        {"id": "first", "label": "First", "api_key": "key-first", "enabled": True},
        {"id": "second", "label": "Second", "api_key": "key-second", "enabled": True},
    ]
    library_voice = SimpleNamespace(name="Aiden", providers=[
        {"provider": "elevenlabs", "account_id": "first", "voice_id": "voice-first"},
        {"provider": "elevenlabs", "account_id": "second", "voice_id": "voice-second"},
    ])
    monkeypatch.setattr(providers, "elevenlabs_accounts", lambda: accounts)
    monkeypatch.setattr(providers, "elevenlabs_candidates", lambda allowed: accounts)
    monkeypatch.setattr(voices.library, "get", lambda voice_id: library_voice)
    reported: list[str] = []
    succeeded: list[tuple[str, int]] = []
    monkeypatch.setattr(providers, "report_elevenlabs_error", lambda account_id, exc: reported.append(account_id))
    monkeypatch.setattr(providers, "record_elevenlabs_success", lambda account_id, cost: succeeded.append((account_id, cost)))
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")

    class Adapter:
        def synthesize(self, api_key, text, model, voice_id, params):
            if api_key == "key-first":
                response = httpx.Response(
                    402,
                    json={"detail": {"code": "insufficient_credits"}},
                    request=httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech"),
                )
                raise providers.ProviderRequestError("ElevenLabs", response)
            assert voice_id == "voice-second"
            return b"ID3-success", "audio/mpeg"

    manager = generation.GenerationManager()
    monkeypatch.setattr(manager, "_persist", lambda: None)
    job = generation.GenerationJob(
        job_id="pool-job",
        mode="txt2speech",
        provider="elevenlabs",
        params={"voice_library_id": "library-aiden"},
    )

    result = manager._run_elevenlabs_pool(
        job, Adapter(), "eleven_multilingual_v2", "Hello", "",
    )

    assert result == (b"ID3-success", "audio/mpeg")
    assert reported == ["first"]
    assert succeeded == [("second", 5)]
    assert job.provider_account_id == "second"
    assert job.params["voice"] == "voice-second"


def test_stable_client_request_id_returns_the_original_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")

    class IdleThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(generation.threading, "Thread", IdleThread)
    manager = generation.GenerationManager()
    params = {
        "repo": "provider:elevenlabs:eleven_multilingual_v2",
        "text": "Only once",
        "voice_library_id": "aiden",
        "client_request_id": "studiohub:batch-1:0",
    }

    first = manager.start_txt2speech(dict(params))
    same = manager.start_txt2speech(dict(params))

    assert same is first
    assert len(manager.list_jobs()) == 1
    with pytest.raises(ValueError, match="different request"):
        manager.start_txt2speech({**params, "text": "Changed"})


def test_active_bound_elevenlabs_job_is_persisted_for_restart_recovery(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    history = tmp_path / ".history.json"
    monkeypatch.setattr(generation, "HISTORY_FILE", history)
    manager = generation.GenerationManager()
    job = generation.GenerationJob(
        job_id="restart-paid",
        mode="txt2speech",
        provider="elevenlabs",
        provider_account_id="account-a",
        state="running",
        params={
            "repo": "provider:elevenlabs:eleven_multilingual_v2",
            "text": "Recover after restart",
            "voice": "voice-a",
            "client_request_id": "studiohub:batch-2:0",
        },
    )
    manager._jobs[job.job_id] = job

    manager._persist()

    saved = json.loads(history.read_text())["jobs"]
    assert [item["job_id"] for item in saved] == ["restart-paid"]
    assert saved[0]["provider_account_id"] == "account-a"


def test_restart_recovery_adopts_history_audio_without_new_synthesis(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(generation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(generation, "HISTORY_FILE", tmp_path / ".history.json")
    manager = generation.GenerationManager()
    monkeypatch.setattr(manager, "_persist", lambda: None)
    monkeypatch.setattr(providers, "get_elevenlabs_account", lambda account_id: {
        "id": account_id, "api_key": "account-key",
    })
    adapter = providers.PROVIDERS["elevenlabs"].adapter
    monkeypatch.setattr(
        adapter,
        "recover_recent",
        lambda *args, **kwargs: (b"ID3-from-history", "audio/mpeg"),
    )
    job = generation.GenerationJob(
        job_id="restart-recover",
        mode="txt2speech",
        provider="elevenlabs",
        provider_account_id="account-a",
        state="running",
        started_at=time.time() - 2,
        params={
            "repo": "provider:elevenlabs:eleven_multilingual_v2",
            "text": "Recover after restart",
            "voice": "voice-a",
        },
    )

    manager._recover_elevenlabs_after_restart(job)

    assert job.state == "done"
    assert (tmp_path / "restart-recover.mp3").read_bytes() == b"ID3-from-history"


def test_dropped_response_recovers_exact_history_item_without_resubmit(monkeypatch) -> None:
    post_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.method == "POST":
            post_calls += 1
            raise httpx.ReadError("response dropped", request=request)
        if request.url.path == "/v1/history":
            return httpx.Response(200, json={"history": [{
                "history_item_id": "history-1",
                "text": "Recover me",
                "voice_id": "voice-1",
                "model_id": "eleven_multilingual_v2",
                "date_unix": int(time.time()),
            }]})
        if request.url.path == "/v1/history/history-1/audio":
            return httpx.Response(200, content=b"ID3-recovered", headers={"content-type": "audio/mpeg"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(providers.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))

    result = providers.ElevenLabsAdapter().synthesize(
        "test-key", "Recover me", "eleven_multilingual_v2", "voice-1", {},
    )

    assert result == (b"ID3-recovered", "audio/mpeg")
    assert post_calls == 1


def test_ambiguous_dropped_response_is_not_resubmitted(monkeypatch) -> None:
    post_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.method == "POST":
            post_calls += 1
            raise httpx.ReadError("response dropped", request=request)
        now = int(time.time())
        return httpx.Response(200, json={"history": [
            {"history_item_id": "one", "text": "Same", "voice_id": "voice-1", "model_id": "model-1", "date_unix": now},
            {"history_item_id": "two", "text": "Same", "voice_id": "voice-1", "model_id": "model-1", "date_unix": now},
        ]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(providers.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(providers.time, "sleep", lambda _: None)

    with pytest.raises(providers.ProviderResultUncertain, match="not resubmitted"):
        providers.ElevenLabsAdapter().synthesize(
            "test-key", "Same", "model-1", "voice-1", {},
        )

    assert post_calls == 1


def test_voice_mapping_rejects_unknown_account(monkeypatch) -> None:
    monkeypatch.setattr(providers, "get_elevenlabs_account", lambda account_id: None)
    body = main.UpdateVoiceBody(providers=[main.VoiceProviderTagBody(
        provider="elevenlabs", account_id="missing", voice_id="voice-1",
    )])

    with pytest.raises(HTTPException, match="Unknown ElevenLabs account") as exc:
        main.update_voice("unused", body)

    assert exc.value.status_code == 400
