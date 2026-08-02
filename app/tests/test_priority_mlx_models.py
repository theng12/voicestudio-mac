from __future__ import annotations

from pathlib import Path
import inspect
from types import SimpleNamespace

import numpy as np
import pytest

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
    assert "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit" in qwen
    assert len(qwen) == 5

    chatterbox = _repos("chatterbox-mlx")
    assert len(chatterbox) == 3
    assert "mlx-community/chatterbox-fp16" not in chatterbox
    assert "mlx-community/chatterbox-turbo-8bit" not in chatterbox

    omni = [entry for entry in catalog.CATALOG if entry.family == "omnivoice"]
    assert [entry.repo for entry in omni] == ["mlx-community/OmniVoice-bfloat16"]
    assert all(entry.repo.startswith("mlx-community/") for entry in omni)
    assert all("voice-cloning" in entry.capabilities for entry in omni)
    assert "k2-fsa/OmniVoice" not in {entry.repo for entry in omni}

    fish = _repos("fish-audio-mlx")
    assert fish == [
        "mlx-community/fish-audio-s2-pro-8bit",
        "mlx-community/fish-audio-s2-pro-bf16",
    ]
    assert all(
        "voice-cloning" in entry.capabilities
        for entry in catalog.CATALOG
        if entry.family == "fish-audio-mlx"
    )
    assert catalog.get_model(fish[0]).sample_rate_hz == 44100
    assert catalog.get_model(fish[0]).min_unified_memory_gb == 24


def test_diagnostics_cover_every_wired_engine_and_show_package_versions() -> None:
    result = generation.diagnostics()

    assert {engine["family"] for engine in result["engines"]} == generation._WIRED_FAMILIES
    assert result["total_engines"] == 14
    packages = {package["package"]: package for package in result["packages"]}
    assert packages["mlx_audio"]["version"]
    assert packages["torchaudio"]["installed"]
    assert "torchaudio" in generation._ENGINE_REQUIREMENTS["f5-tts"]
    assert "mistral_common" in generation._ENGINE_REQUIREMENTS["voxtral-tts"]
    assert "mlx_lm" in generation._ENGINE_REQUIREMENTS["marvis"]
    assert "mlx_lm" in generation._ENGINE_REQUIREMENTS["fish-audio-mlx"]
    assert "omnivoice" not in generation._ENGINE_REQUIREMENTS["omnivoice"]


def test_mlx_cache_release_prefers_current_api() -> None:
    source = inspect.getsource(generation._release_device_memory)
    assert source.index('hasattr(mx, "clear_cache")') < source.index('hasattr(mx, "metal")')


@pytest.mark.parametrize(
    "error",
    [
        MemoryError("unable to allocate Metal buffer"),
        RuntimeError("MPS backend out of memory"),
        RuntimeError("Abort trap: 6"),
    ],
)
def test_memory_failure_classifier_catches_engine_allocation_failures(error) -> None:
    assert generation._is_memory_failure(error)


def test_memory_failure_classifier_does_not_catch_normal_model_errors() -> None:
    assert not generation._is_memory_failure(RuntimeError("invalid speaker name"))


def test_memory_preflight_refuses_when_live_headroom_is_too_low(monkeypatch) -> None:
    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
    monkeypatch.setattr(
        generation,
        "_memory_snapshot",
        lambda: {"total_gb": 8.0, "available_gb": 1.0, "used_gb": 7.0, "percent": 87.5},
    )
    with pytest.raises(generation.MemoryGuardError, match="Memory guard paused"):
        manager._memory_preflight(SimpleNamespace(repo="repo", family="voxcpm-mlx", size_gb=2.3))


def test_qwen_17b_requires_a_16gb_machine_even_when_free_memory_looks_sufficient(
    monkeypatch,
) -> None:
    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_model = None
    manager._mlx_audio_model_repo = None
    manager._f5_tts_model = None
    manager._f5_tts_model_repo = None
    model = catalog.get_model("mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit")
    assert model is not None and model.min_unified_memory_gb == 16
    monkeypatch.setattr(
        generation,
        "_memory_snapshot",
        lambda: {"total_gb": 8.0, "available_gb": 6.0, "used_gb": 2.0, "percent": 25.0},
    )

    with pytest.raises(generation.MemoryGuardError, match="16 GB unified memory"):
        manager._memory_preflight(model)


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


@pytest.mark.parametrize(
    ("voice", "language", "expected"),
    [
        ("af_heart", "en", "a"),
        ("bf_emma", "English", "b"),
        ("af_heart", "en_US", "a"),
        ("bf_emma", "en-GB", "b"),
    ],
)
def test_kokoro_voice_picker_accepts_public_english_aliases(
    voice: str, language: str, expected: str
) -> None:
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}

    manager._mlx_kwargs_voice_picker(
        "kokoro-mlx",
        {"voice": voice, "language": language},
        kwargs,
    )

    assert kwargs["lang_code"] == expected


def test_kokoro_sinegen_backport_trims_and_pads_to_f0_length() -> None:
    class LongSineGen:
        def _f02sine(self, _f0_values):
            return np.ones((1, 7, 3), dtype=np.float32)

    class ShortSineGen:
        def _f02sine(self, _f0_values):
            return np.ones((1, 3, 3), dtype=np.float32)

    assert generation._backport_kokoro_sinegen_length_alignment(LongSineGen, np)
    assert generation._backport_kokoro_sinegen_length_alignment(ShortSineGen, np)

    target = np.zeros((1, 5, 3), dtype=np.float32)
    trimmed = LongSineGen()._f02sine(target)
    padded = ShortSineGen()._f02sine(target)

    assert trimmed.shape == (1, 5, 3)
    assert padded.shape == (1, 5, 3)
    assert np.all(padded[:, :3, :] == 1)
    assert np.all(padded[:, 3:, :] == 0)
    assert not generation._backport_kokoro_sinegen_length_alignment(LongSineGen, np)


def test_kokoro_sinegen_backport_defers_to_newer_upstream() -> None:
    class UpstreamSineGen:
        def _match_f0_length(self, sine_waves, _f0):
            return sine_waves

    assert not generation._backport_kokoro_sinegen_length_alignment(
        UpstreamSineGen, np
    )


def test_kokoro_language_dependencies_are_explicit() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements-generation.txt").read_text()
    assert "misaki[en,zh]==0.9.4" in requirements
    assert "fugashi[unidic-lite]" in requirements
    assert "kokoro>=" not in requirements


def test_f5_tts_uses_saved_voice_transcript_and_honors_override(
    tmp_path: Path, monkeypatch
) -> None:
    from backend import voices

    reference = tmp_path / "reference.wav"
    reference.touch()
    library = _VoiceLibrary(reference, transcript="Saved F5 reference transcript")
    monkeypatch.setattr(voices, "library", library)
    monkeypatch.setattr(generation, "_detect_device", lambda: "cpu")

    captured: dict = {}

    class _F5Model:
        def infer(self, **kwargs):
            captured.update(kwargs)
            return [0.0, 0.0], 24000, None

    manager = object.__new__(generation.GenerationManager)
    manager._f5_tts_get_model = lambda repo, device: _F5Model()
    job = generation.GenerationJob(
        job_id="f5-saved-transcript",
        mode="txt2speech",
        params={
            "text": "Generated speech",
            "voice_library_id": "voice-1",
            "ref_transcript": "",
            "seed": 123,
        },
    )

    manager._generate_f5_tts(
        job,
        SimpleNamespace(repo="SWivid/F5-TTS"),
        tmp_path / "output.wav",
    )

    assert captured["ref_file"] == str(reference)
    assert captured["ref_text"] == "Saved F5 reference transcript"
    assert captured["gen_text"] == "Generated speech"

    job.params["ref_transcript"] = "One-time corrected transcript"
    manager._generate_f5_tts(
        job,
        SimpleNamespace(repo="SWivid/F5-TTS"),
        tmp_path / "override-output.wav",
    )
    assert captured["ref_text"] == "One-time corrected transcript"


def test_bark_catalog_keeps_current_mlx_release_and_complete_presets() -> None:
    bark = [entry for entry in catalog.CATALOG if entry.family == "bark"]
    assert [entry.repo for entry in bark] == ["mlx-community/bark"]
    assert bark[0].ignore_patterns == ("speaker_embeddings/*",)
    assert len(generation.BARK_VOICE_PRESETS) == 130
    assert {item["lang"] for item in generation.BARK_VOICE_PRESETS} == {
        "en", "de", "es", "fr", "hi", "it", "ja", "ko", "pl", "pt", "ru", "tr", "zh",
    }
    assert all(
        sum(item["lang"] == lang for item in generation.BARK_VOICE_PRESETS) == 10
        for lang in {item["lang"] for item in generation.BARK_VOICE_PRESETS}
    )


def test_bark_companions_are_complete_without_unused_bert_weights() -> None:
    companions = catalog.companions_for("mlx-community/bark")
    assert companions[0]["repo"] == "mlx-community/encodec-24khz-float32"
    assert companions[1]["repo"] == "bert-base-multilingual-cased"
    assert companions[1]["allow_patterns"] == (
        "tokenizer.json", "tokenizer_config.json", "vocab.txt",
    )


def test_bark_mlx_controls_and_local_voice_prompt(tmp_path: Path) -> None:
    preset = tmp_path / "v2" / "en_speaker_6.npz"
    preset.parent.mkdir()
    preset.touch()
    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_snapshot_path = lambda repo: tmp_path
    kwargs: dict = {}

    label = manager._mlx_kwargs_bark(
        SimpleNamespace(repo="mlx-community/bark"),
        {
            "bark_voice_preset": "v2/en_speaker_6",
            "bark_temperature": 0.85,
            "bark_max_coarse_history": 240,
            "bark_sliding_window_len": 80,
            "bark_allow_early_stop": False,
        },
        kwargs,
    )

    assert label == "preset=v2/en_speaker_6"
    assert kwargs == {
        "voice": str(preset),
        "temperature": 0.85,
        "max_coarse_history": 240,
        "sliding_window_len": 80,
        "allow_early_stop": False,
    }


def test_bark_random_voice_does_not_inherit_kokoro_default() -> None:
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}
    manager._mlx_kwargs_bark(
        SimpleNamespace(repo="mlx-community/bark"), {}, kwargs
    )
    assert kwargs["voice"] is None


def test_bark_api_preserves_native_controls() -> None:
    from backend.main import Txt2SpeechBody

    params = Txt2SpeechBody(
        repo="mlx-community/bark",
        text="Hello",
        bark_temperature=0.6,
        bark_max_coarse_history=300,
        bark_sliding_window_len=90,
        bark_allow_early_stop=False,
    ).model_dump()
    assert params["bark_temperature"] == 0.6
    assert params["bark_max_coarse_history"] == 300
    assert params["bark_sliding_window_len"] == 90
    assert params["bark_allow_early_stop"] is False


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


def test_qwen_06b_custom_voice_uses_preset_speaker_mode() -> None:
    assert generation._qwen3_mode_from_repo(
        "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
    ) == "custom"


def test_qwen_clone_long_form_chunks_at_sentences_without_losing_text() -> None:
    text = " ".join([
        "First sentence keeps a natural pace.",
        "Second sentence remains with the same cloned voice.",
        "Third sentence is long enough to make this a genuine narration section.",
        "Fourth sentence begins the next section without accelerating the ending.",
        "Fifth sentence confirms every word survives the split.",
    ])
    chunks = generation._qwen_clone_text_chunks(text, max_chars=120)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_qwen_clone_long_sentence_falls_back_to_word_boundaries() -> None:
    text = "word " * 100
    chunks = generation._qwen_clone_text_chunks(text, max_chars=80)

    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


@pytest.mark.parametrize(
    ("family", "repo", "expected_limit"),
    [
        ("qwen3-tts", "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit", 360),
        ("qwen3-tts", "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit", 360),
        ("chatterbox-mlx", "mlx-community/chatterbox-8bit", 500),
        ("chatterbox-mlx", "mlx-community/chatterbox-turbo-4bit", 400),
        ("voxcpm-mlx", "mlx-community/VoxCPM2-4bit", 400),
        ("kokoro-mlx", "mlx-community/Kokoro-82M-bf16", 3000),
        ("vibevoice", "mlx-community/VibeVoice-Realtime-0.5B-4bit", 3000),
        ("fish-audio-mlx", "mlx-community/fish-audio-s2-pro-8bit", 300),
    ],
)
def test_long_form_local_engines_split_safely_without_losing_text(
    family: str, repo: str, expected_limit: int
) -> None:
    text = " ".join(
        f"Sentence {index} keeps every ordinary word at a natural boundary."
        for index in range(1, 121)
    )

    chunks = generation._internal_mlx_text_chunks(family, repo, text)

    assert len(chunks) > 1
    assert all(len(chunk) <= expected_limit for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_long_form_catalogs_do_not_ask_callers_to_manually_chunk() -> None:
    for family in (
        "qwen3-tts",
        "chatterbox-mlx",
        "voxcpm-mlx",
        "kokoro-mlx",
        "vibevoice",
        "fish-audio-mlx",
    ):
        guidance = catalog.FAMILIES[family].text_guidance
        assert guidance.soft_max_chars is None
        assert guidance.chunking == "auto-split"


@pytest.mark.parametrize(
    ("family", "repo"),
    [
        ("kokoro-mlx", "mlx-community/Kokoro-82M-bf16"),
        ("vibevoice", "mlx-community/VibeVoice-Realtime-0.5B-4bit"),
        ("fish-audio-mlx", "mlx-community/fish-audio-s2-pro-8bit"),
    ],
)
def test_customer_sized_40k_text_is_preserved_across_private_sections(
    family: str, repo: str
) -> None:
    text = " ".join(
        f"Sentence {index} stays complete, naturally paced, and privately sectioned."
        for index in range(1, 701)
    )
    assert len(text) > 40_000

    chunks = generation._internal_mlx_text_chunks(family, repo, text)

    assert len(chunks) > 10
    assert all(len(chunk) <= 3000 for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_qwen_clone_join_preserves_segment_audio_and_pause(tmp_path: Path) -> None:
    import numpy as np
    import soundfile as sf

    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "joined.wav"
    sf.write(first, np.full(10, 0.25, dtype=np.float32), 1000, subtype="PCM_16")
    sf.write(second, np.full(10, -0.25, dtype=np.float32), 1000, subtype="PCM_16")

    generation._join_qwen_clone_wavs([first, second], output, pause_s=0.01)
    audio, sample_rate = sf.read(output, dtype="float32")

    assert sample_rate == 1000
    assert len(audio) == 30
    assert np.allclose(audio[:10], 0.25, atol=1e-3)
    assert np.allclose(audio[10:20], 0.0, atol=1e-6)
    assert np.allclose(audio[20:], -0.25, atol=1e-3)


def test_qwen_speed_is_pitch_preserving_and_changes_duration(tmp_path: Path) -> None:
    import numpy as np
    import soundfile as sf

    if generation._find_ffmpeg_executable() is None:
        pytest.skip("FFmpeg is unavailable in this test environment")
    sample_rate = 24000
    seconds = 2.0
    time_axis = np.arange(round(sample_rate * seconds), dtype=np.float32) / sample_rate
    original = 0.25 * np.sin(2 * np.pi * 440.0 * time_axis)
    output = tmp_path / "qwen.wav"
    sf.write(output, original, sample_rate, subtype="PCM_16")

    assert generation._apply_qwen_output_speed(output, 0.90) is True
    adjusted, adjusted_rate = sf.read(output, dtype="float32")

    assert adjusted_rate == sample_rate
    assert len(adjusted) == pytest.approx(len(original) / 0.90, rel=0.03)
    spectrum = np.abs(np.fft.rfft(adjusted))
    frequencies = np.fft.rfftfreq(len(adjusted), 1 / adjusted_rate)
    dominant_hz = frequencies[int(np.argmax(spectrum))]
    assert dominant_hz == pytest.approx(440.0, abs=3.0)


def test_qwen_speed_one_is_a_lossless_noop(tmp_path: Path) -> None:
    output = tmp_path / "qwen.wav"
    payload = b"unchanged"
    output.write_bytes(payload)

    assert generation._apply_qwen_output_speed(output, 1.0) is False
    assert output.read_bytes() == payload


def test_voxcpm_speed_uses_shared_pitch_preserving_postprocess(tmp_path: Path) -> None:
    import soundfile as sf

    if generation._find_ffmpeg_executable() is None:
        pytest.skip("FFmpeg is unavailable in this test environment")
    sample_rate = 48000
    original = np.zeros(sample_rate * 2, dtype=np.float32)
    output = tmp_path / "voxcpm.wav"
    sf.write(output, original, sample_rate, subtype="PCM_16")

    assert generation._apply_mlx_output_speed(output, 0.95, "voxcpm-mlx") is True
    adjusted = sf.info(output)

    assert adjusted.samplerate == sample_rate
    assert adjusted.frames == pytest.approx(len(original) / 0.95, rel=0.03)


def test_voxcpm_long_form_speed_runs_once_after_join(
    tmp_path: Path, monkeypatch
) -> None:
    import importlib
    import soundfile as sf

    generate_module = importlib.import_module("mlx_audio.tts.generate")
    generated_sections: list[str] = []
    tempo_calls: list[tuple[Path, float, str]] = []

    def fake_generate_audio(*, model, output_path, join_audio, **kwargs) -> None:
        assert model == "voxcpm-model"
        assert join_audio is True
        generated_sections.append(kwargs["text"])
        sf.write(
            Path(output_path) / "audio.wav",
            np.ones(480, dtype=np.float32),
            48000,
            subtype="PCM_16",
        )

    def fake_apply_speed(path: Path, speed: float, family: str) -> bool:
        assert path.exists()
        tempo_calls.append((path, speed, family))
        return True

    monkeypatch.setattr(generate_module, "generate_audio", fake_generate_audio)
    monkeypatch.setattr(generation, "_apply_mlx_output_speed", fake_apply_speed)
    monkeypatch.setattr(generation, "_release_device_memory", lambda device: None)

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_get_model = lambda repo: "voxcpm-model"
    manager._resolve_mlx_kwargs = (
        lambda mode, family, model_entry, params, gen_kwargs: "zero-shot"
    )
    text = " ".join(
        f"Sentence {index} stays safely inside the VoxCPM long-form renderer."
        for index in range(1, 25)
    )
    job = generation.GenerationJob(
        job_id="voxcpm-long-speed",
        mode="txt2speech",
        params={"text": text, "speed": 0.93, "seed": 7},
    )
    output = tmp_path / "voxcpm-long.wav"

    manager._generate_mlx_audio(
        job,
        SimpleNamespace(
            repo="mlx-community/VoxCPM2-4bit",
            family="voxcpm-mlx",
            sample_rate_hz=48000,
        ),
        output,
    )

    assert len(generated_sections) > 1
    assert " ".join(generated_sections) == " ".join(text.split())
    assert tempo_calls == [(output, 0.93, "voxcpm-mlx")]
    assert sf.info(output).frames > 480


def test_qwen_regular_long_form_speed_runs_once_after_join(
    tmp_path: Path, monkeypatch
) -> None:
    import importlib
    import soundfile as sf

    generate_module = importlib.import_module("mlx_audio.tts.generate")
    generated_sections: list[str] = []
    tempo_calls: list[tuple[Path, float, str]] = []

    def fake_generate_audio(*, model, output_path, join_audio, **kwargs) -> None:
        assert model == "qwen-regular-model"
        assert join_audio is True
        generated_sections.append(kwargs["text"])
        sf.write(
            Path(output_path) / "audio.wav",
            np.ones(240, dtype=np.float32),
            24000,
            subtype="PCM_16",
        )

    def fake_apply_speed(path: Path, speed: float, family: str) -> bool:
        assert path.exists()
        tempo_calls.append((path, speed, family))
        return True

    monkeypatch.setattr(generate_module, "generate_audio", fake_generate_audio)
    monkeypatch.setattr(generation, "_apply_mlx_output_speed", fake_apply_speed)
    monkeypatch.setattr(generation, "_release_device_memory", lambda device: None)

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_get_model = lambda repo: "qwen-regular-model"
    manager._resolve_mlx_kwargs = (
        lambda mode, family, model_entry, params, gen_kwargs: "custom (speaker=Ryan)"
    )
    text = " ".join(
        f"Sentence {index} stays safely inside the Qwen preset long-form renderer."
        for index in range(1, 25)
    )
    job = generation.GenerationJob(
        job_id="qwen-regular-long-speed",
        mode="txt2speech",
        params={"text": text, "speed": 0.95, "seed": 11, "preset_speaker": "Ryan"},
    )
    output = tmp_path / "qwen-regular-long.wav"

    manager._generate_mlx_audio(
        job,
        SimpleNamespace(
            repo="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
            family="qwen3-tts",
            sample_rate_hz=24000,
        ),
        output,
    )

    assert len(generated_sections) > 1
    assert " ".join(generated_sections) == " ".join(text.split())
    assert tempo_calls == [(output, 0.95, "qwen3-tts")]
    assert sf.info(output).frames > 240


def test_vibevoice_long_form_uses_full_section_budget_and_applies_speed_once(
    tmp_path: Path, monkeypatch
) -> None:
    import importlib
    import soundfile as sf

    generate_module = importlib.import_module("mlx_audio.tts.generate")
    generated_sections: list[str] = []
    tempo_calls: list[tuple[Path, float, str]] = []

    def fake_generate_audio(*, model, output_path, join_audio, **kwargs) -> None:
        assert model == "vibevoice-model"
        assert join_audio is True
        assert kwargs["max_tokens"] == 4096
        assert "speed" not in kwargs
        generated_sections.append(kwargs["text"])
        sf.write(
            Path(output_path) / "audio.wav",
            np.ones(240, dtype=np.float32),
            24000,
            subtype="PCM_16",
        )

    def fake_apply_speed(path: Path, speed: float, family: str) -> bool:
        assert path.exists()
        tempo_calls.append((path, speed, family))
        return True

    monkeypatch.setattr(generate_module, "generate_audio", fake_generate_audio)
    monkeypatch.setattr(generation, "_apply_mlx_output_speed", fake_apply_speed)
    monkeypatch.setattr(generation, "_release_device_memory", lambda device: None)

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_get_model = lambda repo: "vibevoice-model"
    manager._resolve_mlx_kwargs = (
        lambda mode, family, model_entry, params, gen_kwargs: "voice=en-Emma_woman"
    )
    text = " ".join(
        f"Sentence {index} stays safely inside the VibeVoice long-form renderer."
        for index in range(1, 101)
    )
    job = generation.GenerationJob(
        job_id="vibevoice-long-speed",
        mode="txt2speech",
        params={"text": text, "speed": 0.93, "seed": 17, "voice": "en-Emma_woman"},
    )
    output = tmp_path / "vibevoice-long.wav"

    manager._generate_mlx_audio(
        job,
        SimpleNamespace(
            repo="mlx-community/VibeVoice-Realtime-0.5B-4bit",
            family="vibevoice",
            sample_rate_hz=24000,
        ),
        output,
    )

    assert len(generated_sections) > 1
    assert " ".join(generated_sections) == " ".join(text.split())
    assert tempo_calls == [(output, 0.93, "vibevoice")]
    assert sf.info(output).frames > 240


def test_fish_audio_long_form_keeps_native_speed_at_one_and_postprocesses_once(
    tmp_path: Path, monkeypatch
) -> None:
    import importlib
    import soundfile as sf

    generate_module = importlib.import_module("mlx_audio.tts.generate")
    generated_sections: list[str] = []
    tempo_calls: list[tuple[Path, float, str]] = []

    def fake_generate_audio(*, model, output_path, join_audio, **kwargs) -> None:
        assert model == "fish-model"
        assert join_audio is True
        assert kwargs["speed"] == 1.0
        assert kwargs["chunk_length"] == 100000
        generated_sections.append(kwargs["text"])
        sf.write(
            Path(output_path) / "audio.wav",
            np.ones(441, dtype=np.float32),
            44100,
            subtype="PCM_16",
        )

    def fake_apply_speed(path: Path, speed: float, family: str) -> bool:
        assert path.exists()
        tempo_calls.append((path, speed, family))
        return True

    monkeypatch.setattr(generate_module, "generate_audio", fake_generate_audio)
    monkeypatch.setattr(generation, "_apply_mlx_output_speed", fake_apply_speed)
    monkeypatch.setattr(generation, "_release_device_memory", lambda device: None)

    manager = object.__new__(generation.GenerationManager)
    manager._mlx_audio_get_model = lambda repo: "fish-model"
    manager._resolve_mlx_kwargs = (
        lambda mode, family, model_entry, params, gen_kwargs: "clone + style"
    )
    text = " ".join(
        f"Sentence {index} stays safely inside the Fish long-form renderer."
        for index in range(1, 80)
    )
    job = generation.GenerationJob(
        job_id="fish-long-speed",
        mode="txt2speech",
        params={"text": text, "speed": 0.97, "seed": 23},
    )
    output = tmp_path / "fish-long.wav"

    manager._generate_mlx_audio(
        job,
        SimpleNamespace(
            repo="mlx-community/fish-audio-s2-pro-8bit",
            family="fish-audio-mlx",
            sample_rate_hz=44100,
        ),
        output,
    )

    assert len(generated_sections) > 1
    assert " ".join(generated_sections) == " ".join(text.split())
    assert tempo_calls == [(output, 0.97, "fish-audio-mlx")]
    assert sf.info(output).frames > 441


def test_qwen_duration_ceiling_accounts_for_final_speed() -> None:
    assert generation._qwen_max_tokens_for_duration(30.0, 1.0) == 375
    assert generation._qwen_max_tokens_for_duration(30.0, 0.5) == 187
    assert generation._qwen_max_tokens_for_duration(30.0, 2.0) == 750


def test_requested_duration_ceiling_rejects_long_wav(tmp_path: Path) -> None:
    import numpy as np
    import soundfile as sf

    output = tmp_path / "too-long.wav"
    sf.write(output, np.zeros(30_010, dtype=np.float32), 1000, subtype="PCM_16")

    with pytest.raises(RuntimeError, match="exceeding the requested"):
        generation._enforce_output_duration_limit(
            output,
            {"max_output_duration_s": 30.0},
        )


def test_requested_duration_ceiling_accepts_exact_limit(tmp_path: Path) -> None:
    import numpy as np
    import soundfile as sf

    output = tmp_path / "exact.wav"
    sf.write(output, np.zeros(30_000, dtype=np.float32), 1000, subtype="PCM_16")

    generation._enforce_output_duration_limit(
        output,
        {"max_output_duration_s": 30.0},
    )


def test_tts_request_has_no_default_generated_audio_duration_cap() -> None:
    from backend import main

    body = main.Txt2SpeechBody(
        repo="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
        text="Long-form narration. " * 1_000,
        client_request_id="studiohub:stable-long-form-attempt",
        speed=0.9,
    )

    assert body.max_output_duration_s is None
    assert body.client_request_id == "studiohub:stable-long-form-attempt"
    assert body.speed == 0.9
    assert generation._requested_output_duration_limit(body.model_dump()) is None


def test_qwen_and_voxcpm_speed_control_is_visible_and_truthful() -> None:
    markup = (Path(__file__).parents[1] / "frontend" / "index.html").read_text()

    assert "qwen3Mode(gen.repo) !== 'clone'" not in markup
    assert "!isVoxCPMMlx(gen.repo)" not in markup
    assert "Qwen, VoxCPM2, VibeVoice, and Fish S2 Pro preserve pitch" in markup
    assert "after all sections are joined" in markup


def test_qwen_clone_long_form_renders_each_section_and_reports_progress(tmp_path: Path) -> None:
    import numpy as np
    import soundfile as sf

    calls: list[str] = []

    def fake_generate_audio(*, model, output_path, join_audio, **kwargs) -> None:
        assert model == "qwen-model"
        assert join_audio is True
        calls.append(kwargs["text"])
        sf.write(Path(output_path) / "audio.wav", np.ones(10, dtype=np.float32), 1000)

    manager = object.__new__(generation.GenerationManager)
    job = generation.GenerationJob(job_id="qwen-long", mode="txt2speech", params={})
    chunks = ["First short section.", "Second short section."]
    output = tmp_path / "output.wav"
    manager._generate_qwen_clone_long_form(
        job, "qwen-model", {"text": "ignored", "ref_audio": "voice.wav"},
        chunks, tmp_path, output, fake_generate_audio,
    )

    assert calls == chunks
    assert (job.chunk_index, job.chunk_total) == (2, 2)
    assert 0.92 < job.progress < 0.94
    assert output.exists()


def test_shared_long_form_renderer_fails_when_any_section_is_missing(tmp_path: Path) -> None:
    import soundfile as sf

    calls = 0

    def incomplete_generate_audio(*, model, output_path, join_audio, **kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            sf.write(Path(output_path) / "audio.wav", np.ones(10, dtype=np.float32), 1000)

    manager = object.__new__(generation.GenerationManager)
    job = generation.GenerationJob(job_id="missing-section", mode="txt2speech", params={})

    with pytest.raises(RuntimeError, match="didn't produce a wav file"):
        manager._generate_mlx_long_form_sections(
            job,
            "voxcpm-mlx",
            "voxcpm-model",
            {"text": "ignored", "ref_audio": "voice.wav"},
            ["First section.", "Second section."],
            tmp_path,
            tmp_path / "output.wav",
            incomplete_generate_audio,
        )

    assert not (tmp_path / "output.wav").exists()


def test_chatterbox_controls_match_standard_and_turbo_engines(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.touch()
    voices = SimpleNamespace(library=_VoiceLibrary(reference))
    manager = object.__new__(generation.GenerationManager)
    params = {
        "voice_library_id": "voice-1",
        "language": "en",
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
        "lang_code": "en",
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


def test_fish_audio_mlx_supports_optional_clone_style_and_clamps(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.touch()
    voices = SimpleNamespace(library=_VoiceLibrary(reference, transcript=""))
    manager = object.__new__(generation.GenerationManager)
    kwargs: dict = {}

    label = manager._mlx_kwargs_fish_audio(
        {
            "voice_library_id": "voice-1",
            "voice_design_prompt": "warm, intimate audiobook narration",
            "fish_temperature": 9,
            "fish_top_p": 0,
            "fish_top_k": 999,
            "fish_max_tokens": 9999,
        },
        kwargs,
        voices,
    )

    assert label.startswith("clone + style")
    assert kwargs["ref_audio"] == str(reference)
    assert kwargs["ref_text"] == ""
    assert kwargs["instruct"] == "warm, intimate audiobook narration"
    assert kwargs["temperature"] == 2.0
    assert kwargs["top_p"] == 0.05
    assert kwargs["top_k"] == 100
    assert kwargs["max_tokens"] == 4096
