from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from backend.auto_update import AutoUpdater, UpdateDeferred, UpdateError, _parse_iso, _redact


@pytest.fixture
def updater(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AutoUpdater:
    root = tmp_path / "voicestudio-mac.git"
    (root / ".git").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "conda_env" / "bin").mkdir(parents=True)
    (root / "VERSION").write_text("1.0.0\n")
    (root / "app" / "requirements.txt").write_text("fastapi\n")
    python = root / "conda_env" / "bin" / "python"
    python.symlink_to(sys.executable)
    spec = {
        "root": str(root), "title": "Voice Studio KH", "slug": "voicestudio-test",
        "expected_remote": "https://github.com/theng12/voicestudio-mac.git",
        "branch": "main", "port": 47870, "default_hour": 2,
        "server_label": "com.kh.voicestudio.server",
        "watchdog_label": "com.kh.voicestudio.watchdog",
    }
    item = AutoUpdater(spec)
    monkeypatch.setattr(item, "scheduler_status", lambda: {
        "installed": item.settings()["mode"] != "off", "supported": True,
        "label": item.agent_label,
    })
    monkeypatch.setattr(item, "apply_scheduler", lambda force_pending=False: {
        "installed": item.settings()["mode"] != "off" or force_pending,
        "supported": True, "label": item.agent_label,
    })
    monkeypatch.setattr(item, "_notify", lambda *args: None)
    return item


def _spec(root: Path) -> dict:
    return {
        "root": str(root), "title": "Voice Studio KH", "slug": "voicestudio-test",
        "expected_remote": "https://github.com/theng12/voicestudio-mac.git",
        "branch": "main", "port": 47870, "default_hour": 2,
        "server_label": "com.kh.voicestudio.server",
        "watchdog_label": "com.kh.voicestudio.watchdog",
    }


def test_linked_worktree_gitfile_is_accepted(tmp_path: Path):
    root = tmp_path / "linked-worktree"
    root.mkdir()
    gitdir = tmp_path / "main-repository.git" / "worktrees" / "linked-worktree"
    gitdir.mkdir(parents=True)
    (root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    assert AutoUpdater(_spec(root)).root == root.resolve()


@pytest.mark.parametrize("gitfile", [
    "", "not a gitfile\n", "gitdir:\n", "gitdir: \n", "gitdir: first\ngitdir: second\n",
])
def test_malformed_linked_worktree_gitfiles_are_rejected(tmp_path: Path, gitfile: str):
    root = tmp_path / "linked-worktree"
    root.mkdir()
    (root / ".git").write_text(gitfile, encoding="utf-8")

    with pytest.raises(UpdateError, match="real Git checkout"):
        AutoUpdater(_spec(root))


def test_linked_worktree_gitfile_with_missing_target_is_rejected(tmp_path: Path):
    root = tmp_path / "linked-worktree"
    root.mkdir()
    (root / ".git").write_text("gitdir: missing-worktree-metadata\n", encoding="utf-8")

    with pytest.raises(UpdateError, match="real Git checkout"):
        AutoUpdater(_spec(root))


def test_symlinked_updater_root_is_rejected(tmp_path: Path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(checkout, target_is_directory=True)

    with pytest.raises(UpdateError, match="real Git checkout"):
        AutoUpdater(_spec(linked_root))


def test_symlinked_git_marker_is_rejected(tmp_path: Path):
    root = tmp_path / "checkout"
    root.mkdir()
    real_gitdir = tmp_path / "real-gitdir"
    real_gitdir.mkdir()
    (root / ".git").symlink_to(real_gitdir, target_is_directory=True)

    with pytest.raises(UpdateError, match="real Git checkout"):
        AutoUpdater(_spec(root))


def _save(updater: AutoUpdater, mode: str) -> dict:
    return updater.save_settings({
        "mode": mode, "frequency": "daily", "maintenance_hour": 2,
        "idle_only": True,
    })


def test_default_is_off_and_idle_only(updater: AutoUpdater):
    assert updater.settings() == {
        "mode": "off", "frequency": "daily", "maintenance_hour": 2,
        "idle_only": True, "weekday": 6,
    }
    assert updater.public_status()["scheduler"]["installed"] is False


def test_settings_modes_install_and_remove_schedule(updater: AutoUpdater):
    assert _save(updater, "notify")["scheduler"]["installed"] is True
    assert _save(updater, "auto")["scheduler"]["installed"] is True
    status = _save(updater, "off")
    assert status["scheduler"]["installed"] is False
    assert status["next_check"] is None


def test_invalid_settings_are_rejected(updater: AutoUpdater):
    with pytest.raises(UpdateError):
        updater.save_settings({"mode": "always", "frequency": "daily",
                               "maintenance_hour": 2, "idle_only": True})
    with pytest.raises(UpdateError):
        updater.save_settings({"mode": "auto", "frequency": "daily",
                               "maintenance_hour": 24, "idle_only": True})


def test_notify_only_checks_but_does_not_install(updater: AutoUpdater, monkeypatch):
    _save(updater, "notify")
    updater._write_status(next_check="2000-01-01T00:00:00Z")
    monkeypatch.setattr(updater, "check", lambda: {"update_available": True, "latest_version": "2.0.0"})
    called = []
    monkeypatch.setattr(updater, "update", lambda **kwargs: called.append(kwargs))
    monkeypatch.setattr(updater, "_notify", lambda *args: called.append("notify"))
    updater.scheduled()
    assert called == ["notify"]


def test_auto_mode_installs_available_update(updater: AutoUpdater, monkeypatch):
    _save(updater, "auto")
    updater._write_status(next_check="2000-01-01T00:00:00Z")
    monkeypatch.setattr(updater, "check", lambda: {"update_available": True, "latest_version": "2.0.0"})
    called = []
    monkeypatch.setattr(updater, "update", lambda **kwargs: called.append(kwargs) or {"state": "succeeded"})
    updater.scheduled()
    assert called == [{"automatic": True}]


def test_active_work_defers_and_records_reason(updater: AutoUpdater, monkeypatch):
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: ["voice generation is running"])
    with pytest.raises(UpdateDeferred):
        updater.update(automatic=True)
    status = updater.public_status()
    assert status["state"] == "deferred"
    assert "voice generation" in status["defer_reason"]
    assert status["next_retry"]


def test_update_after_work_creates_pending_retry(updater: AutoUpdater, monkeypatch):
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: ["download active"])
    status = updater.trigger_update(after_current=True)
    assert status["pending_manual"] is True
    assert status["state"] == "deferred"


def test_concurrent_update_lock_is_refused(updater: AutoUpdater):
    with updater._exclusive_lock():
        with pytest.raises(UpdateError, match="already running"):
            with updater._exclusive_lock():
                pass


@pytest.mark.parametrize("case, message", [
    ("remote", "Unexpected Git remote"),
    ("branch", "configured main branch"),
    ("dirty", "local changes"),
    ("diverged", "diverged"),
])
def test_git_safety_refusals(updater: AutoUpdater, monkeypatch, case, message):
    def fake_git(*args, **kwargs):
        command = tuple(args)
        if command == ("remote", "get-url", "origin"):
            return "https://github.com/attacker/wrong.git" if case == "remote" else updater.spec["expected_remote"]
        if command[:3] == ("symbolic-ref", "--quiet", "--short"):
            return "feature" if case == "branch" else "main"
        if command[:2] == ("status", "--porcelain"):
            return " M local.txt" if case == "dirty" else ""
        if command[:1] == ("fetch",):
            return ""
        if command == ("rev-parse", "HEAD"):
            return "a" * 40
        if command == ("rev-parse", "origin/main"):
            return "b" * 40
        if command[:1] == ("show",):
            return "2.0.0"
        raise AssertionError(command)
    monkeypatch.setattr(updater, "_git", fake_git)
    def fake_run(args, **kwargs):
        rc = 1 if case == "diverged" and "merge-base" in args else 0
        return subprocess.CompletedProcess(args, rc, "", "")
    monkeypatch.setattr(updater, "_run", fake_run)
    with pytest.raises(UpdateError, match=message):
        updater._git_preflight()


def test_dirty_worktree_refusal_lists_the_blocking_paths(updater: AutoUpdater, monkeypatch):
    def fake_git(*args, **kwargs):
        command = tuple(args)
        if command == ("remote", "get-url", "origin"):
            return updater.spec["expected_remote"]
        if command[:3] == ("symbolic-ref", "--quiet", "--short"):
            return "main"
        if command[:2] == ("status", "--porcelain"):
            return " M app/backend/main.py\n?? notes.txt\n"
        raise AssertionError(command)
    monkeypatch.setattr(updater, "_git", fake_git)
    with pytest.raises(UpdateError) as excinfo:
        updater._git_preflight()
    message = str(excinfo.value)
    assert "app/backend/main.py" in message
    assert "notes.txt" in message
    assert "more" not in message


def test_dirty_worktree_refusal_caps_the_path_preview_at_five(updater: AutoUpdater, monkeypatch):
    porcelain_lines = "\n".join(f" M file{i}.txt" for i in range(8))

    def fake_git(*args, **kwargs):
        command = tuple(args)
        if command == ("remote", "get-url", "origin"):
            return updater.spec["expected_remote"]
        if command[:3] == ("symbolic-ref", "--quiet", "--short"):
            return "main"
        if command[:2] == ("status", "--porcelain"):
            return porcelain_lines
        raise AssertionError(command)
    monkeypatch.setattr(updater, "_git", fake_git)
    with pytest.raises(UpdateError) as excinfo:
        updater._git_preflight()
    message = str(excinfo.value)
    for i in range(5):
        assert f"file{i}.txt" in message
    for i in range(5, 8):
        assert f"file{i}.txt" not in message
    assert "and 3 more" in message


def test_disk_space_failure_happens_before_files_change(updater: AutoUpdater, monkeypatch):
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr("backend.auto_update.shutil.disk_usage", lambda _p: type("D", (), {"free": 1})())
    monkeypatch.setattr(updater, "_git_preflight", lambda **kwargs: pytest.fail("Git update must not start"))
    with pytest.raises(UpdateError, match="disk space"):
        updater.update()


@pytest.mark.parametrize("failure", ["dependencies", "health"])
def test_install_or_health_failure_attempts_rollback(updater: AutoUpdater, monkeypatch, failure):
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "_git_preflight", lambda **kwargs: {
        "local": "a" * 40, "remote": "b" * 40, "latest": "2.0.0", "available": True,
    })
    monkeypatch.setattr(updater, "_stop_mode", lambda mode: None)
    monkeypatch.setattr(updater, "_git", lambda *args, **kwargs: "")
    monkeypatch.setattr(updater, "_verify_import", lambda expected: None)
    monkeypatch.setattr(updater, "_start_mode", lambda mode: None)
    monkeypatch.setattr(updater, "_verify_health", lambda *_args: failure != "health")
    if failure == "dependencies":
        monkeypatch.setattr(updater, "_install_dependencies", lambda: (_ for _ in ()).throw(UpdateError("dependency install failed")))
    else:
        monkeypatch.setattr(updater, "_install_dependencies", lambda: None)
    rollbacks = []
    monkeypatch.setattr(updater, "_rollback", lambda *args: rollbacks.append(args) or True)
    with pytest.raises(UpdateError):
        updater.update()
    assert len(rollbacks) == 1
    assert updater.public_status()["rollback"] == "succeeded"


def test_rollback_failure_is_reported(updater: AutoUpdater, monkeypatch):
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "_git_preflight", lambda **kwargs: {
        "local": "a" * 40, "remote": "b" * 40, "latest": "2.0.0", "available": True,
    })
    monkeypatch.setattr(updater, "_stop_mode", lambda mode: None)
    monkeypatch.setattr(updater, "_git", lambda *args, **kwargs: "")
    monkeypatch.setattr(updater, "_install_dependencies", lambda: (_ for _ in ()).throw(UpdateError("boom")))
    monkeypatch.setattr(updater, "_rollback", lambda *args: False)
    with pytest.raises(UpdateError):
        updater.update()
    assert updater.public_status()["rollback"] == "failed"


def test_service_and_pinokio_modes_restart_only_their_owner(updater: AutoUpdater, monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "_run", lambda args, **kwargs: calls.append(tuple(args)) or subprocess.CompletedProcess(args, 0, "", ""))
    monkeypatch.setattr(updater, "_pterm", lambda action: calls.append(("pterm", action)))
    updater._start_mode("service")
    updater._start_mode("pinokio")
    assert calls == [("/bin/bash", "install_service.sh"), ("pterm", "start")]


def test_secrets_are_redacted():
    value = _redact({"hf_token": "hf_secret", "details": "Authorization: Bearer-abc"})
    assert value["hf_token"] == "[redacted]"
    assert "Bearer-abc" not in value["details"]


def test_next_daily_and_weekly_checks_are_future(updater: AutoUpdater):
    now = dt.datetime(2026, 7, 15, 10, tzinfo=dt.timezone.utc)
    updater.now = lambda: now
    daily = updater._next_regular({**updater.defaults, "frequency": "daily", "maintenance_hour": 2})
    weekly = updater._next_regular({**updater.defaults, "frequency": "weekly", "maintenance_hour": 2})
    assert daily > now
    assert weekly > daily


def test_managed_target_requires_all_fields(updater: AutoUpdater):
    with pytest.raises(UpdateError, match="all be provided"):
        updater.trigger_update(target_commit="a" * 40)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("unknown", "did not resolve"),
        ("not_on_main", "not an ancestor"),
        ("version_mismatch", "VERSION does not match"),
        ("rewritten_main", "history was rewritten"),
    ],
)
def test_managed_preflight_refuses_unattested_targets(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch, case: str, message: str
):
    target = "b" * 40
    main_tip = "c" * 40
    previous = "d" * 40
    if case == "rewritten_main":
        updater._write_status(last_remote_commit=previous)

    def fake_git(*args, **_kwargs):
        command = tuple(args)
        if command == ("remote", "get-url", "origin"):
            return updater.spec["expected_remote"]
        if command[:3] == ("symbolic-ref", "--quiet", "--short"):
            return "main"
        if command[:2] == ("status", "--porcelain") or command[:1] == ("fetch",):
            return ""
        if command == ("rev-parse", "HEAD"):
            return "a" * 40
        if command == ("rev-parse", "origin/main"):
            return main_tip
        if command == ("rev-parse", "--verify", f"{target}^{{commit}}"):
            return "e" * 40 if case == "unknown" else target
        if command == ("show", f"{target}:VERSION"):
            return "2.0.1" if case == "version_mismatch" else "2.0.0"
        raise AssertionError(command)

    def fake_run(args, **_kwargs):
        if "merge-base" not in args:
            raise AssertionError(args)
        if case == "rewritten_main" and args[-2:] == [previous, main_tip]:
            return subprocess.CompletedProcess(args, 1, "", "")
        if case == "not_on_main" and args[-2:] == [target, main_tip]:
            return subprocess.CompletedProcess(args, 1, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(updater, "_git", fake_git)
    monkeypatch.setattr(updater, "_run", fake_run)

    with pytest.raises(UpdateError, match=message):
        updater._git_preflight(target_commit=target, target_version="2.0.0")


def test_readiness_failure_remains_nonblocking_for_ordinary_updates(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "backend.auto_update.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    monkeypatch.setattr(updater, "_service_positively_stopped", lambda: False)

    assert updater.readiness_reasons() == []
    assert updater.readiness_reasons(fail_closed=True)


def test_generation_dependency_refresh_uses_voice_source_requirements(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    source = updater.root / "app" / "requirements-generation.txt"
    source.write_text("mlx-audio>=0.1\n")
    marker = updater.root / "conda_env" / "lib" / "python3.12" / "site-packages" / "mlx_audio"
    marker.mkdir(parents=True)
    updater.spec["generation_marker"] = "mlx_audio"
    calls = []
    monkeypatch.setattr(updater, "_pinokio_home", lambda: updater.root.parent.parent)
    monkeypatch.setattr(
        updater,
        "_run",
        lambda args, **_kwargs: calls.append([str(item) for item in args])
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    updater._install_dependencies()

    requirement_paths = [call[call.index("-r") + 1] for call in calls if "-r" in call]
    assert str(source) in requirement_paths
    assert not any(path.endswith("requirements-generation.lock.txt") for path in requirement_paths)


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "1.2.3.4", "1.2.3+build.1"])
def test_managed_target_requires_release_compatible_semver(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch, version: str
):
    monkeypatch.setattr(updater, "_spawn", lambda *_args: None)
    with pytest.raises(UpdateError, match="target_version is invalid"):
        updater.trigger_update(
            target_commit="a" * 40, target_version=version, operation_id="hub-op-1"
        )


def test_matching_managed_operation_is_adopted_without_duplicate_helper(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    spawned = []
    monkeypatch.setattr(
        updater, "_spawn",
        lambda *args: spawned.append(args) or SimpleNamespace(pid=os.getpid()),
    )

    request = {
        "target_commit": "a" * 40,
        "target_version": "2.0.0",
        "operation_id": "hub-op-1",
    }
    updater.trigger_update(**request)
    adopted = updater.trigger_update(**request)

    assert len(spawned) == 1
    assert adopted["managed_update"] == request


def test_concurrent_identical_managed_requests_admit_one_helper(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    request = {"target_commit": "a" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    original_read = updater._read_status
    barrier = threading.Barrier(2)
    reads = 0
    reads_lock = threading.Lock()
    spawned = []

    def synchronized_read():
        nonlocal reads
        with reads_lock:
            reads += 1
            wait = reads <= 2
        if wait:
            try:
                barrier.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                pass
        return original_read()

    monkeypatch.setattr(updater, "_read_status", synchronized_read)
    monkeypatch.setattr(
        updater, "_spawn",
        lambda *args: spawned.append(args) or SimpleNamespace(pid=os.getpid()),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _unused: updater.trigger_update(**request), range(2)))

    assert len(spawned) == 1
    assert all(result["managed_update"] == request for result in results)


def test_concurrent_conflicting_managed_requests_reject_one(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    first = {"target_commit": "a" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    second = {"target_commit": "b" * 40, "target_version": "2.0.0", "operation_id": "hub-op-2"}
    original_read = updater._read_status
    barrier = threading.Barrier(2)
    reads = 0
    reads_lock = threading.Lock()
    spawned = []

    def synchronized_read():
        nonlocal reads
        with reads_lock:
            reads += 1
            wait = reads <= 2
        if wait:
            try:
                barrier.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                pass
        return original_read()

    monkeypatch.setattr(updater, "_read_status", synchronized_read)
    monkeypatch.setattr(
        updater, "_spawn",
        lambda *args: spawned.append(args) or SimpleNamespace(pid=os.getpid()),
    )

    def trigger(request):
        try:
            return updater.trigger_update(**request)
        except UpdateError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(trigger, (first, second)))

    assert len(spawned) == 1
    assert sum(isinstance(result, UpdateError) for result in results) == 1


def test_completed_managed_target_does_not_hijack_ordinary_deferred_update(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    updater._write_status(
        managed_update={
            "target_commit": "a" * 40,
            "target_version": "2.0.0",
            "operation_id": "hub-op-1",
        },
        pending_manual=False,
    )
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: ["generation active"])
    updater.trigger_update(after_current=True)
    calls = []
    monkeypatch.setattr(updater, "update", lambda **kwargs: calls.append(kwargs) or {"state": "succeeded"})

    updater.scheduled()

    assert calls == [{"automatic": False}]


def test_dead_managed_operation_reinstalls_durable_recovery(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    request = {"target_commit": "a" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    updater._write_status(active_managed_update=request, pending_manual=True, managed_helper_pid=999_999)
    scheduled = []
    spawned = []
    monkeypatch.setattr(updater, "apply_scheduler", lambda **kwargs: scheduled.append(kwargs) or {"installed": True})
    monkeypatch.setattr(
        updater, "_spawn",
        lambda *args: spawned.append(args) or SimpleNamespace(pid=os.getpid()),
    )

    updater.trigger_update(**request)

    assert scheduled == [{"force_pending": True}]
    assert len(spawned) == 1


def test_resumed_managed_update_restarts_original_service_after_stop(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    request = {"target_commit": "b" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    updater._write_status(
        active_managed_update={**request, "run_mode": "service", "phase": "stopped"},
        pending_manual=True,
    )
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr(updater, "_git_preflight", lambda **_kwargs: {
        "local": request["target_commit"], "remote": request["target_commit"],
        "latest": request["target_version"], "available": False,
    })
    started = []
    verified = []
    monkeypatch.setattr(updater, "_install_dependencies", lambda: None)
    monkeypatch.setattr(updater, "_verify_import", lambda _version: None)
    monkeypatch.setattr(updater, "_start_mode", lambda mode: started.append(mode))
    monkeypatch.setattr(
        updater, "_verify_health", lambda mode, *_args: verified.append(mode) or True
    )

    updater.update(**request)

    assert started == ["service"]
    assert verified == ["service"]


@pytest.mark.parametrize("phase", ["stopped", "merged", "merged"], ids=[
    "after-merge-before-phase-write", "during-install", "after-install-before-import",
])
def test_target_checkout_recovery_replays_install_and_import_before_restart(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch, phase: str
):
    request = {"target_commit": "b" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    updater._write_status(
        active_managed_update={
            **request, "run_mode": "service", "phase": phase,
            "rollback_sha": "a" * 40, "rollback_version": "1.0.0",
        },
        pending_manual=True,
    )
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr(updater, "_git_preflight", lambda **_kwargs: {
        "local": request["target_commit"], "remote": request["target_commit"],
        "latest": request["target_version"], "available": False,
    })
    calls = []
    monkeypatch.setattr(updater, "_install_dependencies", lambda: calls.append("install"))
    monkeypatch.setattr(updater, "_verify_import", lambda _version: calls.append("import"))
    monkeypatch.setattr(updater, "_start_mode", lambda mode: calls.append(f"start:{mode}"))
    monkeypatch.setattr(updater, "_verify_health", lambda *_args: calls.append("health") or True)

    updater.update(**request)

    assert calls == ["install", "import", "start:service", "health"]


@pytest.mark.parametrize("outcome", ["no-op", "failure", "success"])
def test_managed_terminal_paths_clear_retry_and_preserve_regular_check(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch, outcome: str
):
    request = {"target_commit": "b" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    regular_check = "2030-01-01T00:00:00Z"
    _save(updater, "auto")
    updater._write_status(
        active_managed_update={**request, "run_mode": "stopped", "phase": "prepared"},
        pending_manual=True, next_retry="2026-08-15T10:00:00Z", next_check=regular_check,
    )
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    if outcome == "success":
        monkeypatch.setattr(updater, "_git_preflight", lambda **_kwargs: {
            "local": "a" * 40, "remote": request["target_commit"],
            "latest": request["target_version"], "available": True,
        })
        monkeypatch.setattr(updater, "_git", lambda *_args, **_kwargs: "")
        monkeypatch.setattr(updater, "_stop_mode", lambda _mode: None)
        monkeypatch.setattr(updater, "_install_dependencies", lambda: None)
        monkeypatch.setattr(updater, "_verify_import", lambda _version: None)
        monkeypatch.setattr(updater, "_start_mode", lambda _mode: None)
        monkeypatch.setattr(updater, "_verify_health", lambda *_args: True)
    else:
        monkeypatch.setattr(updater, "_git_preflight", lambda **_kwargs: {
            "local": request["target_commit"], "remote": request["target_commit"],
            "latest": request["target_version"], "available": False,
        })
        monkeypatch.setattr(updater, "_verify_health", lambda *_args: outcome == "no-op")

    if outcome == "failure":
        with pytest.raises(UpdateError):
            updater.update(**request)
    else:
        updater.update(**request)

    status = updater.public_status()
    assert status["next_retry"] is None
    assert status["next_check"] == regular_check
    monkeypatch.setattr(updater, "check", lambda: pytest.fail("terminal managed update must not trigger Auto work"))
    updater.scheduled()


def test_target_checkout_recovery_keeps_persisted_rollback_point(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    request = {"target_commit": "b" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    updater._write_status(
        active_managed_update={
            **request, "run_mode": "service", "phase": "merged",
            "rollback_sha": "a" * 40, "rollback_version": "1.0.0",
        },
        pending_manual=True,
    )
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr(updater, "_git_preflight", lambda **_kwargs: {
        "local": request["target_commit"], "remote": request["target_commit"],
        "latest": request["target_version"], "available": False,
    })
    monkeypatch.setattr(
        updater, "_install_dependencies", lambda: (_ for _ in ()).throw(UpdateError("install failed"))
    )
    rollbacks = []
    monkeypatch.setattr(updater, "_rollback", lambda *args: rollbacks.append(args) or True)

    with pytest.raises(UpdateError, match="install failed"):
        updater.update(**request)

    assert rollbacks == [("a" * 40, "b" * 40, "service", "1.0.0")]


def test_managed_launch_sets_prompt_retry_ahead_of_future_regular_check(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    request = {"target_commit": "a" * 40, "target_version": "2.0.0", "operation_id": "hub-op-1"}
    now = dt.datetime(2026, 8, 15, 10, tzinfo=dt.timezone.utc)
    updater.now = lambda: now
    updater._write_status(next_check="2030-01-01T00:00:00Z")
    monkeypatch.setattr(updater, "_spawn", lambda *_args: SimpleNamespace(pid=os.getpid()))

    updater.trigger_update(**request)

    assert _parse_iso(updater.public_status()["next_retry"]) <= now
    calls = []
    monkeypatch.setattr(updater, "update", lambda **kwargs: calls.append(kwargs) or {"state": "succeeded"})
    updater.scheduled()
    assert calls == [{"automatic": False, **request}]


def test_completed_managed_operation_remains_idempotent_beyond_eight_later_operations(
    updater: AutoUpdater, monkeypatch: pytest.MonkeyPatch
):
    history = [
        {
            "target_commit": f"{index:x}" * 40,
            "target_version": "2.0.0",
            "operation_id": f"hub-op-{index}",
            "result": "succeeded",
        }
        for index in range(9)
    ]
    updater._write_status(managed_operation_history=history)
    monkeypatch.setattr(updater, "_spawn", lambda *_args: pytest.fail("completed operation must be adopted"))

    result = updater.trigger_update(
        target_commit="0" * 40, target_version="2.0.0", operation_id="hub-op-0"
    )

    assert result["managed_update"] is None


def test_managed_target_only_merges_requested_sha(updater: AutoUpdater, monkeypatch):
    target = "b" * 40
    main_tip = "c" * 40
    calls = []

    def fake_git(*args, **_kwargs):
        command = tuple(args)
        calls.append(command)
        if command == ("remote", "get-url", "origin"):
            return updater.spec["expected_remote"]
        if command[:3] == ("symbolic-ref", "--quiet", "--short"):
            return "main"
        if command[:2] == ("status", "--porcelain") or command[:1] == ("fetch",):
            return ""
        if command == ("rev-parse", "HEAD"):
            return "a" * 40
        if command == ("rev-parse", "origin/main"):
            return main_tip
        if command == ("rev-parse", "--verify", f"{target}^{{commit}}"):
            return target
        if command == ("show", f"{target}:VERSION"):
            return "2.0.0"
        if command[:1] == ("merge",):
            return ""
        raise AssertionError(command)

    monkeypatch.setattr(updater, "_git", fake_git)
    monkeypatch.setattr(
        updater, "_run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: [])
    monkeypatch.setattr(updater, "active_mode", lambda: "stopped")
    monkeypatch.setattr(updater, "_stop_mode", lambda _mode: None)
    monkeypatch.setattr(updater, "_install_dependencies", lambda: None)
    monkeypatch.setattr(updater, "_verify_import", lambda _version: None)
    monkeypatch.setattr(updater, "_start_mode", lambda _mode: None)
    monkeypatch.setattr(updater, "_verify_health", lambda *_args: True)

    updater.update(target_commit=target, target_version="2.0.0", operation_id="hub-op-1")

    assert ("merge", "--ff-only", target) in calls
    assert ("merge", "--ff-only", "origin/main") not in calls


def test_busy_managed_update_keeps_durable_target(updater: AutoUpdater, monkeypatch):
    monkeypatch.setattr(updater, "readiness_reasons", lambda **_kwargs: ["generation active"])

    with pytest.raises(UpdateDeferred):
        updater.update(
            target_commit="a" * 40,
            target_version="2.0.0",
            operation_id="hub-op-1",
        )

    status = updater.public_status()
    assert status["pending_manual"] is True
    assert status["managed_update"] == {
        "target_commit": "a" * 40,
        "target_version": "2.0.0",
        "operation_id": "hub-op-1",
    }


def test_public_status_redacts_and_bounds_details(updater: AutoUpdater):
    updater._write_status(
        details=[f"token=secret-{index}" for index in range(20)],
        last_update_result="Authorization: Bearer super-secret",
    )

    status = updater.public_status()

    assert len(status["details"]) <= 8
    assert "super-secret" not in status["last_update_result"]
    assert all("secret-" not in item for item in status["details"])
