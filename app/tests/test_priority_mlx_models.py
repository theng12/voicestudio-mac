from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend import catalog, generation


class _VoiceLibrary:
    def __init__(self, reference: Path) -> None:
        self.reference = reference

    def get(self, voice_id: str):
        return {"id": voice_id} if voice_id == "voice-1" else None

    def reference_path(self, voice_id: str) -> Path:
        return self.reference

    def transcript(self, voice_id: str) -> str:
        return "Saved reference transcript"


def _repos(family: str) -> list[str]:
    return [entry.repo for entry in catalog.CATALOG if entry.family == family]


def test_priority_catalog_is_focused_and_clone_capable() -> None:
    qwen = _repos("qwen3-tts")
    assert "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit" in qwen
    assert "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit" not in qwen
    assert len(qwen) == 4

    chatterbox = _repos("chatterbox-mlx")
    assert len(chatterbox) == 3
    assert "mlx-community/chatterbox-fp16" not in chatterbox
    assert "mlx-community/chatterbox-turbo-8bit" not in chatterbox

    omni = [entry for entry in catalog.CATALOG if entry.family == "omnivoice"]
    assert len(omni) == 3
    assert all(entry.repo.startswith("mlx-community/") for entry in omni)
    assert all("voice-cloning" in entry.capabilities for entry in omni)
    assert "k2-fsa/OmniVoice" not in {entry.repo for entry in omni}


def test_qwen_17b_base_uses_clone_mode() -> None:
    assert generation._qwen3_mode_from_repo(
        "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
    ) == "clone"


def test_chatterbox_controls_match_standard_and_turbo_engines(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.touch()
    voices = SimpleNamespace(library=_VoiceLibrary(reference))
    manager = object.__new__(generation.GenerationManager)
    params = {
        "voice_library_id": "voice-1",
        "temperature": 1.1,
        "cfg_value": 0.7,
        "chatterbox_cfg_weight": 0.6,
        "chatterbox_repetition_penalty": 1.3,
        "chatterbox_min_p": 0.1,
        "chatterbox_top_p": 0.9,
    }

    standard: dict = {}
    manager._mlx_kwargs_clone_with_intensity(
        SimpleNamespace(repo="mlx-community/chatterbox-8bit"),
        params,
        standard,
        voices,
    )
    assert standard == {
        "ref_audio": str(reference),
        "ref_text": "Saved reference transcript",
        "exaggeration": 0.7,
        "temperature": 1.1,
        "repetition_penalty": 1.3,
        "top_p": 0.9,
        "cfg_weight": 0.6,
        "min_p": 0.1,
    }

    turbo: dict = {}
    manager._mlx_kwargs_clone_with_intensity(
        SimpleNamespace(repo="mlx-community/chatterbox-turbo-4bit"),
        params,
        turbo,
        voices,
    )
    assert "exaggeration" not in turbo
    assert "cfg_weight" not in turbo
    assert "min_p" not in turbo
    assert turbo["temperature"] == 1.1


def test_omnivoice_mlx_supports_clone_plus_traits_and_clamps(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.touch()
    voices = SimpleNamespace(library=_VoiceLibrary(reference))
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}

    label = manager._mlx_kwargs_omnivoice(
        {
            "voice_library_id": "voice-1",
            "voice_design_prompt": "female, warm, khmer accent",
            "ref_transcript": "Override transcript",
            "omnivoice_num_steps": 100,
            "omnivoice_guidance_scale": 99,
            "omnivoice_duration_s": 240,
        },
        kwargs,
        voices,
    )

    assert label.startswith("combined")
    assert kwargs["ref_audio"] == str(reference)
    assert kwargs["ref_text"] == "Override transcript"
    assert kwargs["instruct"] == "female, warm, khmer accent"
    assert kwargs["num_steps"] == 64
    assert kwargs["guidance_scale"] == 8.0
    assert kwargs["duration_s"] == 120.0
