"""Fixed dependency convergence for the Voice Studio application environment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence


APP = Path(__file__).resolve().parents[1]
MEDIA_BIN = Path(sys.prefix) / "bin"
PINOKIO_CONFIG = Path.home() / ".pinokio" / "config.json"
MODES = {"base", "generation", "all-installed"}
GEN_VERIFY = (
    "import torch, torchaudio, transformers, diffusers, mlx, mlx_lm, mlx_audio, "
    "mistral_common, f5_tts, fugashi, jieba; from importlib.metadata import version; "
    "from misaki.ja import JAG2P; from misaki.zh import ZHG2P; "
    "assert version('mistral-common') == '1.11.5'; "
    "JAG2P(); ZHG2P(); print('GEN_VERIFY_OK')"
)


class ConvergenceError(RuntimeError):
    """A fixed dependency stage could not be completed safely."""


def _pinokio_home() -> Path:
    try:
        config = json.loads(PINOKIO_CONFIG.read_text(encoding="utf-8"))
        home = config.get("home") if isinstance(config, dict) else None
    except (OSError, ValueError):
        home = None
    if not isinstance(home, str) or not home:
        raise ConvergenceError("Pinokio toolchain unavailable.")
    candidate = Path(home)
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ConvergenceError("Pinokio toolchain unavailable.")
    return candidate


def _fixed_tool(name: str) -> str:
    candidate = _pinokio_home() / "bin" / "miniforge" / "bin" / name
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise ConvergenceError("Pinokio toolchain unavailable.")
    return str(candidate)


def conda_executable() -> str:
    """Use Conda's explicit executable when valid, otherwise Pinokio's fixed one."""
    configured = os.environ.get("CONDA_EXE")
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise ConvergenceError("Pinokio toolchain unavailable.")
        return str(candidate)
    return _fixed_tool("conda")


def uv_executable() -> str:
    """Resolve only Pinokio's fixed uv executable."""
    return _fixed_tool("uv")


def pip_command(requirements: Path) -> list[str]:
    return [uv_executable(), "pip", "install", "--python", sys.executable, "-r", str(requirements)]


def generation_installed() -> bool:
    return any(path.is_dir() for path in Path(sys.prefix).glob("lib/python*/site-packages/diffusers"))


def _commands(mode: str) -> list[tuple[str, list[str]]]:
    if mode not in MODES:
        raise ValueError("mode must be base, generation, or all-installed")
    commands: list[tuple[str, list[str]]] = []
    if mode in {"base", "all-installed"}:
        commands.extend([
            ("base-media-install", [conda_executable(), "install", "-y", "-p", sys.prefix,
                                    "-c", "conda-forge", "ffmpeg"]),
            ("base-ffmpeg-verify", [str(MEDIA_BIN / "ffmpeg"), "-version"]),
            ("base-ffprobe-verify", [str(MEDIA_BIN / "ffprobe"), "-version"]),
            ("base-python-install", pip_command(APP / "requirements.txt")),
        ])
    if mode == "generation" or (mode == "all-installed" and generation_installed()):
        commands.extend([
            ("generation-python-install", pip_command(APP / "requirements-generation.txt")),
            ("generation-verify", [sys.executable, "-c", GEN_VERIFY]),
        ])
    return commands


def converge(mode: str, *, runner: Callable[..., object] = subprocess.run) -> None:
    """Run the selected fixed convergence mode without accepting caller input."""
    for stage, argv in _commands(mode):
        try:
            runner(argv, cwd=APP, check=True, timeout=1800)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConvergenceError(f"Dependency convergence failed during {stage}.") from exc


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) != 1 or values[0] not in MODES:
        print("dependency convergence: invalid mode", file=sys.stderr)
        return 2
    try:
        converge(values[0])
    except ConvergenceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
