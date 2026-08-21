from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run_isolated_service_install(tmp_path: Path, environment: Path) -> None:
    commands = tmp_path / "commands"
    commands.mkdir(exist_ok=True)
    _write_executable(commands / "id", "#!/bin/sh\nprintf '501\\n'\n")
    _write_executable(
        commands / "launchctl",
        "#!/bin/sh\n[ \"$1\" = print ] && exit 1\nexit 0\n",
    )
    _write_executable(commands / "lsof", "#!/bin/sh\nexit 0\n")
    _write_executable(commands / "sleep", "#!/bin/sh\nexit 0\n")
    subprocess.run(
        ["/bin/bash", str(environment.parent / "install_service.sh")],
        cwd=environment.parent,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{commands}:{os.environ['PATH']}",
        },
        check=True,
        text=True,
        capture_output=True,
    )


def _launcher(name: str) -> dict:
    result = subprocess.run(
        ["node", "-e", f"console.log(JSON.stringify(require('./{name}')))"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _copy_service_fixture(tmp_path: Path) -> Path:
    app_root = tmp_path / "app"
    app_root.mkdir()
    for name in (
        "ENVIRONMENT.example",
        "install_service.sh",
        "voicestudio-serve.sh",
        "voicestudio-watchdog.sh",
    ):
        shutil.copy2(ROOT / name, app_root / name)
    return app_root


def test_repository_ships_template_and_ignores_machine_environment() -> None:
    template = ROOT / "ENVIRONMENT.example"

    assert template.is_file()
    assert not (ROOT / "ENVIRONMENT").exists()
    assert subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "ENVIRONMENT"], cwd=ROOT,
    ).returncode == 0
    assert subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "ENVIRONMENT.example"], cwd=ROOT,
    ).returncode == 1
    contents = template.read_text(encoding="utf-8")
    for key in (
        "HF_HOME=./cache/HF_HOME\n",
        "PINOKIO_SHARE_LOCAL=false\n",
        "PINOKIO_SHARE_LOCAL_PORT=\n",
        "VOICESTUDIO_EXTRA_MODEL_DIRS=\n",
    ):
        assert key in contents


def test_install_and_start_seed_only_a_missing_machine_environment() -> None:
    expected_seed = {
        "when": "{{!exists('ENVIRONMENT')}}",
        "method": "fs.copy",
        "params": {"src": "ENVIRONMENT.example", "dest": "ENVIRONMENT"},
    }

    install = _launcher("install.js")
    start = _launcher("start.js")

    assert install["run"][0] == expected_seed
    assert install["run"][1]["method"] == "shell.run"
    assert start["run"][0] == expected_seed
    server = start["run"][1]
    assert server["method"] == "shell.run"
    assert server["params"]["env"]["HF_HOME"] == (
        "{{envs.HF_HOME || path.resolve(cwd, 'cache/HF_HOME')}}"
    )
    assert start["run"][2] == {
        "method": "local.set",
        "params": {"url": "{{input.event[1]}}"},
    }


def test_service_install_seeds_all_defaults_when_machine_environment_is_missing(
    tmp_path: Path,
) -> None:
    app_root = _copy_service_fixture(tmp_path)
    environment = app_root / "ENVIRONMENT"

    _run_isolated_service_install(tmp_path, environment)

    contents = environment.read_text(encoding="utf-8")
    assert "HF_HOME=./cache/HF_HOME\n" in contents
    assert "PINOKIO_SHARE_LOCAL=false\n" in contents
    assert "PINOKIO_SHARE_LOCAL_PORT=\n" in contents
    assert "VOICESTUDIO_EXTRA_MODEL_DIRS=\n" in contents
    assert contents.count("PINOKIO_SCRIPT_AUTOLAUNCH=start.js\n") == 1
    assert contents.count("PINOKIO_SCRIPT_AUTOLAUNCH_ENABLED=false\n") == 1
    assert contents.count("PINOKIO_SCRIPT_REQUIRES=\n") == 1


def test_service_install_disables_pinokio_autolaunch_once_and_idempotently(
    tmp_path: Path,
) -> None:
    """A sandboxed launchctl stub proves the installer's user-facing effect.

    It never invokes the machine's launchd or the real Voice Studio service.
    """
    app_root = _copy_service_fixture(tmp_path)
    environment = app_root / "ENVIRONMENT"
    environment.write_text(
        "HF_HOME=./cache/HF_HOME\n"
        "PINOKIO_SCRIPT_AUTOLAUNCH=old-start.js\n"
        "PINOKIO_SCRIPT_AUTOLAUNCH_ENABLED=true\n"
        "PINOKIO_SCRIPT_AUTOLAUNCH=start.js\n"
        "PINOKIO_SCRIPT_AUTOLAUNCH_ENABLED=true\n"
        "PINOKIO_SCRIPT_REQUIRES=imagestudio-mac,studiohub-mac\n"
        "PINOKIO_SCRIPT_REQUIRES=stale-studio\n",
        encoding="utf-8",
    )
    before_inode = environment.stat().st_ino

    _run_isolated_service_install(tmp_path, environment)

    first = environment.read_text(encoding="utf-8")
    assert environment.stat().st_ino != before_inode
    assert first.count("PINOKIO_SCRIPT_AUTOLAUNCH=") == 1
    assert first.count("PINOKIO_SCRIPT_AUTOLAUNCH_ENABLED=") == 1
    assert first.count("PINOKIO_SCRIPT_REQUIRES=") == 1
    assert "PINOKIO_SCRIPT_AUTOLAUNCH=start.js\n" in first
    assert "PINOKIO_SCRIPT_AUTOLAUNCH_ENABLED=false\n" in first
    assert "PINOKIO_SCRIPT_REQUIRES=\n" in first
    assert "HF_HOME=./cache/HF_HOME\n" in first

    _run_isolated_service_install(tmp_path, environment)

    assert environment.read_text(encoding="utf-8") == first
