from __future__ import annotations

import hashlib

import pytest

from backend import voices


def _sync(library: voices.VoiceLibrary, voice_id: str = "0123456789ab", **overrides):
    audio = overrides.pop("audio_bytes", b"not-a-real-wave-but-safe-for-storage")
    values = {
        "audio_bytes": audio,
        "original_filename": "aiden.wav",
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "name": "Aiden",
        "language": "en",
        "gender": "m",
        "license": "self-owned",
        "notes": "Fresh fleet reference",
        "source_url": None,
        "transcript": "This is the reviewed transcript.",
        "permission_acknowledged": True,
    }
    values.update(overrides)
    return library.sync_from_hub(voice_id, **values)


def test_fleet_sync_is_stable_idempotent_and_updates_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    library = voices.VoiceLibrary()

    created, status = _sync(library)
    assert status == "created"
    assert created.id == "0123456789ab"
    assert created.fleet_managed is True
    assert library.transcript(created.id) == "This is the reviewed transcript."

    current, status = _sync(library)
    assert status == "current"
    assert current.audio_sha256 == created.audio_sha256

    updated, status = _sync(library, transcript="A corrected transcript.")
    assert status == "updated"
    assert library.transcript(updated.id) == "A corrected transcript."
    assert list(tmp_path.glob(".*.tmp")) == []


def test_fleet_sync_refuses_local_id_and_changed_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    library = voices.VoiceLibrary()
    local = library.add(
        audio_bytes=b"local-audio",
        original_filename="local.wav",
        name="Local", language="en", gender="n", license="self-owned",
        permission_acknowledged=True,
    )
    local_path = tmp_path / local.id
    fleet_id = "fedcba987654"
    local_path.rename(tmp_path / fleet_id)
    metadata = tmp_path / fleet_id / voices.METADATA_FILENAME
    data = metadata.read_text().replace(local.id, fleet_id)
    metadata.write_text(data)

    with pytest.raises(voices.FleetVoiceConflict, match="local voice"):
        _sync(library, voice_id=fleet_id)

    _sync(library)
    with pytest.raises(voices.FleetVoiceConflict, match="different audio"):
        _sync(library, audio_bytes=b"different-audio")


def test_managed_delete_requires_exact_hash_and_protects_local_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    library = voices.VoiceLibrary()
    managed, _ = _sync(library)

    with pytest.raises(voices.FleetVoiceConflict, match="SHA-256"):
        library.delete_fleet_managed(managed.id, "0" * 64)
    assert library.get(managed.id) is not None
    assert library.delete_fleet_managed(managed.id, managed.audio_sha256 or "") is True
    assert library.get(managed.id) is None


def test_fleet_sync_validates_id_hash_and_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    library = voices.VoiceLibrary()

    with pytest.raises(ValueError, match="12 lowercase hex"):
        _sync(library, voice_id="../bad")
    with pytest.raises(ValueError, match="does not match"):
        _sync(library, audio_sha256="0" * 64)
    with pytest.raises(ValueError, match="permission_acknowledged"):
        _sync(library, permission_acknowledged=False)
