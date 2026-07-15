from __future__ import annotations

from pathlib import Path
import inspect
from types import SimpleNamespace

from backend import catalog, generation


class _VoiceLibrary:
    def __init__(self, reference: Path, transcript: str = "Saved reference transcript") -> None:
        self.reference = reference
        self._transcript = transcript

    def get(self, voice_id: str):
        return {"id": voice_id} if voice_id == "voice-1" else None

    def reference_path(self, voice_id: str) -> Path:
        return self.reference

    def transcript(self, voice_id: str) -> str:
        return self._transcript


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


def test_kokoro_catalog_is_single_mlx_multilingual_release() -> None:
    kokoro = [entry for entry in catalog.CATALOG if "kokoro" in entry.family]
    assert [entry.repo for entry in kokoro] == ["mlx-community/Kokoro-82M-bf16"]
    assert "kokoro" not in catalog.FAMILIES
    assert len(generation.KOKORO_VOICES) == 54
    assert {voice["lang"] for voice in generation.KOKORO_VOICES} == set("abefhijpz")


def test_kokoro_voice_picker_sets_language_and_validates_blends() -> None:
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}
    label = manager._mlx_kwargs_voice_picker(
        "kokoro-mlx",
        {"voice": "jf_alpha,jm_kumo", "language": "j"},
        kwargs,
    )
    assert kwargs == {"voice": "jf_alpha,jm_kumo", "lang_code": "j"}
    assert "lang=j" in label

    try:
        manager._mlx_kwargs_voice_picker(
            "kokoro-mlx", {"voice": "af_heart,jf_alpha"}, {}
        )
    except ValueError as exc:
        assert "same language" in str(exc)
    else:
        raise AssertionError("cross-language Kokoro blend should fail")


def test_kokoro_language_dependencies_are_explicit() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements-generation.txt").read_text()
    assert "misaki[en,zh]==0.9.4" in requirements
    assert "fugashi[unidic-lite]" in requirements
    assert "kokoro>=" not in requirements


def test_mlx_worker_joins_all_generated_segments() -> None:
    source = inspect.getsource(generation.GenerationManager._generate_mlx_audio)
    assert "join_audio=True" in source
    assert 'temp_dir / "audio.wav"' in source


def test_voxcpm_catalog_keeps_latest_mlx_workflows_only() -> None:
    assert _repos("voxcpm-mlx") == [
        "mlx-community/VoxCPM2-4bit",
        "mlx-community/VoxCPM2-bf16",
    ]
    assert "voxcpm" not in catalog.FAMILIES
    requirements = (Path(__file__).resolve().parents[1] / "requirements-generation.txt").read_text()
    assert not any(line.startswith("voxcpm") for line in requirements.splitlines())


def test_voxcpm_saved_transcript_enables_ultimate_clone(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.touch()
    voices = SimpleNamespace(library=_VoiceLibrary(reference))
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}

    label = manager._mlx_kwargs_voxcpm_flex(
        {"voice_library_id": "voice-1", "voice_design_prompt": "calm and warm"},
        kwargs,
        voices,
    )

    assert label == "ultimate clone + style"
    assert kwargs == {
        "instruct": "calm and warm",
        "ref_audio": str(reference),
        "prompt_audio": str(reference),
        "prompt_text": "Saved reference transcript",
    }


def test_voxcpm_clone_without_transcript_stays_reference_only(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.touch()
    voices = SimpleNamespace(library=_VoiceLibrary(reference, transcript=""))
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}

    label = manager._mlx_kwargs_voxcpm_flex(
        {"voice_library_id": "voice-1"}, kwargs, voices
    )

    assert label == "reference clone"
    assert kwargs == {"ref_audio": str(reference)}


def test_mlx_worker_applies_seed_and_voxcpm_controls() -> None:
    source = inspect.getsource(generation.GenerationManager._generate_mlx_audio)
    assert "mx.random.seed" in source
    assert 'gen_kwargs["warmup_patches"]' in source
    assert 'gen_kwargs["max_tokens"]' in source


def test_voxcpm_api_preserves_advanced_controls() -> None:
    from backend.main import Txt2SpeechBody

    body = Txt2SpeechBody(
        repo="mlx-community/VoxCPM2-4bit",
        text="Hello",
        voxcpm_warmup_patches=2,
        voxcpm_max_tokens=3072,
    )
    params = body.model_dump()
    assert params["voxcpm_warmup_patches"] == 2
    assert params["voxcpm_max_tokens"] == 3072


def test_voxcpm_cached_model_materializes_thread_sensitive_boundary() -> None:
    source = inspect.getsource(generation.GenerationManager._mlx_audio_get_model)
    assert 'entry.family == "voxcpm-mlx"' in source
    assert "mx.eval(sr_boundaries)" in source


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
