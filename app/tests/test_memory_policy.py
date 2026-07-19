import threading
from pathlib import Path

from fastapi.testclient import TestClient

from backend import memory_policy
from backend.main import FLEET_TOKEN, app
from backend.process_title import PROCESS_TITLE


class GenerationManager:
    def __init__(self, loaded=True, active=False, activity=100.0):
        self.loaded = loaded
        self.active = active
        self.activity = activity
        self.releases = 0

    def has_active_jobs(self):
        return self.active

    def loaded_model_keys(self):
        return [("local/test-voice", "tts-mlx")] if self.loaded else []

    def last_activity_at(self):
        return self.activity if self.loaded else None

    def release_memory_locked(self, reason="manual"):
        self.releases += 1
        was_loaded, self.loaded = self.loaded, False
        return {"released": was_loaded, "models": [["local/test-voice", "tts-mlx"]] if was_loaded else [], "actions": ["tts cleared"]}


class TranscriptionManager:
    def __init__(self, loaded=True, active=False, activity=100.0):
        self.loaded = loaded
        self.active = active
        self.activity = activity
        self.releases = 0

    def is_active(self):
        return self.active

    def loaded_model_key(self):
        return ("local/test-whisper", "whisper-stt") if self.loaded else None

    def last_activity_at(self):
        return self.activity if self.loaded else None

    def release_memory_locked(self, reason="manual"):
        self.releases += 1
        was_loaded, self.loaded = self.loaded, False
        return {"released": was_loaded, "models": [["local/test-whisper", "whisper-stt"]] if was_loaded else [], "actions": ["stt cleared"]}


def _reset(monkeypatch, tmp_path, gen=None, stt=None):
    monkeypatch.setattr(memory_policy, "SETTINGS_FILE", tmp_path / "memory_policy.json")
    monkeypatch.setattr(memory_policy, "_GEN_MANAGER", gen or GenerationManager())
    monkeypatch.setattr(memory_policy, "_STT_MANAGER", stt or TranscriptionManager())
    monkeypatch.setattr(memory_policy, "_GPU_LOCK", threading.Lock())
    monkeypatch.setattr(memory_policy, "_LAST_RELEASE_AT", None)
    monkeypatch.setattr(memory_policy, "_LAST_RELEASE_REASON", None)
    monkeypatch.setattr(memory_policy, "_LAST_RELEASE_DETAILS", None)
    monkeypatch.setattr(memory_policy, "_LAST_ERROR", None)
    monkeypatch.setattr(memory_policy, "_RELEASE_COUNT", 0)
    monkeypatch.setattr(memory_policy, "_RELEASING", False)


def test_performance_default_keeps_tts_and_whisper_loaded(tmp_path, monkeypatch):
    gen, stt = GenerationManager(), TranscriptionManager()
    _reset(monkeypatch, tmp_path, gen, stt)
    assert memory_policy.status()["mode"] == "performance"
    assert memory_policy.run_due_release(now=100_000) is None
    assert gen.releases == stt.releases == 0


def test_balanced_releases_both_caches_at_ten_minutes(tmp_path, monkeypatch):
    gen, stt = GenerationManager(), TranscriptionManager()
    _reset(monkeypatch, tmp_path, gen, stt)
    memory_policy.save("balanced")
    assert memory_policy.run_due_release(now=699) is None
    released = memory_policy.run_due_release(now=700)
    assert released["last_release_reason"] == "automatic:balanced"
    assert released["loaded_models"] == []
    assert gen.releases == stt.releases == 1


def test_active_generation_or_transcription_blocks_release(tmp_path, monkeypatch):
    client = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
    _reset(monkeypatch, tmp_path, GenerationManager(active=True), TranscriptionManager())
    assert client.post("/api/memory/release").status_code == 409
    _reset(monkeypatch, tmp_path, GenerationManager(), TranscriptionManager(active=True))
    assert client.post("/api/memory/release").status_code == 409


def test_memory_api_frontend_and_process_title(tmp_path, monkeypatch):
    _reset(monkeypatch, tmp_path)
    client = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
    saved = client.put("/api/memory-policy", json={"mode": "memory_saver"})
    assert saved.status_code == 200
    assert saved.json()["idle_seconds"] == 120
    released = client.post("/api/memory/release")
    assert released.status_code == 200
    assert released.json()["last_release_details"]["released"] is True
    assert len(released.json()["last_release_details"]["models"]) == 2

    root = Path(__file__).parents[1]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Release Memory / Unload Model" in html
    assert "Performance · default" in html
    assert 'fetch("/api/memory-policy"' in script
    assert 'fetch("/api/memory/release"' in script
    assert PROCESS_TITLE == "Voice Studio Mac"
