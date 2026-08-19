from __future__ import annotations

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


def test_service_install_disables_pinokio_autolaunch_once_and_idempotently(
    tmp_path: Path,
) -> None:
    """A sandboxed launchctl stub proves the installer's user-facing effect.

    It never invokes the machine's launchd or the real Voice Studio service.
    """
    app_root = tmp_path / "app"
    app_root.mkdir()
    for name in (
        "install_service.sh",
        "voicestudio-serve.sh",
        "voicestudio-watchdog.sh",
    ):
        shutil.copy2(ROOT / name, app_root / name)
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
