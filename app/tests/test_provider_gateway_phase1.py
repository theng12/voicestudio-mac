from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from backend import main, providers, voices


def test_old_voice_metadata_defaults_to_no_provider_tags(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    voice_dir = tmp_path / "legacyvoice1"
    voice_dir.mkdir()
    (voice_dir / voices.METADATA_FILENAME).write_text(json.dumps({
        "id": "legacyvoice1",
        "name": "Legacy voice",
        "language": "en",
        "gender": "n",
    }))

    library = voices.VoiceLibrary()
    loaded = library.get("legacyvoice1")

    assert loaded is not None
    assert loaded.providers == []


def test_voice_provider_tags_are_validated_and_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    voice_dir = tmp_path / "mappedvoice1"
    voice_dir.mkdir()
    (voice_dir / voices.METADATA_FILENAME).write_text(json.dumps({
        "id": "mappedvoice1",
        "name": "Mapped voice",
        "language": "en",
        "gender": "f",
    }))
    library = voices.VoiceLibrary()

    updated = library.update("mappedvoice1", providers=[
        {"provider": "ElevenLabs", "voice_id": "voice-native-123"},
        {"provider": "fal", "voice_id": "fal-native-456"},
    ])

    assert updated is not None
    assert updated.providers == [
        {"provider": "elevenlabs", "voice_id": "voice-native-123"},
        {"provider": "fal", "voice_id": "fal-native-456"},
    ]
    reloaded = library.get("mappedvoice1")
    assert reloaded is not None
    assert reloaded.providers == updated.providers

    with pytest.raises(ValueError, match="more than once"):
        library.update("mappedvoice1", providers=[
            {"provider": "elevenlabs", "voice_id": "first"},
            {"provider": "elevenlabs", "voice_id": "second"},
        ])


def test_provider_voice_catalog_is_normalized_and_cached(monkeypatch) -> None:
    provider = providers.PROVIDERS["elevenlabs"]
    calls = []

    def fake_list_voices(api_key: str) -> list[dict]:
        calls.append(api_key)
        return [
            {"id": "voice-1", "label": "Narrator", "lang": "en", "gender": "f"},
            {"id": "", "label": "Invalid"},
        ]

    monkeypatch.setattr(providers, "has_key", lambda key: True)
    monkeypatch.setattr(providers, "get_api_key", lambda key: "test-key")
    monkeypatch.setattr(provider.adapter, "list_voices", fake_list_voices)
    providers._voice_cache.clear()

    first = providers.voices_for_provider("elevenlabs", force=True)
    second = providers.voices_for_provider("elevenlabs")

    assert calls == ["test-key"]
    assert first == second == [{
        "id": "voice-1",
        "label": "Narrator",
        "lang": "en",
        "gender": "f",
        "preview_url": "",
    }]
    assert providers.serialize_provider("elevenlabs", include_models=False)["voice_mapping_supported"] is True


def test_provider_serialization_exposes_available_model_count_without_consent(monkeypatch) -> None:
    monkeypatch.setattr(providers, "has_key", lambda key: True)
    monkeypatch.setattr(providers, "paid_enabled", lambda key: False)
    monkeypatch.setattr(providers, "is_enabled", lambda key: True)
    data = providers.serialize_provider("fal")

    assert data["models"] == []
    assert data["available_model_count"] == len(providers.PROVIDERS["fal"].curated_models)


def test_voice_update_rejects_unknown_provider() -> None:
    body = main.UpdateVoiceBody(providers=[
        main.VoiceProviderTagBody(provider="unknown-cloud", voice_id="voice-1"),
    ])

    with pytest.raises(HTTPException, match="Unknown providers") as exc:
        main.update_voice("unused-voice-id", body)

    assert exc.value.status_code == 400
