import threading
from pathlib import Path
from types import SimpleNamespace

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


def test_explicit_performance_mode_keeps_tts_and_whisper_loaded(tmp_path, monkeypatch):
    """`performance` must still pin models when an operator asks for it. What
    changed in v1.32.3 is that it is no longer the *default* — see
    test_default_mode_is_no_longer_the_one_that_never_releases below."""
    gen, stt = GenerationManager(), TranscriptionManager()
    _reset(monkeypatch, tmp_path, gen, stt)
    memory_policy.save("performance")
    assert memory_policy.status()["mode"] == "performance"
    assert memory_policy.run_due_release(now=100_000) is None
    assert gen.releases == stt.releases == 0


def test_default_mode_is_no_longer_the_one_that_never_releases(tmp_path, monkeypatch):
    """With no operator choice on disk, an idle model must eventually be freed.
    Previously the default was `performance` (idle_seconds=None), so the
    release thread ran forever and did nothing."""
    gen, stt = GenerationManager(), TranscriptionManager()
    _reset(monkeypatch, tmp_path, gen, stt)
    assert memory_policy.status()["mode"] != "performance"
    assert memory_policy.run_due_release(now=100_000) is not None
    assert gen.releases == stt.releases == 1


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
    # The "· default" badge is no longer hardcoded onto Performance: since
    # v1.32.3 the default follows the host's memory, so the label is bound
    # to whatever the backend reports.
    assert "Performance" in html
    assert "memoryPolicy.default_mode==='performance'" in html
    assert 'fetch("/api/memory-policy"' in script
    assert 'fetch("/api/memory/release"' in script
    assert PROCESS_TITLE == "Voice Studio Mac"


def test_shipped_default_actually_releases_on_idle(monkeypatch) -> None:
    """The idle-release thread ran on every fleet machine and did nothing,
    because the shipped default was "performance" (idle_seconds=None). Each
    Studio ships this same skeleton, so on a shared 8 GB Mac 3-5 of them each
    independently pinned a model forever: 16 of 19 machines could not start a
    job. A default that never releases is not a default."""
    assert memory_policy.MODES[memory_policy.DEFAULT_MODE]["idle_seconds"] is not None
    assert (
        memory_policy.MODES[memory_policy.SMALL_MACHINE_DEFAULT_MODE]["idle_seconds"]
        is not None
    )

    # Small machines get the tighter budget; roomy ones keep a model warm longer.
    monkeypatch.setattr(
        memory_policy, "_SMALL_MACHINE_GB", 12, raising=False
    )
    import psutil

    monkeypatch.setattr(
        psutil, "virtual_memory",
        lambda: SimpleNamespace(total=int(8.6e9), available=int(4e9),
                                used=int(4.6e9), percent=53.0),
    )
    assert memory_policy.default_mode() == "memory_saver"

    monkeypatch.setattr(
        psutil, "virtual_memory",
        lambda: SimpleNamespace(total=int(25.8e9), available=int(18e9),
                                used=int(7.8e9), percent=30.0),
    )
    assert memory_policy.default_mode() == "balanced"


def test_operator_choice_still_wins_over_the_machine_default(monkeypatch, tmp_path) -> None:
    """An explicit mode is persisted and must survive; the memory-aware default
    only applies when nobody has chosen."""
    settings = tmp_path / "memory_policy.json"
    settings.write_text('{"mode": "performance"}\n', encoding="utf-8")
    monkeypatch.setattr(memory_policy, "SETTINGS_FILE", settings)
    assert memory_policy._read()["mode"] == "performance"


def test_ui_does_not_hardcode_performance_as_the_default() -> None:
    """The mode picker said "Performance · default". Since v1.32.3 the default is
    chosen from the host's memory, so a hardcoded label is simply wrong on every
    8 GB machine. The badge must follow whatever the backend reports."""
    markup = (Path(__file__).resolve().parents[1]
              / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "Performance · default" not in markup
    for mode in ("performance", "balanced", "memory_saver", "immediate"):
        assert f"memoryPolicy.default_mode==='{mode}'" in markup


def test_psutil_is_a_base_dependency_not_only_a_generation_extra() -> None:
    """memory_policy.default_mode() imports psutil unconditionally and its
    except-Exception fallback silently masks a missing import by defaulting to
    the roomy-machine mode -- exactly backwards on a small Mac. psutil must be
    declared in the base requirements files that install.js always installs,
    not just in requirements-generation.txt (the optional stack)."""
    app_root = Path(__file__).resolve().parents[1]
    base_txt = (app_root / "requirements.txt").read_text(encoding="utf-8")
    base_lock = (app_root / "requirements.lock.txt").read_text(encoding="utf-8")
    assert any(line.strip().startswith("psutil") for line in base_txt.splitlines())
    assert any(line.strip().startswith("psutil") for line in base_lock.splitlines())
