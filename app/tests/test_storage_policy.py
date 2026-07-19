import os
import time

from fastapi.testclient import TestClient

from backend import storage_policy
from backend.main import FLEET_TOKEN, app


class Job:
    def __init__(self, state):
        self.state = state


class Manager:
    def __init__(self, output_dir, jobs=None):
        self.output_dir = output_dir
        self.jobs = jobs or {}

    def get(self, job_id):
        return self.jobs.get(job_id)

    def delete_job(self, job_id):
        job = self.jobs.pop(job_id, None)
        if not job:
            return False
        for suffix in storage_policy.OUTPUT_SUFFIXES:
            (self.output_dir / f"{job_id}{suffix}").unlink(missing_ok=True)
        return True


def _file(root, name, size, age_days=0):
    path = root / name
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_age_and_cap_only_remove_generated_audio(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    voices_dir = tmp_path / "voices"
    output_dir.mkdir()
    voices_dir.mkdir()
    monkeypatch.setattr(storage_policy, "SETTINGS_FILE", tmp_path / "config" / "policy.json")
    manager = Manager(output_dir, {"old": Job("done"), "new": Job("done")})
    _file(output_dir, "old.wav", 4, age_days=4)
    _file(output_dir, "new.mp3", 5)
    _file(output_dir, ".history.json", 100, age_days=20)
    master = _file(voices_dir, "shared-voice.wav", 100, age_days=20)
    storage_policy.save(True, 3, 80)

    result = storage_policy.enforce(manager, output_dir, target_bytes=4)

    assert result["deleted"] == 2 and result["used_bytes"] == 0
    assert (output_dir / ".history.json").exists()
    assert master.exists()


def test_active_output_is_never_deleted(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(storage_policy, "SETTINGS_FILE", tmp_path / "config" / "policy.json")
    manager = Manager(output_dir, {"running": Job("running")})
    _file(output_dir, "running.wav", 10, age_days=10)
    storage_policy.save(True, 1, 1)

    result = storage_policy.enforce(manager, output_dir, target_bytes=0)

    assert result["deleted"] == 0
    assert (output_dir / "running.wav").exists()


def test_policy_api_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_policy, "SETTINGS_FILE", tmp_path / "config" / "policy.json")
    client = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
    response = client.put("/api/storage-policy", json={
        "enabled": True,
        "retention_days": 3,
        "max_gb": 80,
    })
    assert response.status_code == 200
    assert response.json()["retention_days"] == 3
