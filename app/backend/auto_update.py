"""Safe, opt-in application updates for the KH Studio family.

The web server only starts this module in a detached helper process.  That
helper can therefore stop and restart the server without killing itself.  All
commands are fixed argument arrays; user settings never become shell input.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Callable, Optional
from urllib.request import Request, urlopen


MODES = {"off", "notify", "auto"}
FREQUENCIES = {"daily", "weekly"}
STATES = {"idle", "checking", "available", "deferred", "updating",
          "restarting", "succeeded", "failed"}
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
OPERATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SECRET_RE = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)\s*[:=]\s*(?:bearer\s+)?([^\s,;]+)")
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
RUN_MODES = {"service", "pinokio", "stopped"}
MANAGED_PHASES = {"prepared", "stopping", "stopped", "merged", "verified", "restarting"}


class UpdateError(RuntimeError):
    """An expected, actionable updater refusal or failure."""


class UpdateDeferred(UpdateError):
    """Work is active, so the update must be retried later."""


class _UpdateBusy(UpdateError):
    """The updater lock is already held by another update process."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: Optional[dt.datetime] = None) -> str:
    return (value or _utc_now()).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {k: ("[redacted]" if re.search(r"token|secret|password|key", k, re.I)
                    else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_RE.sub(lambda m: f"{m.group(1)}=[redacted]", value)
    return value


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise UpdateError(f"Unsafe symlinked updater directory: {path.parent}")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_redact(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


class AutoUpdater:
    def __init__(self, spec: dict, readiness: Optional[Callable[[], list[str]]] = None,
                 *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 now: Callable[[], dt.datetime] = _utc_now) -> None:
        self.spec = dict(spec)
        self._configured_root = Path(self.spec["root"])
        self.root = self._configured_root.resolve()
        self.readiness = readiness
        self.runner = runner
        self.now = now
        self.state_dir = self.root / "auto_update"
        self.config_path = self.state_dir / "config.json"
        self.status_path = self.state_dir / "status.json"
        self.lock_path = self.state_dir / "update.lock"
        self.admission_lock_path = self.state_dir / "admission.lock"
        self.log_dir = self.root / "logs" / "auto_update"
        self.agent_label = f"com.kh.{self.spec['slug']}.updater"
        self.agent_path = Path.home() / "Library" / "LaunchAgents" / f"{self.agent_label}.plist"
        self.wrapper_path = self.state_dir / f"{self.spec['slug']}-updater.sh"
        self._thread_lock = threading.Lock()
        self._admission_thread_lock = threading.Lock()
        self._validate_spec()
        self.log = self._make_logger()

    def _validate_spec(self) -> None:
        # Keep the configured root itself real, but support Git's standard
        # linked-worktree gitfile ("gitdir: <worktree metadata directory>").
        # Resolving first would otherwise hide a symlinked configured root.
        git_marker = self.root / ".git"
        if self._configured_root.is_symlink() or git_marker.is_symlink():
            raise UpdateError("Updater root must be a real Git checkout.")
        if not git_marker.is_dir():
            try:
                lines = git_marker.read_text(encoding="utf-8").splitlines()
            except OSError:
                raise UpdateError("Updater root must be a real Git checkout.") from None
            if len(lines) != 1 or not lines[0].startswith("gitdir: "):
                raise UpdateError("Updater root must be a real Git checkout.")
            gitdir_text = lines[0][len("gitdir: "):]
            if not gitdir_text or "\x00" in gitdir_text:
                raise UpdateError("Updater root must be a real Git checkout.")
            gitdir = Path(gitdir_text)
            if not gitdir.is_absolute():
                gitdir = git_marker.parent / gitdir
            if not gitdir.is_dir():
                raise UpdateError("Updater root must be a real Git checkout.")
        branch = self.spec.get("branch", "main")
        if not BRANCH_RE.fullmatch(branch) or branch.startswith("-") or ".." in branch:
            raise UpdateError("Unsafe configured Git branch.")
        remote = self.spec.get("expected_remote", "")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", remote):
            raise UpdateError("Unsafe expected Git remote.")
        port = int(self.spec["port"])
        if not 1024 <= port <= 65535:
            raise UpdateError("Unsafe app port.")

    def _make_logger(self) -> logging.Logger:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(f"kh-auto-update.{self.spec['slug']}.{id(self)}")
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(self.log_dir / "updater.log", maxBytes=1_000_000,
                                      backupCount=4, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        return logger

    @property
    def defaults(self) -> dict:
        return {
            "mode": "off",
            "frequency": "daily",
            "maintenance_hour": int(self.spec["default_hour"]),
            "idle_only": True,
            "weekday": int(self.spec.get("default_weekday", 6)),
        }

    def _load_json(self, path: Path, fallback: dict) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else dict(fallback)
        except (OSError, ValueError):
            return dict(fallback)

    def settings(self) -> dict:
        data = {**self.defaults, **self._load_json(self.config_path, {})}
        if data.get("mode") not in MODES:
            data["mode"] = "off"
        if data.get("frequency") not in FREQUENCIES:
            data["frequency"] = "daily"
        data["maintenance_hour"] = max(0, min(23, int(data.get("maintenance_hour", self.defaults["maintenance_hour"]))))
        data["idle_only"] = bool(data.get("idle_only", True))
        return data

    def _read_status(self) -> dict:
        return self._load_json(self.status_path, {
            "state": "idle", "last_checked": None, "latest_version": None,
            "next_check": None, "last_update_result": None, "defer_reason": None,
            "details": [], "rollback": None, "pending_manual": False,
            "active_managed_update": None, "managed_operation_history": [],
        })

    def _write_status(self, **changes: object) -> dict:
        status = self._read_status()
        status.update(_redact(changes))
        state = status.get("state")
        if state not in STATES:
            status["state"] = "failed"
        _atomic_json(self.status_path, status)
        return status

    def installed_version(self) -> str:
        try:
            return (self.root / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"

    def _version_matches(self, actual: object, expected: str) -> bool:
        value = str(actual or "")
        return value == expected or (
            bool(self.spec.get("allow_build_suffix")) and value.startswith(expected + ".")
        )

    def _managed_request(self, *, target_commit: Optional[str] = None,
                         target_version: Optional[str] = None,
                         operation_id: Optional[str] = None) -> Optional[dict]:
        values = (target_commit, target_version, operation_id)
        if not any(value is not None for value in values):
            return None
        if not all(isinstance(value, str) and value for value in values):
            raise UpdateError("Managed update target_commit, target_version, and operation_id must all be provided.")
        target_commit, target_version, operation_id = (str(value) for value in values)
        if not COMMIT_RE.fullmatch(target_commit):
            raise UpdateError("Managed target_commit must be a full lowercase Git commit SHA.")
        if not VERSION_RE.fullmatch(target_version):
            raise UpdateError("Managed target_version is invalid.")
        if not OPERATION_RE.fullmatch(operation_id):
            raise UpdateError("Managed operation_id is invalid.")
        return {
            "target_commit": target_commit,
            "target_version": target_version,
            "operation_id": operation_id,
        }

    def _active_managed_state(self, status: Optional[dict] = None) -> Optional[dict]:
        value = (status or self._read_status()).get("active_managed_update")
        if not isinstance(value, dict):
            return None
        try:
            request = self._managed_request(
                target_commit=value.get("target_commit"),
                target_version=value.get("target_version"),
                operation_id=value.get("operation_id"),
            )
        except UpdateError:
            return None
        if not request:
            return None
        mode = value.get("run_mode")
        phase = value.get("phase")
        rollback_sha = value.get("rollback_sha")
        rollback_version = value.get("rollback_version")
        return {
            **request,
            **({"run_mode": mode} if mode in RUN_MODES else {}),
            **({"phase": phase} if phase in MANAGED_PHASES else {}),
            **({"rollback_sha": rollback_sha} if isinstance(rollback_sha, str) and COMMIT_RE.fullmatch(rollback_sha) else {}),
            **({"rollback_version": rollback_version} if isinstance(rollback_version, str) and VERSION_RE.fullmatch(rollback_version) else {}),
        }

    def _active_managed_request(self, status: Optional[dict] = None) -> Optional[dict]:
        state = self._active_managed_state(status)
        return ({key: state[key] for key in ("target_commit", "target_version", "operation_id")}
                if state else None)

    def _managed_history(self, status: Optional[dict] = None) -> list[dict]:
        value = (status or self._read_status()).get("managed_operation_history")
        if not isinstance(value, list):
            return []
        history = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                request = self._managed_request(
                    target_commit=item.get("target_commit"), target_version=item.get("target_version"),
                    operation_id=item.get("operation_id"),
                )
            except UpdateError:
                continue
            if request:
                history.append({**request, "result": str(item.get("result") or "unknown")[:32]})
        return history

    def _complete_managed_changes(self, managed: Optional[dict], result: str) -> dict:
        if not managed:
            return {}
        history = [item for item in self._managed_history()
                   if item["operation_id"] != managed["operation_id"]]
        history.append({**managed, "result": result})
        return {
            "active_managed_update": None,
            "managed_helper_pid": None,
            "managed_operation_history": history,
            # Drop the legacy active-state field when this version writes status.
            "managed_update": None,
        }

    def release_notes_url(self) -> str:
        return self.spec["expected_remote"][:-4] + "/blob/main/CHANGELOG.md"

    def public_status(self) -> dict:
        status = self._read_status()
        settings = self.settings()
        latest = status.get("latest_version")
        installed = self.installed_version()
        details = status.get("details") if isinstance(status.get("details"), list) else []
        scheduler = self.scheduler_status()
        return {
            "state": status.get("state") if status.get("state") in STATES else "failed",
            "last_checked": str(status.get("last_checked") or "")[:80] or None,
            "latest_version": str(latest or "")[:80] or None,
            "next_check": str(status.get("next_check") or "")[:80] or None,
            "next_retry": str(status.get("next_retry") or "")[:80] or None,
            "last_update_result": str(_redact(str(status.get("last_update_result") or "")))[:240] or None,
            "defer_reason": str(_redact(str(status.get("defer_reason") or "")))[:480] or None,
            "details": [str(_redact(str(value)))[:240] for value in details[:8]],
            "rollback": str(status.get("rollback") or "")[:32] or None,
            "pending_manual": bool(status.get("pending_manual")),
            "managed_update": self._active_managed_request(status),
            "capabilities": {"managed_exact_commit": True, "dependency_convergence": 1},
            "settings": settings,
            "installed_version": installed,
            "update_available": bool(latest and latest != installed),
            "scheduler": {
                "installed": bool(scheduler.get("installed")),
                "supported": bool(scheduler.get("supported")),
                "label": str(scheduler.get("label") or "")[:160],
            },
            "release_notes_url": self.release_notes_url(),
        }

    def _next_regular(self, settings: Optional[dict] = None) -> dt.datetime:
        cfg = settings or self.settings()
        now = self.now().astimezone()
        candidate = now.replace(hour=cfg["maintenance_hour"], minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += dt.timedelta(days=1)
        if cfg["frequency"] == "weekly":
            target = int(cfg.get("weekday", 6)) % 7
            candidate += dt.timedelta(days=(target - candidate.weekday()) % 7)
        return candidate.astimezone(dt.timezone.utc)

    def save_settings(self, payload: dict) -> dict:
        current = self.settings()
        mode = payload.get("mode", current["mode"])
        frequency = payload.get("frequency", current["frequency"])
        hour = payload.get("maintenance_hour", current["maintenance_hour"])
        idle_only = payload.get("idle_only", current["idle_only"])
        if mode not in MODES:
            raise UpdateError("Mode must be off, notify, or auto.")
        if frequency not in FREQUENCIES:
            raise UpdateError("Frequency must be daily or weekly.")
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise UpdateError("Maintenance hour must be from 0 through 23.")
        if not isinstance(idle_only, bool):
            raise UpdateError("Idle-only must be true or false.")
        saved = {"mode": mode, "frequency": frequency, "maintenance_hour": hour,
                 "idle_only": idle_only, "weekday": int(current.get("weekday", 6))}
        _atomic_json(self.config_path, saved)
        next_check = None if mode == "off" else _iso(self._next_regular(saved))
        self._write_status(next_check=next_check, defer_reason=None,
                           pending_manual=False, state="idle")
        applied = self.apply_scheduler()
        if mode != "off" and not applied["installed"]:
            raise UpdateError("Settings saved, but the automatic-update schedule could not be installed.")
        if mode == "off" and applied["installed"]:
            raise UpdateError("Settings saved, but the automatic-update schedule is still loaded.")
        return self.public_status()

    def _plist(self) -> bytes:
        payload = {
            "Label": self.agent_label,
            "ProgramArguments": [str(self.wrapper_path)],
            "WorkingDirectory": str(self.root / "app"),
            "RunAtLoad": True,
            "StartInterval": 900,
            "ProcessType": "Background",
            "ThrottleInterval": 60,
            "StandardOutPath": str(self.log_dir / "launchd.log"),
            "StandardErrorPath": str(self.log_dir / "launchd.err.log"),
            "EnvironmentVariables": {
                "PATH": f"{self._pinokio_home() / 'bin/miniforge/bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
                "PYTHONUNBUFFERED": "1",
            },
        }
        return plistlib.dumps(payload, sort_keys=True)

    def _write_wrapper(self) -> None:
        python = self.root / "conda_env" / "bin" / "python"
        if not python.is_file():
            python = Path(sys.executable)
        if self.state_dir.is_symlink() or self.wrapper_path.is_symlink():
            raise UpdateError("Refusing a symlinked updater wrapper path.")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "#!/bin/sh\n"
            f"exec {shlex.quote(str(python))} -m backend.auto_update --scheduled\n"
        )
        temporary = self.wrapper_path.with_name(
            f".{self.wrapper_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o700)
            os.replace(temporary, self.wrapper_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def _launchctl(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        return self.runner(["/bin/launchctl", *args], text=True, capture_output=True,
                           timeout=30, check=check)

    def apply_scheduler(self, *, force_pending: bool = False) -> dict:
        self.agent_path.parent.mkdir(parents=True, exist_ok=True)
        uid = os.getuid()
        domain = f"gui/{uid}"
        self._launchctl("bootout", f"{domain}/{self.agent_label}")
        should_install = self.settings()["mode"] != "off" or force_pending
        if not should_install:
            with contextlib.suppress(FileNotFoundError):
                self.agent_path.unlink()
            with contextlib.suppress(FileNotFoundError):
                self.wrapper_path.unlink()
            return self.scheduler_status()
        if self.agent_path.exists() and self.agent_path.is_symlink():
            raise UpdateError("Refusing a symlinked LaunchAgent file.")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._write_wrapper()
        tmp = self.agent_path.with_name(f".{self.agent_path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(self._plist())
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.agent_path)
        result = self._launchctl("bootstrap", domain, str(self.agent_path))
        if result.returncode:
            raise UpdateError(f"launchd rejected the updater schedule: {result.stderr.strip()}")
        return self.scheduler_status()

    def scheduler_status(self) -> dict:
        if sys.platform != "darwin":
            return {"installed": False, "label": self.agent_label, "supported": False}
        result = self._launchctl("print", f"gui/{os.getuid()}/{self.agent_label}")
        return {"installed": result.returncode == 0, "label": self.agent_label,
                "supported": True, "plist": str(self.agent_path)}

    def _run(self, args: list[str], *, cwd: Optional[Path] = None,
             timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
        safe_args = [str(a) for a in args]
        self.log.info("run %s", " ".join(safe_args))
        result = self.runner(safe_args, cwd=str(cwd or self.root), text=True,
                             capture_output=True, timeout=timeout)
        if check and result.returncode:
            message = (result.stderr or result.stdout or "command failed").strip()
            raise UpdateError(f"{safe_args[0]} failed: {_redact(message)}")
        return result

    def _git(self, *args: str, timeout: int = 120, check: bool = True) -> str:
        result = self._run(["/usr/bin/git", *args], timeout=timeout, check=check)
        return result.stdout.rstrip("\r\n")

    def _pinokio_home(self) -> Path:
        # Every supported checkout is PINOKIO_HOME/api/<app>. Resolve from the
        # fixed repository location instead of trusting environment input.
        home = self.root.parent.parent.resolve()
        if self.root.parent != home / "api":
            raise UpdateError("Repository is outside PINOKIO_HOME/api.")
        return home

    def _git_preflight(self, *, fetch: bool = True, target_commit: Optional[str] = None,
                       target_version: Optional[str] = None) -> dict:
        if self._git("remote", "get-url", "origin") != self.spec["expected_remote"]:
            raise UpdateError("Unexpected Git remote. Repair origin before updating.")
        branch = self._git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if branch != self.spec.get("branch", "main"):
            raise UpdateError("Updater requires the configured main branch (not detached HEAD).")
        dirty = self._git("status", "--porcelain", "--untracked-files=normal")
        if dirty:
            paths = [line[3:].strip() for line in dirty.splitlines() if line.strip()]
            preview = ", ".join(paths[:5])
            if len(paths) > 5:
                preview += f", and {len(paths) - 5} more"
            detail = f": {preview}" if preview else ""
            raise UpdateError(
                f"Working tree has local changes{detail}. Commit or remove them before updating."
            )
        if fetch:
            self._git("fetch", "--prune", "origin", self.spec.get("branch", "main"), timeout=180)
        local = self._git("rev-parse", "HEAD")
        remote_ref = f"origin/{self.spec.get('branch', 'main')}"
        main_tip = self._git("rev-parse", remote_ref)
        previous = self._read_status().get("last_remote_commit")
        if previous and previous != main_tip:
            if self._run(["/usr/bin/git", "merge-base", "--is-ancestor", str(previous), main_tip],
                         check=False).returncode:
                raise UpdateError("Remote history was rewritten. Automatic update refused.")
        managed = target_commit is not None
        remote = main_tip
        if managed:
            if target_version is None:
                raise UpdateError("Managed target version is required.")
            remote = self._git("rev-parse", "--verify", f"{target_commit}^{{commit}}")
            if remote != target_commit:
                raise UpdateError("Managed target did not resolve to the requested commit.")
            if self._run(["/usr/bin/git", "merge-base", "--is-ancestor", remote, main_tip],
                         check=False).returncode:
                raise UpdateError("Managed target is not an ancestor of origin/main.")
        if local != remote:
            if self._run(["/usr/bin/git", "merge-base", "--is-ancestor", local, remote],
                         check=False).returncode:
                raise UpdateError("Local and remote history diverged. Fast-forward update refused.")
        latest = self._git("show", f"{remote}:VERSION").strip()
        if not VERSION_RE.fullmatch(latest):
            raise UpdateError("Published VERSION metadata is invalid.")
        if managed and latest != target_version:
            raise UpdateError("Managed target VERSION does not match target_version.")
        return {"local": local, "remote": remote, "main_tip": main_tip, "latest": latest,
                "available": local != remote}

    def check(self) -> dict:
        self._write_status(state="checking", defer_reason=None, details=[])
        try:
            result = self._git_preflight(fetch=True)
            state = "available" if result["available"] else "succeeded"
            self._write_status(state=state, last_checked=_iso(self.now()),
                               latest_version=result["latest"],
                               last_remote_commit=result["remote"],
                               last_update_result="Update available" if result["available"] else "Already up to date",
                               details=["Git remote, branch, worktree, and fast-forward safety checks passed."])
        except Exception as exc:
            self._write_status(state="failed", last_checked=_iso(self.now()),
                               last_update_result="Update check failed",
                               details=[str(_redact(str(exc)))])
            raise
        return self.public_status()

    def trigger_check(self) -> dict:
        if not self._thread_lock.acquire(blocking=False):
            raise UpdateError("An update check is already running.")
        def worker() -> None:
            try:
                self.check()
            except Exception:
                self.log.exception("update check failed")
            finally:
                self._thread_lock.release()
        threading.Thread(target=worker, daemon=True).start()
        return self.public_status()

    def readiness_reasons(self, *, fail_closed: bool = False) -> list[str]:
        if self.readiness is not None:
            return [str(x) for x in self.readiness() if x]
        url = f"http://127.0.0.1:{int(self.spec['port'])}/api/auto-update/readiness"
        try:
            with urlopen(Request(url, headers={"User-Agent": "KH-Studio-Updater/1"}), timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("reasons"), list):
                raise UpdateError("The readiness endpoint returned an invalid response.")
            return [str(x) for x in data.get("reasons", []) if x]
        except Exception:
            if not fail_closed:
                # Preserve Voice Studio's established ordinary Off/Notify/Auto
                # behavior: an unavailable readiness endpoint is non-blocking.
                return []
            # A failed health/readiness request is not proof that the app owns no
            # work: it may be alive-but-hung while an inference thread is still
            # active. Only allow an update when launchd says the service is not
            # loaded AND nothing is accepting connections on the app port.
            if self._service_positively_stopped():
                return []
            return [
                "the update safety check is unavailable and Voice Studio is not confirmed stopped"
            ]

    def readiness_status(self) -> dict:
        reasons = self.readiness_reasons()
        return {"idle": not reasons, "reasons": reasons}

    def _notify(self, title: str, message: str) -> None:
        clean_title = str(_redact(title))[:100]
        clean_message = str(_redact(message))[:240]
        script = 'display notification "' + clean_message.replace("\\", "\\\\").replace('"', '\\"') + \
                 '" with title "' + clean_title.replace("\\", "\\\\").replace('"', '\\"') + '"'
        self._run(["/usr/bin/osascript", "-e", script], timeout=15, check=False)

    @contextlib.contextmanager
    def _exclusive_lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise _UpdateBusy("Another update is already running.") from exc
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def apply_scheduler_if_idle(self) -> bool:
        """Reconcile launchd while holding the updater lock for the whole change."""
        try:
            with self._exclusive_lock():
                self.apply_scheduler()
        except _UpdateBusy:
            return False
        return True

    @contextlib.contextmanager
    def _admission_lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self._admission_thread_lock:
            handle = open(self.admission_lock_path, "a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    def _update_is_running(self) -> bool:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _managed_helper_alive(self, status: dict) -> bool:
        if self._update_is_running():
            return True
        pid = status.get("managed_helper_pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _health(self, expected: str, expected_commit: Optional[str] = None, *, timeout: int = 90) -> bool:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{int(self.spec['port'])}/api/health"
        while time.monotonic() < deadline:
            try:
                with urlopen(url, timeout=3) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if (data.get("ok") and self._version_matches(data.get("app_version"), expected)
                        and (expected_commit is None or data.get("app_commit") == expected_commit)):
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def _service_loaded(self) -> bool:
        label = self.spec.get("server_label")
        if not label:
            return False
        return self._launchctl("print", f"gui/{os.getuid()}/{label}").returncode == 0

    def _port_accepting_connections(self) -> bool:
        try:
            with socket.create_connection(
                ("127.0.0.1", int(self.spec["port"])), timeout=0.75
            ):
                return True
        except OSError:
            return False

    def _service_positively_stopped(self) -> bool:
        """Prove the updater is not looking at an unresponsive live service."""
        try:
            return not self._service_loaded() and not self._port_accepting_connections()
        except Exception:
            # An unavailable launchd/process-state check is uncertainty, not
            # evidence that it is safe to stop an app and replace its files.
            return False

    def _health_alive(self) -> bool:
        try:
            with urlopen(f"http://127.0.0.1:{int(self.spec['port'])}/api/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def active_mode(self) -> str:
        if (self.root / "service" / ".installed").exists() or self._service_loaded():
            return "service"
        if self._health_alive():
            return "pinokio"
        return "stopped"

    def _pterm(self, action: str) -> None:
        home = self._pinokio_home()
        node = home / "bin" / "miniforge" / "bin" / "node"
        cli = home / "bin" / "npm" / "lib" / "node_modules" / "pterm" / "index.js"
        if not node.is_file() or not cli.is_file():
            raise UpdateError("Pinokio command helper is unavailable; use Repair in Pinokio.")
        ref = f"pinokio://127.0.0.1:42000/api/{self.root.name}"
        self._run([str(node), str(cli), action, "start.js", "--ref", ref], timeout=90)

    def _stop_mode(self, mode: str) -> None:
        if mode == "service":
            domain = f"gui/{os.getuid()}"
            for label in (self.spec.get("watchdog_label"), self.spec.get("server_label")):
                if label:
                    self._launchctl("bootout", f"{domain}/{label}")
        elif mode == "pinokio":
            self._pterm("stop")
        deadline = time.monotonic() + 30
        while self._health_alive() and time.monotonic() < deadline:
            time.sleep(1)
        if self._health_alive():
            raise UpdateError("The app did not stop cleanly; no files were changed.")

    def _start_mode(self, mode: str) -> None:
        if mode == "service":
            self._run(["/bin/bash", "install_service.sh"], timeout=120)
        elif mode == "pinokio":
            self._pterm("start")

    def _python(self) -> Path:
        candidate = self.root / "conda_env" / "bin" / "python"
        if not candidate.is_file():
            raise UpdateError("The app environment is not installed.")
        return candidate

    def _install_dependencies(self) -> None:
        python = self._python()
        module = self.root / "app" / "backend" / "dependency_convergence.py"
        if not module.is_file():
            raise UpdateError("Dependency convergence command is unavailable.")
        self._run(
            [str(python), "-m", "backend.dependency_convergence", "all-installed"],
            cwd=self.root / "app", timeout=1800,
        )

    def _restore_rollback_dependencies(self) -> None:
        """Restore an older rollback tree that predates dependency convergence."""
        python = self._python()
        base = self.root / "app" / "requirements.txt"
        if not base.is_file():
            raise UpdateError("Base requirements file is missing.")
        prefix = [str(python), "-m", "pip", "install"]
        self._run([*prefix, "-r", str(base)], cwd=self.root / "app", timeout=1200)
        marker = self.spec.get("generation_marker")
        generation = self.root / "app" / self.spec.get(
            "generation_requirements", "requirements-generation.txt"
        )
        if marker and generation.is_file() and any((self.root / "conda_env" / "lib").glob(f"python*/site-packages/{marker}")):
            self._run([*prefix, "-r", str(generation)], cwd=self.root / "app", timeout=1800)

    def _verify_import(self, expected: str) -> None:
        module = self.spec.get("verify_module", "backend.main")
        allow_suffix = bool(self.spec.get("allow_build_suffix"))
        code = ("import importlib; m=importlib.import_module(" + repr(module) + "); "
                "v=str(getattr(m,'APP_VERSION','')); expected=" + repr(expected) + "; "
                "assert v==expected or (" + repr(allow_suffix) + " and v.startswith(expected+'.')), (v,expected); "
                "print('UPDATE_VERIFY_OK')")
        self._run([str(self._python()), "-c", code], cwd=self.root / "app", timeout=180)

    def _temporary_health(self, expected: str, expected_commit: Optional[str] = None) -> bool:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        process = subprocess.Popen(
            [str(self._python()), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(self.root / "app"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                        data = json.loads(response.read().decode("utf-8"))
                    return bool(data.get("ok") and self._version_matches(data.get("app_version"), expected)
                                and (expected_commit is None or data.get("app_commit") == expected_commit))
                except Exception:
                    time.sleep(1)
            return False
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _verify_health(self, mode: str, expected: str, expected_commit: Optional[str] = None) -> bool:
        return (self._temporary_health(expected, expected_commit) if mode == "stopped"
                else self._health(expected, expected_commit))

    def _hide_machine_environment_for_rollback(
        self, old_sha: str, new_sha: str,
    ) -> Optional[Path]:
        """Move machine state aside only while crossing back to a tracked template."""
        if self._git("ls-tree", "--name-only", new_sha, "--", "ENVIRONMENT"):
            return None
        if self._git("ls-tree", "--name-only", old_sha, "--", "ENVIRONMENT") != "ENVIRONMENT":
            return None
        environment = self.root / "ENVIRONMENT"
        try:
            info = environment.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise UpdateError("Refusing rollback with a symlinked ENVIRONMENT file.")
        if not stat.S_ISREG(info.st_mode):
            raise UpdateError("Refusing rollback with a non-file ENVIRONMENT path.")

        backup = self.root / (
            f".ENVIRONMENT.rollback.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(backup, flags, 0o600)
        os.close(fd)
        reservation = backup.lstat()
        try:
            os.replace(environment, backup)
            if not stat.S_ISREG(backup.lstat().st_mode):
                os.replace(backup, environment)
                raise UpdateError("ENVIRONMENT changed during rollback preparation.")
        except Exception as exc:
            try:
                backup_info = backup.lstat()
            except FileNotFoundError:
                backup_info = None
            if backup_info is not None and not os.path.samestat(reservation, backup_info):
                if environment.exists() or environment.is_symlink():
                    raise UpdateError(
                        f"Machine ENVIRONMENT is retained at {backup}; manual restore required."
                    ) from exc
                try:
                    os.replace(backup, environment)
                except OSError as restore_exc:
                    raise UpdateError(
                        f"Machine ENVIRONMENT is retained at {backup}; manual restore required."
                    ) from restore_exc
            elif backup_info is not None:
                backup.unlink()
            raise
        return backup

    def _restore_machine_environment_after_rollback(self, backup: Path) -> None:
        if not stat.S_ISREG(backup.lstat().st_mode):
            raise UpdateError(f"Unsafe rollback backup retained at {backup}.")
        try:
            os.replace(backup, self.root / "ENVIRONMENT")
        except OSError as exc:
            raise UpdateError(
                f"Machine ENVIRONMENT is retained at {backup}; manual restore required."
            ) from exc

    def _rollback(self, old_sha: str, new_sha: str, mode: str, old_version: str) -> bool:
        try:
            self._stop_mode(mode)
            if self._git("rev-parse", "HEAD") != new_sha:
                raise UpdateError("Repository changed during rollback; manual repair required.")
            if self._git("status", "--porcelain", "--untracked-files=normal"):
                raise UpdateError("Worktree changed during rollback; manual repair required.")
            # Move only the updater-applied clean tree back. This is deliberately
            # not `git reset --hard`, and it runs only after proving no user edit
            # exists in the worktree.
            environment_backup = self._hide_machine_environment_for_rollback(old_sha, new_sha)
            try:
                self._git("read-tree", "--reset", "-u", old_sha)
            finally:
                if environment_backup is not None:
                    self._restore_machine_environment_after_rollback(environment_backup)
            self._git("update-ref", "refs/heads/main", old_sha, new_sha)
            module = self.root / "app" / "backend" / "dependency_convergence.py"
            if module.is_file():
                self._install_dependencies()
            else:
                self._restore_rollback_dependencies()
            self._verify_import(old_version)
            self._start_mode(mode)
            return self._verify_health(mode, old_version, old_sha)
        except Exception:
            self.log.exception("rollback failed")
            return False

    def update(self, *, automatic: bool = False, target_commit: Optional[str] = None,
               target_version: Optional[str] = None, operation_id: Optional[str] = None) -> dict:
        managed = self._managed_request(target_commit=target_commit, target_version=target_version,
                                        operation_id=operation_id)
        with self._exclusive_lock():
            old_sha = ""
            new_sha = ""
            old_version = self.installed_version()
            mode = self.active_mode()
            managed_state = None
            try:
                if managed:
                    # A trigger holds this lock through spawn and PID persistence;
                    # wait for that handoff before the helper writes updater state.
                    with self._admission_lock():
                        active = self._active_managed_state()
                        if active and self._active_managed_request() == managed:
                            mode = active.get("run_mode", mode)
                            phase = active.get("phase", "prepared")
                            rollback = {
                                key: active[key] for key in ("rollback_sha", "rollback_version")
                                if key in active
                            }
                        else:
                            phase = "prepared"
                            rollback = {}
                        managed_state = {**managed, **rollback, "run_mode": mode, "phase": phase}
                        self._write_status(active_managed_update=managed_state, managed_update=None,
                                           pending_manual=True)
                reasons = (self.readiness_reasons(fail_closed=True) if managed
                           else self.readiness_reasons())
                if reasons:
                    reason = "; ".join(reasons)
                    self._write_status(state="deferred", defer_reason=reason,
                                       last_update_result="Update deferred",
                                       next_retry=_iso(self.now() + dt.timedelta(minutes=15)),
                                       pending_manual=bool(managed) or bool(self._read_status().get("pending_manual")))
                    if self._read_status().get("pending_manual"):
                        self.apply_scheduler(force_pending=True)
                    self._notify(f"{self.spec['title']} update deferred", reason)
                    raise UpdateDeferred(reason)
                if shutil.disk_usage(self.root).free < int(self.spec.get("min_free_bytes", MIN_FREE_BYTES)):
                    raise UpdateError("Not enough free disk space for a safe update and rollback.")
                preflight = self._git_preflight(fetch=True, target_commit=target_commit,
                                                 target_version=target_version)
                old_sha = preflight["local"]
                new_sha = preflight["remote"]
                if managed and managed_state.get("rollback_sha"):
                    old_sha = managed_state["rollback_sha"]
                    old_version = managed_state.get("rollback_version", old_version)
                elif managed and preflight["available"]:
                    # Preserve a rollback point before the app is stopped or its
                    # worktree changes, so a post-merge recovery can still fail safe.
                    managed_state.update(rollback_sha=old_sha, rollback_version=old_version)
                    self._write_status(active_managed_update=managed_state)
                if not preflight["available"]:
                    if managed and managed_state["phase"] in {"stopping", "stopped", "merged"}:
                        # A matching checkout only proves the merge happened. Replay
                        # these idempotent checks until their durable phase says done.
                        self._install_dependencies()
                        self._verify_import(preflight["latest"])
                        managed_state["phase"] = "verified"
                        self._write_status(active_managed_update=managed_state)
                    if managed and managed_state["phase"] in {"stopping", "stopped", "merged", "verified", "restarting"} and mode != "stopped":
                        managed_state["phase"] = "restarting"
                        self._write_status(active_managed_update=managed_state, state="restarting")
                        self._start_mode(mode)
                    if managed and not self._verify_health(mode, preflight["latest"], new_sha):
                        raise UpdateError("The loaded app does not attest to the requested commit and version.")
                    self._write_status(state="succeeded", latest_version=preflight["latest"],
                                       last_checked=_iso(self.now()), last_update_result="Already up to date",
                                       defer_reason=None, pending_manual=False, next_retry=None,
                                       **self._complete_managed_changes(managed, "succeeded"))
                    if self.settings()["mode"] == "off":
                        self.apply_scheduler()
                    return self.public_status()
                self._write_status(state="updating", latest_version=preflight["latest"],
                                   last_checked=_iso(self.now()), defer_reason=None,
                                   details=[f"Rollback point {old_sha[:12]}", f"Active mode: {mode}"])
                self._notify(f"{self.spec['title']} update started", f"Installing {preflight['latest']}")
                if managed:
                    managed_state["phase"] = "stopping"
                    self._write_status(active_managed_update=managed_state)
                self._stop_mode(mode)
                if managed:
                    managed_state["phase"] = "stopped"
                    self._write_status(active_managed_update=managed_state)
                self._git("merge", "--ff-only", new_sha)
                if managed:
                    managed_state["phase"] = "merged"
                    self._write_status(active_managed_update=managed_state)
                self._install_dependencies()
                self._verify_import(preflight["latest"])
                if managed:
                    managed_state["phase"] = "verified"
                    self._write_status(active_managed_update=managed_state)
                    managed_state["phase"] = "restarting"
                    self._write_status(active_managed_update=managed_state, state="restarting")
                else:
                    self._write_status(state="restarting")
                self._start_mode(mode)
                if not self._verify_health(mode, preflight["latest"], new_sha):
                    raise UpdateError("The updated app did not attest to the expected commit and version.")
                terminal_schedule = {"next_retry": None}
                if not managed:
                    terminal_schedule["next_check"] = _iso(self._next_regular())
                self._write_status(state="succeeded", last_update_result=f"Updated to {preflight['latest']}",
                                   rollback=None, pending_manual=False,
                                   details=["Dependencies installed.", "Import check passed.",
                                            "Health and running version verified."],
                                   **terminal_schedule,
                                   **self._complete_managed_changes(managed, "succeeded"))
                self._notify(f"{self.spec['title']} update succeeded", f"Now running {preflight['latest']}")
                if self.settings()["mode"] == "off":
                    self.apply_scheduler()
                return self.public_status()
            except UpdateDeferred:
                raise
            except Exception as exc:
                rollback = None
                if old_sha and new_sha and old_sha != new_sha:
                    rollback = self._rollback(old_sha, new_sha, mode, old_version)
                message = str(_redact(str(exc)))
                self._write_status(state="failed", last_update_result="Update failed",
                                   rollback="succeeded" if rollback else ("failed" if rollback is False else None),
                                   details=[message], pending_manual=False, next_retry=None,
                                   **self._complete_managed_changes(managed, "failed"))
                self._notify(f"{self.spec['title']} update failed",
                             message if rollback is None else f"{message} Rollback {'succeeded' if rollback else 'failed'}.")
                if self.settings()["mode"] == "off":
                    self.apply_scheduler()
                raise

    def _managed_helper_args(self, managed: dict) -> list[str]:
        return ["--update", "--manual", "--target-commit", managed["target_commit"],
                "--target-version", managed["target_version"], "--operation-id", managed["operation_id"]]

    def _start_managed_helper(self, managed: dict) -> dict:
        # This wins over a future regular check after a restart, including when
        # the operator's normal update mode is Off, Notify, or Auto.
        self._write_status(next_retry=_iso(self.now()), pending_manual=True)
        try:
            process = self._spawn(*self._managed_helper_args(managed))
        except Exception as exc:
            self.log.exception("managed update helper did not start")
            self._write_status(state="deferred", last_update_result="Managed update queued for retry",
                               defer_reason="Managed helper will be retried by the durable schedule.",
                               details=[str(_redact(str(exc)))], next_retry=_iso(self.now()),
                               managed_helper_pid=None)
            return self.public_status()
        self._write_status(state="updating", last_update_result="Update started", defer_reason=None,
                           pending_manual=True, managed_helper_pid=getattr(process, "pid", None))
        return self.public_status()

    def trigger_update(self, *, after_current: bool = False, target_commit: Optional[str] = None,
                       target_version: Optional[str] = None, operation_id: Optional[str] = None) -> dict:
        managed = self._managed_request(target_commit=target_commit, target_version=target_version,
                                        operation_id=operation_id)
        with self._admission_lock():
            status = self._read_status()
            active = self._active_managed_request(status)
            history = self._managed_history(status)
            if managed:
                for completed in history:
                    if completed["operation_id"] == managed["operation_id"]:
                        if {key: completed[key] for key in managed} != managed:
                            raise UpdateError("Managed operation_id is already bound to a different target.")
                        return self.public_status()
                if active:
                    if active["operation_id"] != managed["operation_id"] or active != managed:
                        raise UpdateError("Another managed update operation is already active.")
                    if self._managed_helper_alive(status):
                        return self.public_status()
                    self.apply_scheduler(force_pending=True)
                    return self._start_managed_helper(managed)
                self._write_status(active_managed_update=managed, managed_update=None,
                                   managed_helper_pid=None, pending_manual=True)
                if after_current:
                    reasons = self.readiness_reasons(fail_closed=True)
                    self._write_status(state="deferred", defer_reason="; ".join(reasons) if reasons else "Queued for the next idle check",
                                       pending_manual=True, next_retry=_iso(self.now()))
                    self.apply_scheduler(force_pending=True)
                    return self.public_status()
                # Persist and install the retry mechanism before helper launch, so a
                # killed helper or a restart cannot lose an Off-mode managed request.
                self.apply_scheduler(force_pending=True)
                return self._start_managed_helper(managed)
            if active:
                raise UpdateError("A managed update operation is already active.")
            self._write_status(active_managed_update=None, managed_update=None, managed_helper_pid=None)
            if after_current:
                reasons = self.readiness_reasons()
                self._write_status(state="deferred", defer_reason="; ".join(reasons) if reasons else "Queued for the next idle check",
                                   pending_manual=True, next_retry=_iso(self.now()))
                self.apply_scheduler(force_pending=True)
                return self.public_status()
            self._spawn("--update", "--manual")
            self._write_status(state="updating", last_update_result="Update started", defer_reason=None,
                               pending_manual=False)
            return self.public_status()

    def retry(self) -> dict:
        managed = self._active_managed_request()
        return self.trigger_update(after_current=False, **(managed or {}))

    def _spawn(self, *args: str) -> subprocess.Popen:
        python = self._python()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(self.log_dir / "helper.log", "a", encoding="utf-8")
        try:
            return subprocess.Popen([str(python), "-m", "backend.auto_update", *args],
                                    cwd=str(self.root / "app"), stdout=stream, stderr=stream,
                                    start_new_session=True, close_fds=True)
        finally:
            stream.close()

    def scheduled(self) -> dict:
        status = self._read_status()
        cfg = self.settings()
        pending = bool(status.get("pending_manual"))
        if cfg["mode"] == "off" and not pending:
            self.apply_scheduler()
            return self.public_status()
        due_values = [_parse_iso(status.get("next_check")), _parse_iso(status.get("next_retry"))]
        due_values = [x for x in due_values if x]
        if due_values and self.now() < min(due_values):
            return self.public_status()
        if pending:
            try:
                return self.update(automatic=False, **(self._active_managed_request(status) or {}))
            except UpdateDeferred:
                return self.public_status()
        checked = self.check()
        self._write_status(next_check=_iso(self._next_regular()), next_retry=None)
        if not checked.get("update_available"):
            return self.public_status()
        if cfg["mode"] == "notify":
            version = checked.get("latest_version")
            if status.get("notified_version") != version:
                self._notify(f"{self.spec['title']} update available", f"Version {version} is ready")
                self._write_status(notified_version=version)
            return self.public_status()
        if cfg["mode"] == "auto":
            try:
                return self.update(automatic=True)
            except UpdateDeferred:
                return self.public_status()
        return self.public_status()


def cli() -> int:
    from .auto_update_config import create_updater
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--target-commit")
    parser.add_argument("--target-version")
    parser.add_argument("--operation-id")
    args = parser.parse_args()
    updater = create_updater()
    try:
        if args.update:
            updater.update(automatic=not args.manual, target_commit=args.target_commit,
                           target_version=args.target_version, operation_id=args.operation_id)
        else:
            updater.scheduled()
        return 0
    except UpdateDeferred:
        return 0
    except Exception:
        updater.log.exception("updater helper failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
