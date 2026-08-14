"""Managed FFmpeg/FFprobe discovery shared by Voice Studio workers."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


_TOOLS = frozenset({"ffmpeg", "ffprobe"})


def find_executable(name: str) -> Path | None:
    """Return a runnable media executable from this app's Conda environment."""
    if name not in _TOOLS:
        raise ValueError(f"Unsupported media tool: {name}")
    environment = Path(__file__).resolve().parents[2] / "conda_env"
    suffix = ".exe" if os.name == "nt" else ""
    for directory in (environment / "bin", environment / "Library" / "bin", environment / "Scripts"):
        candidate = directory / f"{name}{suffix}"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _version(executable: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    fields = result.stdout.splitlines()[0].split() if result.stdout else []
    return fields[2] if len(fields) >= 3 and fields[1] == "version" else None


def availability() -> dict[str, dict[str, bool | str | None]]:
    """Return non-secret managed media capability facts for health endpoints."""
    status = {}
    for name in sorted(_TOOLS):
        executable = find_executable(name)
        status[name] = {
            "available": executable is not None,
            "version": _version(executable) if executable else None,
        }
    return status
