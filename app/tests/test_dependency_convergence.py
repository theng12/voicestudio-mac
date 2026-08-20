from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from backend import dependency_convergence as convergence


class RecordingRunner:
    def __init__(self, failure_at: int | None = None) -> None:
        self.argv: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.failure_at = failure_at

    def __call__(self, argv: list[str], **kwargs):
        self.argv.append(argv)
        self.kwargs.append(kwargs)
        if self.failure_at == len(self.argv):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)


@pytest.fixture
def toolchain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    home = tmp_path / "pinokio"
    conda = home / "bin" / "miniforge" / "bin" / "conda"
    uv = home / "bin" / "miniforge" / "bin" / "uv"
    for executable in (conda, uv):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
    config = tmp_path / "config.json"
    config.write_text('{"home": ' + repr(str(home)).replace("'", '"') + "}", encoding="utf-8")
    monkeypatch.setattr(convergence, "PINOKIO_CONFIG", config)
    monkeypatch.delenv("CONDA_EXE", raising=False)
    return conda, uv


def test_base_installs_and_verifies_media_tools(toolchain: tuple[Path, Path]) -> None:
    conda, uv = toolchain
    runner = RecordingRunner()

    convergence.converge("base", runner=runner)

    assert runner.argv == [
        [str(conda), "install", "-y", "-p", sys.prefix, "-c", "conda-forge", "ffmpeg"],
        [str(Path(sys.prefix) / "bin" / "ffmpeg"), "-version"],
        [str(Path(sys.prefix) / "bin" / "ffprobe"), "-version"],
        [str(uv), "pip", "install", "--python", sys.executable, "-r",
         str(convergence.APP / "requirements.txt")],
    ]
    assert all(kwargs == {"cwd": convergence.APP, "check": True, "timeout": 1800}
               for kwargs in runner.kwargs)


def test_all_installed_skips_missing_generation_marker(
    toolchain: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(convergence, "generation_installed", lambda: False)
    runner = RecordingRunner()

    convergence.converge("all-installed", runner=runner)

    assert len(runner.argv) == 4
    assert all("requirements-generation.txt" not in argv for argv in runner.argv)


def test_all_installed_refreshes_existing_generation_after_base(
    toolchain: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _conda, uv = toolchain
    monkeypatch.setattr(convergence, "generation_installed", lambda: True)
    runner = RecordingRunner()

    convergence.converge("all-installed", runner=runner)

    assert runner.argv[3] == [str(uv), "pip", "install", "--python", sys.executable, "-r",
                             str(convergence.APP / "requirements.txt")]
    assert runner.argv[4] == [str(uv), "pip", "install", "--python", sys.executable, "-r",
                             str(convergence.APP / "requirements-generation.txt")]
    assert runner.argv[5] == [sys.executable, "-c", convergence.GEN_VERIFY]


def test_generation_runs_full_verifier(toolchain: tuple[Path, Path]) -> None:
    runner = RecordingRunner()

    convergence.converge("generation", runner=runner)

    assert runner.argv[-1][:2] == [sys.executable, "-c"]
    for name in ("torch", "torchaudio", "transformers", "diffusers", "mlx_audio",
                 "mistral_common", "f5_tts", "fugashi", "jieba", "JAG2P", "ZHG2P"):
        assert name in runner.argv[-1][2]


def test_conda_prefers_a_valid_configured_executable(
    toolchain: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "provided-conda"
    configured.write_text("#!/bin/sh\n", encoding="utf-8")
    configured.chmod(0o755)
    monkeypatch.setenv("CONDA_EXE", str(configured))

    assert convergence.conda_executable() == str(configured)


def test_invalid_configured_conda_fails_closed(
    toolchain: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "not-executable-conda"
    configured.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("CONDA_EXE", str(configured))

    with pytest.raises(convergence.ConvergenceError, match="Pinokio toolchain unavailable"):
        convergence.conda_executable()


@pytest.mark.parametrize("contents", ["", "[]", "{", '{"home": "relative"}', '{"home": 4}'])
def test_missing_or_malformed_tool_configuration_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str,
) -> None:
    config = tmp_path / "config.json"
    config.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(convergence, "PINOKIO_CONFIG", config)
    monkeypatch.delenv("CONDA_EXE", raising=False)

    with pytest.raises(convergence.ConvergenceError, match="Pinokio toolchain unavailable"):
        convergence.uv_executable()


def test_missing_fixed_tool_fails_closed(toolchain: tuple[Path, Path]) -> None:
    _conda, uv = toolchain
    uv.unlink()

    with pytest.raises(convergence.ConvergenceError, match="Pinokio toolchain unavailable"):
        convergence.uv_executable()


def test_runner_failure_reports_only_the_failed_stage(toolchain: tuple[Path, Path]) -> None:
    runner = RecordingRunner(failure_at=2)

    with pytest.raises(convergence.ConvergenceError, match="base-ffmpeg-verify") as excinfo:
        convergence.converge("base", runner=runner)

    assert str(Path(sys.prefix)) not in str(excinfo.value)
    assert len(runner.argv) == 2


@pytest.mark.parametrize("mode", ["", "install", "base; echo no", "all"])
def test_invalid_mode_is_rejected_before_any_command(
    toolchain: tuple[Path, Path], mode: str,
) -> None:
    runner = RecordingRunner()

    with pytest.raises(ValueError, match="base, generation, or all-installed"):
        convergence.converge(mode, runner=runner)

    assert runner.argv == []


@pytest.mark.parametrize("invalid", ["secret-token=abc", "x" * 10_000])
def test_cli_rejects_invalid_argv_with_fixed_bounded_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], invalid: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(convergence, "converge", lambda mode: calls.append(mode))

    assert convergence.main([invalid]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "dependency convergence: invalid mode\n"
    assert len(captured.err) == 37
    assert invalid not in captured.err
    assert calls == []


@pytest.mark.parametrize("mode", ["base", "generation", "all-installed"])
def test_cli_accepts_only_each_fixed_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(convergence, "converge", lambda selected: calls.append(selected))

    assert convergence.main([mode]) == 0

    assert capsys.readouterr().err == ""
    assert calls == [mode]
