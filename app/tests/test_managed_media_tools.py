from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend import generation, media_tools, reference_audio, transcription


ROOT = Path(__file__).parents[2]


def test_generation_resolves_ffmpeg_from_the_app_conda_environment(
    tmp_path: Path, monkeypatch,
) -> None:
    """A clean service environment must not need a parent PATH or Homebrew."""
    root = tmp_path / "pinokio" / "api" / "voice-studio"
    executable = root / "conda_env" / "bin" / "ffmpeg"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    backend_file = root / "app" / "backend" / "generation.py"

    monkeypatch.setattr(media_tools, "__file__", str(backend_file))

    assert generation._find_ffmpeg_executable() == executable


def test_all_media_workers_share_the_managed_resolver() -> None:
    """Changing resolver policy once must cover TTS, reference decode, and STT."""
    assert all(
        getattr(worker, "media_tools", None) is media_tools
        for worker in (generation, reference_audio, transcription)
    )


def test_media_capability_exposes_only_availability_and_version(
    tmp_path: Path, monkeypatch,
) -> None:
    """Capability output must be safe to return from a health endpoint."""
    root = tmp_path / "pinokio" / "api" / "voice-studio"
    for name in ("ffmpeg", "ffprobe"):
        executable = root / "conda_env" / "bin" / name
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setattr(
        media_tools,
        "__file__",
        str(root / "app" / "backend" / "media_tools.py"),
    )
    monkeypatch.setattr(
        media_tools,
        "subprocess",
        SimpleNamespace(
            run=lambda command, **_kwargs: SimpleNamespace(
                stdout=f"{Path(command[0]).name} version 7.1.1 Copyright\n"
            )
        ),
        raising=False,
    )

    status = getattr(media_tools, "availability", lambda: {})()

    assert status == {
        "ffmpeg": {"available": True, "version": "7.1.1"},
        "ffprobe": {"available": True, "version": "7.1.1"},
    }
    assert str(root) not in str(status)


def test_generation_and_transcription_capabilities_publish_safe_media_facts(
    monkeypatch,
) -> None:
    facts = {
        "ffmpeg": {"available": True, "version": "7.1.1"},
        "ffprobe": {"available": True, "version": "7.1.1"},
    }
    monkeypatch.setattr(media_tools, "availability", lambda: facts)

    generation_status = generation.availability()
    transcription_status = transcription.availability()

    assert generation_status.get("media") == facts
    assert transcription_status.get("media") == facts
    assert str(ROOT) not in str(generation_status.get("media"))
    assert str(ROOT) not in str(transcription_status.get("media"))


def test_new_and_existing_installs_install_managed_ffmpeg() -> None:
    """Both normal launcher flows must provision the same Conda media tools."""
    for launcher in ("install.js", "update.js"):
        source = (ROOT / launcher).read_text(encoding="utf-8")
        assert "conda install -y -c conda-forge ffmpeg" in source
        assert "ffmpeg -version && ffprobe -version" in source
        assert source.index("conda install -y -c conda-forge ffmpeg") < source.index(
            "ffmpeg -version && ffprobe -version"
        )
