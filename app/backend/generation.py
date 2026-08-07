"""
TTS generation manager.

Worker dispatch is keyed off `model.family`. See `_WIRED_FAMILIES` below for
the authoritative list — the audit_truth.py script cross-checks that list
against the actual dispatch branches on every release.

Currently wired (workers exist):
- bark            → mlx-audio worker
- voxcpm-mlx      → mlx-audio worker
- kokoro-mlx      → mlx-audio worker
- qwen3-tts       → mlx-audio worker (custom / design / clone modes by repo)
- chatterbox-mlx  → mlx-audio worker
- spark-tts-mlx   → mlx-audio worker
- orpheus         → mlx-audio worker
- kittentts       → mlx-audio worker
- vibevoice       → mlx-audio worker
- voxtral-tts     → mlx-audio worker (20 preset voices / 9 langs)
- marvis          → mlx-audio worker (sesame/csm engine; 2 preset voices)
- omnivoice       → mlx-audio worker (voice design + cloning)
- fish-audio-mlx  → mlx-audio worker (Fish S2 Pro style + cloning)
- f5-tts          → f5_tts.api.F5TTS (separate worker)

Removed in v1.3.1:
- chatterbox (PyTorch) — chatterbox-mlx covers it on Apple Silicon
- spark-tts (PyTorch) — spark-tts-mlx covers it on Apple Silicon
- xtts (Coqui)         — TTS pip package pins old torch + non-commercial license

═════════════════════════════════════════════════════════════════════════
WORKER MODEL-LOADING STANDARD (established v1.3.5)
═════════════════════════════════════════════════════════════════════════

THE RULE: in every worker added to this file, resolve the local HF Hub
snapshot path and pass it EXPLICITLY to the loader. Never pass a HF repo
ID string when the loader will accept an absolute filesystem path.

THE PATTERN:

    def _engine_get_model(self, repo: str, device: str):
        # ... eviction-on-repo-switch boilerplate ...

        snapshot_path = self._mlx_audio_snapshot_path(repo)   # generic walker
        # Optional: validate critical files exist, raise clean RuntimeError
        ckpt = snapshot_path / "subfolder" / "model.safetensors"
        if not ckpt.exists():
            raise RuntimeError(
                f"<Engine> file missing at {ckpt}. "
                "Re-download <repo> from the Models tab."
            )

        model = SomeEngine.from_pretrained(
            str(snapshot_path),
            local_files_only=True,                            # belt + suspenders
            # ... engine-specific args
        )
        return model

WHY THIS EXISTS: different upstream libraries use different cache backends.
The standard `huggingface_hub` cache lives at
    ${HF_HOME}/hub/models--<org>--<repo>/...
But some libraries — notably `cached_path` (used by F5-TTS) — have their
OWN cache layout that doesn't share with HF Hub. When a worker passes a
repo string and the library internally uses `cached_path`, it looks in
the wrong directory and silently re-downloads even when the file is
already cached. This actually happened with F5-TTS in v1.3.0 → v1.3.4
(1.35 GB re-downloaded into a duplicate location). Passing an absolute
path bypasses the library's cache lookup entirely.

COMPLIANCE TABLE (keep current when adding workers):

| Worker                | Pattern                                                       | Status |
|-----------------------|---------------------------------------------------------------|--------|
| _generate_mlx_audio   | load_model(snapshot_path)  Path not str (v1.2.8)              | OK     |
| _generate_f5_tts      | F5TTS(ckpt_file=…, vocab_file=…)  (v1.3.4)                    | OK     |
| Bark via MLX worker   | load_model(snapshot_path) + absolute local voice prompt                   | OK |

═════════════════════════════════════════════════════════════════════════

Outputs land in `app/output/<job_id>.wav` and are persisted to
`app/output/.history.json` (same shape as MusicStudio's gen history) so they
survive server restarts.
"""
from __future__ import annotations

import hashlib
import importlib.util
from importlib import metadata
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
from packaging.version import InvalidVersion, Version

from . import (
    catalog,
    cache,
    long_form_policy,
    model_audits,
    qwen_quality,
    resource_telemetry,
)
from .voicestudio_genstudio_integration import final_tts_result


# ───────────── module-level state ─────────────

# TTS on MPS can OOM if multiple models are loaded simultaneously. Even
# Kokoro's 82M model + a second model would fight for unified memory.
# Serialize all generations.
_GEN_LOCK = threading.Lock()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
HISTORY_FILE = OUTPUT_DIR / ".history.json"
HISTORY_MAX = 200
_AUDIO_OUTPUT_SUFFIXES = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}

# Direct Voice Studio jobs need the same live-memory protection that Studio Hub
# already applies before dispatching local work. These are intentionally
# conservative: the model's on-disk size is only an approximation, so we keep
# extra room for token buffers, audio activations, and the rest of macOS.
MEMORY_HEADROOM_GB = 1.25
MEMORY_RETRY_LIMIT = 1
MEMORY_RESTART_FAILURES = 2


class MemoryGuardError(RuntimeError):
    """A job was refused before inference because the host had too little RAM."""


def _memory_snapshot() -> Optional[dict]:
    """Return live host memory, or None when the optional probe is unavailable."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / 1e9, 2),
            "available_gb": round(vm.available / 1e9, 2),
            "used_gb": round(vm.used / 1e9, 2),
            "percent": float(vm.percent),
        }
    except Exception:
        return None


def _required_free_memory_gb(model_entry, *, loaded: bool) -> float:
    """Use the exact same RAM estimate for inventory and admission."""
    model_gb = max(0.5, float(model_entry.size_gb or 0.5))
    required = (
        max(1.5, model_gb * 0.45) + MEMORY_HEADROOM_GB
        if loaded
        else model_gb + MEMORY_HEADROOM_GB
    )
    return round(required, 2)


def _is_memory_failure(exc: BaseException) -> bool:
    """Recognize allocation failures without treating ordinary model errors as OOM."""
    if isinstance(exc, MemoryError):
        return True
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in message for marker in (
        "out of memory", "out-of-memory", "mps backend out of memory",
        "metal allocation", "metal alloc", "allocation failed",
        "alloc failed", "resource limit", "abort trap: 6",
    ))


# ───────────── lightweight dependency discovery ─────────────

# Importing these libraries just to discover whether they are installed adds
# 10-20 seconds to every server restart. Model workers still perform the real
# imports when generation begins, while diagnostics performs an explicit deep
# import when the user asks for it.
def _package_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


_TTS_MISSING = [name for name in ("torch", "transformers") if not _package_installed(name)]
TTS_AVAILABLE = not _TTS_MISSING
TTS_IMPORT_ERROR: Optional[str] = (
    f"Missing packages: {', '.join(_TTS_MISSING)}" if _TTS_MISSING else None
)
# ───────────── Kokoro voice catalog ─────────────

# Kokoro v1.0 ships with named preset voices. Voice naming convention:
# - First letter: language code
# - Second letter: gender ('f' = female, 'm' = male)
# - Rest: voice nickname
# This roster is verified against the bf16 MLX snapshot's safetensors files.
KOKORO_VOICES = [
    # American English — Female
    {"id": "af_heart",   "label": "Heart (warm)",      "lang": "a", "gender": "f"},
    {"id": "af_bella",   "label": "Bella (clear)",     "lang": "a", "gender": "f"},
    {"id": "af_aoede",   "label": "Aoede (musical)",   "lang": "a", "gender": "f"},
    {"id": "af_kore",    "label": "Kore (neutral)",    "lang": "a", "gender": "f"},
    {"id": "af_nicole",  "label": "Nicole (soft)",     "lang": "a", "gender": "f"},
    {"id": "af_nova",    "label": "Nova (bright)",     "lang": "a", "gender": "f"},
    {"id": "af_sarah",   "label": "Sarah (calm)",      "lang": "a", "gender": "f"},
    {"id": "af_sky",     "label": "Sky (airy)",        "lang": "a", "gender": "f"},
    {"id": "af_alloy",   "label": "Alloy (smooth)",    "lang": "a", "gender": "f"},
    {"id": "af_jessica", "label": "Jessica (friendly)","lang": "a", "gender": "f"},
    {"id": "af_river",   "label": "River (mellow)",    "lang": "a", "gender": "f"},
    # American English — Male
    {"id": "am_michael", "label": "Michael (warm)",    "lang": "a", "gender": "m"},
    {"id": "am_adam",    "label": "Adam (neutral)",    "lang": "a", "gender": "m"},
    {"id": "am_echo",    "label": "Echo (resonant)",   "lang": "a", "gender": "m"},
    {"id": "am_eric",    "label": "Eric (casual)",     "lang": "a", "gender": "m"},
    {"id": "am_fenrir",  "label": "Fenrir (deep)",     "lang": "a", "gender": "m"},
    {"id": "am_liam",    "label": "Liam (young)",      "lang": "a", "gender": "m"},
    {"id": "am_onyx",    "label": "Onyx (rich)",       "lang": "a", "gender": "m"},
    {"id": "am_puck",    "label": "Puck (playful)",    "lang": "a", "gender": "m"},
    {"id": "am_santa",   "label": "Santa (jolly)",     "lang": "a", "gender": "m"},
    # British English — Female
    {"id": "bf_alice",   "label": "Alice (refined)",   "lang": "b", "gender": "f"},
    {"id": "bf_emma",    "label": "Emma (gentle)",     "lang": "b", "gender": "f"},
    {"id": "bf_isabella","label": "Isabella (formal)", "lang": "b", "gender": "f"},
    {"id": "bf_lily",    "label": "Lily (light)",      "lang": "b", "gender": "f"},
    # British English — Male
    {"id": "bm_daniel",  "label": "Daniel (clear)",    "lang": "b", "gender": "m"},
    {"id": "bm_fable",   "label": "Fable (story)",     "lang": "b", "gender": "m"},
    {"id": "bm_george",  "label": "George (warm)",     "lang": "b", "gender": "m"},
    {"id": "bm_lewis",   "label": "Lewis (calm)",      "lang": "b", "gender": "m"},
    # Spanish
    {"id": "ef_dora",    "label": "Dora",              "lang": "e", "gender": "f"},
    {"id": "em_alex",    "label": "Alex",              "lang": "e", "gender": "m"},
    {"id": "em_santa",   "label": "Santa",             "lang": "e", "gender": "m"},
    # French
    {"id": "ff_siwis",   "label": "Siwis",             "lang": "f", "gender": "f"},
    # Hindi
    {"id": "hf_alpha",   "label": "Alpha",             "lang": "h", "gender": "f"},
    {"id": "hf_beta",    "label": "Beta",              "lang": "h", "gender": "f"},
    {"id": "hm_omega",   "label": "Omega",             "lang": "h", "gender": "m"},
    {"id": "hm_psi",     "label": "Psi",               "lang": "h", "gender": "m"},
    # Italian
    {"id": "if_sara",    "label": "Sara",              "lang": "i", "gender": "f"},
    {"id": "im_nicola",  "label": "Nicola",            "lang": "i", "gender": "m"},
    # Japanese
    {"id": "jf_alpha",   "label": "Alpha",             "lang": "j", "gender": "f"},
    {"id": "jf_gongitsune", "label": "Gongitsune",     "lang": "j", "gender": "f"},
    {"id": "jf_nezumi",  "label": "Nezumi",            "lang": "j", "gender": "f"},
    {"id": "jf_tebukuro", "label": "Tebukuro",         "lang": "j", "gender": "f"},
    {"id": "jm_kumo",    "label": "Kumo",              "lang": "j", "gender": "m"},
    # Brazilian Portuguese
    {"id": "pf_dora",    "label": "Dora",              "lang": "p", "gender": "f"},
    {"id": "pm_alex",    "label": "Alex",              "lang": "p", "gender": "m"},
    {"id": "pm_santa",   "label": "Santa",             "lang": "p", "gender": "m"},
    # Mandarin Chinese
    {"id": "zf_xiaobei", "label": "Xiaobei",           "lang": "z", "gender": "f"},
    {"id": "zf_xiaoni",  "label": "Xiaoni",            "lang": "z", "gender": "f"},
    {"id": "zf_xiaoxiao", "label": "Xiaoxiao",         "lang": "z", "gender": "f"},
    {"id": "zf_xiaoyi",  "label": "Xiaoyi",            "lang": "z", "gender": "f"},
    {"id": "zm_yunjian", "label": "Yunjian",           "lang": "z", "gender": "m"},
    {"id": "zm_yunxi",   "label": "Yunxi",             "lang": "z", "gender": "m"},
    {"id": "zm_yunxia",  "label": "Yunxia",            "lang": "z", "gender": "m"},
    {"id": "zm_yunyang", "label": "Yunyang",           "lang": "z", "gender": "m"},
]

# Lang code → display name
LANG_NAMES = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}

_GENERIC_ENGLISH_ALIASES = {"en", "eng", "english"}
_AMERICAN_ENGLISH_ALIASES = {"en-us", "american-english"}
_BRITISH_ENGLISH_ALIASES = {"en-gb", "en-uk", "british-english"}


def _normalize_kokoro_language(requested_language: str, voice_language: str) -> str:
    """Translate public English language names to Kokoro's one-letter codes.

    Generic English follows the selected voice, so ``en`` works for either an
    American or British preset without silently changing that preset's accent.
    """
    normalized = requested_language.strip().lower().replace("_", "-").replace(" ", "-")
    if not normalized:
        return voice_language
    if normalized in _GENERIC_ENGLISH_ALIASES:
        return voice_language if voice_language in {"a", "b"} else "a"
    if normalized in _AMERICAN_ENGLISH_ALIASES:
        return "a"
    if normalized in _BRITISH_ENGLISH_ALIASES:
        return "b"
    return normalized


def _backport_kokoro_sinegen_length_alignment(sinegen_class=None, mx_module=None) -> bool:
    """Backport upstream mlx-audio cc30ce27f6 without advancing 52 commits.

    The pinned mlx-audio can resample a sine tensor a few hundred frames past
    the matching F0 tensor. Its next multiply then fails with
    ``broadcast_shapes`` and the caller only sees "didn't produce a wav".
    Upstream now trims or pads the sine tensor to the F0 length. Wrapping the
    private sine builder applies the same behavior while retaining the fleet's
    otherwise verified dependency set.
    """
    if sinegen_class is None or mx_module is None:
        import mlx.core as mx
        from mlx_audio.tts.models.kokoro.istftnet import SineGen

        sinegen_class = SineGen
        mx_module = mx

    if hasattr(sinegen_class, "_match_f0_length"):
        return False
    if getattr(sinegen_class, "_voicestudio_length_alignment", False):
        return False

    original_f02sine = sinegen_class._f02sine

    def _aligned_f02sine(instance, f0_values):
        sine_waves = original_f02sine(instance, f0_values)
        target_len = f0_values.shape[1]
        if sine_waves.shape[1] > target_len:
            return sine_waves[:, :target_len, :]
        if sine_waves.shape[1] < target_len:
            return mx_module.pad(
                sine_waves,
                ((0, 0), (0, target_len - sine_waves.shape[1]), (0, 0)),
            )
        return sine_waves

    sinegen_class._f02sine = _aligned_f02sine
    sinegen_class._voicestudio_length_alignment = True
    return True


def availability() -> dict:
    """Per-engine availability + the static config the frontend needs."""
    qwen3_ok = _have_mlx_audio()
    bark_ok = qwen3_ok
    omnivoice_ok = qwen3_ok
    f5_tts_ok = _have_f5_tts()
    wired = []
    if qwen3_ok:
        # All mlx-audio-backed families share one loader + one worker.
        # If mlx-audio imports, every entry in MLX_AUDIO_FAMILIES is wired.
        for fam in MLX_AUDIO_FAMILIES.keys():
            wired.append(fam)
    if f5_tts_ok:
        wired.append("f5-tts")
    return {
        "available": TTS_AVAILABLE,
        "kokoro_available": qwen3_ok,
        "qwen3_available": qwen3_ok,
        "voxcpm_available": qwen3_ok,
        "bark_available": bark_ok,
        "omnivoice_available": omnivoice_ok,
        "f5_tts_available": f5_tts_ok,
        "diffusers_available": _have_diffusers(),
        "error": TTS_IMPORT_ERROR,
        "device": _detect_device() if TTS_AVAILABLE else None,
        "kokoro_voices": KOKORO_VOICES,
        "qwen3_preset_speakers": QWEN3_PRESET_SPEAKERS,
        "qwen3_voice_design_examples": QWEN3_VOICE_DESIGN_EXAMPLES,
        "voxcpm_emotion_examples": VOXCPM_EMOTION_EXAMPLES,
        "bark_voice_presets": BARK_VOICE_PRESETS,
        "bark_tags": BARK_TAGS,
        # Preset-voice rosters for the clickable voice-button picker (v1.5.1).
        "voxtral_voices": VOXTRAL_VOICES,
        "marvis_voices": MARVIS_VOICES,
        "orpheus_voices": ORPHEUS_VOICES,
        "vibevoice_voices": VIBEVOICE_PRESET_VOICES,
        "lang_names": {**LANG_NAMES, **_BARK_LANGUAGES},
        "phase": 2,
        "wired_families": wired,
    }


def _have_mlx_audio() -> bool:
    return _package_installed("mlx_audio")


def _have_f5_tts() -> bool:
    """Lightweight presence check; diagnostics validates the package and deps."""
    return _package_installed("f5_tts")


VOXCPM_EMOTION_EXAMPLES = [
    "calm and measured",
    "excited and happy",
    "sad and slow",
    "angry and forceful",
    "whispering softly",
    "elderly male, gravelly",
    "young female, cheerful",
]


def _detect_device() -> str:
    """Report the native Voice Studio target without importing PyTorch."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mps"
    return "cpu"


def _have_diffusers() -> bool:
    return _package_installed("diffusers")


# ───────────── diagnostics ─────────────

# Keep in sync with requirements-generation.txt. The user-visible health check
# checks these one-by-one and tells the UI which engines are ready.
_PACKAGE_CHECKLIST = [
    ("torch",         "Core ML framework + MPS device support"),
    ("torchaudio",    "Audio operators required by F5-TTS and its vocoder stack"),
    ("transformers",  "Tokenizers used by Bark, Spark-TTS, and Whisper"),
    ("misaki",        "Multilingual grapheme-to-phoneme for Kokoro MLX"),
    ("fugashi",       "Japanese tokenizer for Kokoro MLX"),
    ("jieba",         "Mandarin tokenizer for Kokoro MLX"),
    ("diffusers",     "Diffusion utilities used by optional audio pipelines"),
    ("accelerate",    "Multi-device model loading"),
    ("soundfile",     "WAV file writing (libsndfile)"),
    ("numpy",         "Tensor numerics"),
    ("phonemizer",    "IPA conversion for speech engines"),
    # MLX-side packages (Qwen3-TTS family). Apple Silicon native, not PyTorch.
    ("mlx",           "Apple Silicon ML framework (Qwen3-TTS)"),
    ("mlx_lm",        "MLX language-model runtime used by Marvis"),
    ("mlx_audio",     "MLX inference wrapper for audio models (including OmniVoice and Fish S2 Pro)"),
    ("mistral_common", "Voxtral speech tokenizer and audio request encoding"),
    # F5-TTS (SWivid) — flow-matching voice cloning.
    ("f5_tts",        "F5-TTS flow-matching TTS engine"),
    ("vocos",         "VoCoS vocoder used by F5-TTS"),
]

_ENGINE_REQUIREMENTS = {
    "voxcpm-mlx":     ["mlx", "mlx_audio", "soundfile", "numpy"],
    "bark":           ["mlx", "mlx_audio", "transformers", "soundfile", "numpy"],
    # Other mlx-audio-backed families. All share the same package set, since
    # mlx-audio is the only inference dep.
    "qwen3-tts":      ["mlx", "mlx_audio", "soundfile", "numpy"],
    "kokoro-mlx":     ["mlx", "mlx_audio", "misaki", "fugashi", "jieba", "soundfile", "numpy"],
    "chatterbox-mlx": ["mlx", "mlx_audio", "soundfile", "numpy"],
    "spark-tts-mlx":  ["mlx", "mlx_audio", "soundfile", "numpy"],
    "orpheus":        ["mlx", "mlx_audio", "soundfile", "numpy"],
    "kittentts":      ["mlx", "mlx_audio", "soundfile", "numpy"],
    "vibevoice":      ["mlx", "mlx_audio", "soundfile", "numpy"],
    # v0.4.6 OmniVoice is MLX + Transformers; no separate omnivoice package is
    # required by the tracked generation environment. Torch may still be
    # installed globally for other engines, but is not an OmniVoice contract.
    "omnivoice":      ["mlx", "mlx_audio", "transformers", "soundfile", "numpy"],
    "fish-audio-mlx": ["mlx", "mlx_lm", "mlx_audio", "transformers", "soundfile", "numpy"],
    "voxtral-tts":    ["mlx", "mlx_audio", "mistral_common", "soundfile", "numpy"],
    "marvis":         ["mlx", "mlx_lm", "mlx_audio", "soundfile", "numpy"],
    # mlx-audio v0.4.7 additions. Both self-verified via a real local
    # generation; arktts needs no extra package, moss_tts_nano pulls its
    # codec as a runtime companion download (see catalog.FAMILY_COMPANIONS)
    # rather than a Python package.
    "arktts":         ["mlx", "mlx_audio", "soundfile", "numpy"],
    "moss-tts-nano":  ["mlx", "mlx_lm", "mlx_audio", "soundfile", "numpy"],
    # Echo-TTS bundles its DiT + sampling in mlx-audio and pulls the Fish S1 DAC
    # codec as a runtime companion download, so no extra Python package.
    "echo-tts":       ["mlx", "mlx_audio", "soundfile", "numpy"],
    # F5-TTS (PyTorch, flow-matching). Wired in v1.3.0.
    "f5-tts":     ["f5_tts", "torch", "torchaudio", "vocos", "soundfile"],
}

# Which engines have an actual worker implemented in this app — i.e. picking
# one of these models won't trip a NotImplementedError. Keep in sync with the
# branches in `_dispatch_txt2speech` below + the MLX_AUDIO_FAMILIES table.
_WIRED_FAMILIES = {
    "bark",
    # All mlx-audio-backed families share one worker.
    "qwen3-tts", "voxcpm-mlx", "kokoro-mlx",
    "chatterbox-mlx", "spark-tts-mlx", "orpheus",
    "kittentts", "vibevoice", "voxtral-tts", "marvis",
    "omnivoice", "fish-audio-mlx",
    "arktts", "moss-tts-nano", "echo-tts",
    # Its own loader (f5_tts.api.F5TTS) — separate worker.
    "f5-tts",
}


# ───────────── mlx-audio family config table ─────────────
#
# All families in this table share `_generate_mlx_audio` as their backend
# worker. Per-family differences are expressed declaratively here instead of
# duplicating the load/save scaffolding in N separate worker functions.
#
# Fields:
# - default_sample_rate: Hz emitted by the engine (used for log lines).
# - uses_cfg: whether to pass `cfg_value` + `inference_timesteps` knobs to
#   mlx-audio.generate_audio. Only VoxCPM2 uses these today.
# - mode: which kwarg-resolver to dispatch to:
#     "qwen3"             — repo-name picks one of custom/design/clone
#     "voxcpm_flex"       — any combo of ref_audio + ref_text + instruct
#     "voice_picker"      — voice param required (preset speaker), no clone
#     "clone_with_intensity" — needs ref_audio, optional exaggeration/intensity
#     "voice_or_clone"    — voice param OR ref_audio (zero-shot or clone)
#
# To add a new mlx-audio family: add a catalog FAMILIES entry, add ModelEntry
# rows, drop a config line here, list it in _WIRED_FAMILIES + _ENGINE_REQUIREMENTS.
# No new worker code needed unless mlx-audio exposes a never-before-seen kwarg.
MLX_AUDIO_FAMILIES: dict[str, dict] = {
    "bark": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "bark",
        "label": "Suno Bark (MLX)",
    },
    "qwen3-tts": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "qwen3",
        "label": "Qwen3-TTS",
    },
    "voxcpm-mlx": {
        "default_sample_rate": 48000,
        "uses_cfg": True,
        "mode": "voxcpm_flex",
        "label": "VoxCPM2 (MLX)",
    },
    "kokoro-mlx": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "voice_picker",
        "label": "Kokoro (MLX)",
    },
    "chatterbox-mlx": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "clone_with_intensity",
        "label": "Chatterbox (MLX)",
    },
    "spark-tts-mlx": {
        "default_sample_rate": 16000,
        "uses_cfg": False,
        "mode": "voice_or_clone",
        "label": "Spark-TTS (MLX)",
    },
    "orpheus": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "voice_picker",
        "label": "Orpheus",
    },
    "kittentts": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "voice_picker",
        "label": "KittenTTS",
    },
    "vibevoice": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "voice_picker",
        "label": "VibeVoice Realtime",
    },
    "voxtral-tts": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "voice_picker",
        "label": "Voxtral-4B-TTS",
    },
    "marvis": {
        # model_type "csm"/"marvis" → mlx-audio routes to the sesame engine.
        # Voices (conversational_a/b) resolve their prompt wavs from the model
        # repo itself (config text_tokenizer points at the Marvis repo), so no
        # gated sesame/csm-1b fallback is ever hit.
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "voice_picker",
        "label": "Marvis TTS",
    },
    "omnivoice": {
        "default_sample_rate": 24000,
        "uses_cfg": False,
        "mode": "omnivoice",
        "label": "OmniVoice (MLX)",
    },
    "fish-audio-mlx": {
        "default_sample_rate": 44100,
        "uses_cfg": False,
        "mode": "fish_audio",
        "label": "Fish Audio S2 Pro (MLX)",
    },
    "arktts": {
        "default_sample_rate": 44100,
        "uses_cfg": False,
        "mode": "audio8",
        "label": "Audio8 TTS Preview (MLX)",
    },
    "moss-tts-nano": {
        "default_sample_rate": 48000,
        "uses_cfg": False,
        "mode": "moss_tts_nano",
        "label": "MOSS-TTS-Nano (MLX)",
    },
    "echo-tts": {
        "default_sample_rate": 44100,
        "uses_cfg": False,
        "mode": "echo_tts",
        "label": "Echo-TTS (MLX)",
    },
}


# ───────────── Bark preset metadata ─────────────

# The current MLX conversion ships all ten v2 prompts for all 13 languages.
_BARK_LANGUAGES = {
    "en": "English", "de": "German", "es": "Spanish", "fr": "French",
    "hi": "Hindi", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "pl": "Polish", "pt": "Portuguese", "ru": "Russian", "tr": "Turkish",
    "zh": "Chinese",
}
BARK_VOICE_PRESETS = [
    {
        "id": f"v2/{lang}_speaker_{speaker}",
        "lang": lang,
        "label": f"{name} · Speaker {speaker}"
                 + (" (popular)" if lang == "en" and speaker == 6 else ""),
    }
    for lang, name in _BARK_LANGUAGES.items()
    for speaker in range(10)
]

# Non-verbal cues + style modifiers Bark understands. The UI exposes these as
# clickable chips that insert at the cursor in the text input — engine-specific
# UX per the prompts.js DESIGN RULE.
BARK_TAGS = [
    {"tag": "[laughter]",       "label": "Laughter",       "group": "non-verbal"},
    {"tag": "[laughs]",         "label": "Laughs",         "group": "non-verbal"},
    {"tag": "[sighs]",          "label": "Sighs",          "group": "non-verbal"},
    {"tag": "[gasps]",          "label": "Gasps",          "group": "non-verbal"},
    {"tag": "[clears throat]",  "label": "Clears throat",  "group": "non-verbal"},
    {"tag": "[whispers]",       "label": "Whispers",       "group": "non-verbal"},
    {"tag": "—",                "label": "— (em-dash hesitation)", "group": "prosody"},
    {"tag": "...",              "label": "... (trailing off)",     "group": "prosody"},
    {"tag": "[MUSIC]",          "label": "[MUSIC] — instrumental", "group": "musical"},
    {"tag": "[singing]",        "label": "[singing] — sung lyric", "group": "musical"},
    {"tag": "♪ ♪",              "label": "♪ ♪ — musical phrase",   "group": "musical"},
]


# ───────────── Qwen3-TTS preset metadata ─────────────

# Surfaced via /api/generate/availability so the frontend can populate the
# preset-speaker picker without re-querying mlx-audio.
#
# SOURCE OF TRUTH: the CustomVoice model's own config.json `spk_id` map. The
# installed mlx-community/Qwen3-TTS-12Hz-*-CustomVoice models ship EXACTLY these
# 9 speakers (verified against config.json):
#     aiden, dylan, eric, ono_anna, ryan, serena, sohee, uncle_fu, vivian
# mlx-audio matches speaker names case-insensitively and lowercases them before
# the spk_id lookup (qwen3_tts.py: `config.spk_id[speaker.lower()]`), so the
# capitalised display ids below resolve correctly.
#
# DO NOT add speakers that aren't in the model's spk_id map. Earlier this list
# carried two phantom speakers ("Ethan", "Chelsie") copied from an older Qwen
# roster — picking them passed the app's own validation but mlx-audio rejected
# them with `ValueError: Speaker 'Ethan' not supported`, which surfaced only as
# the generic "mlx-audio didn't produce a wav file" wall. Removed in v1.4.4.
QWEN3_PRESET_SPEAKERS = [
    {"id": "Ryan",     "lang": "en", "gender": "m", "description": "Dynamic male, strong rhythmic drive"},
    {"id": "Aiden",    "lang": "en", "gender": "m", "description": "Sunny American male, clear midrange"},
    {"id": "Serena",   "lang": "en", "gender": "f", "description": "Warm, gentle young female"},
    {"id": "Vivian",   "lang": "en", "gender": "f", "description": "Bright, slightly edgy young female"},
    {"id": "Uncle_Fu", "lang": "zh", "gender": "m", "description": "Seasoned male, low mellow timbre"},
    {"id": "Dylan",    "lang": "zh", "gender": "m", "description": "Youthful Beijing male, clear natural timbre"},
    {"id": "Eric",     "lang": "zh", "gender": "m", "description": "Lively Chengdu male, slightly husky"},
    {"id": "Ono_Anna", "lang": "ja", "gender": "f", "description": "Playful Japanese female, light timbre"},
    {"id": "Sohee",    "lang": "ko", "gender": "f", "description": "Warm Korean female, rich emotion"},
]

QWEN3_VOICE_DESIGN_EXAMPLES = [
    "Calm narrator, slow and contemplative",
    "Excited and happy, speaking very fast",
    "Sad and crying, speaking slowly",
    "Angry and shouting",
    "Whispering quietly",
    "Deep gravelly male, like a 60-year-old narrator",
    "Light cheerful female, friendly customer-service tone",
]


# ───────────── Preset-voice rosters for the MLX voice-picker families ─────────────
#
# Surfaced via /api/generate/availability so the frontend can render clickable
# voice buttons instead of a free-text field. Each id is the EXACT string the
# engine expects (verified against the installed mlx-audio engine source — same
# rigor as QWEN3_PRESET_SPEAKERS) so a button click can never produce a phantom
# voice. Families NOT listed here (KittenTTS, VibeVoice) keep the free-text
# field because their exact rosters aren't verifiable without the model on disk.

# Voxtral-4B-TTS — verified against voxtral_tts.py `VOICE_MAP` (20 entries).
# The voice name selects the language.
VOXTRAL_VOICES = [
    {"id": "casual_male",     "lang": "en", "gender": "m", "label": "Casual male"},
    {"id": "casual_female",   "lang": "en", "gender": "f", "label": "Casual female"},
    {"id": "cheerful_female", "lang": "en", "gender": "f", "label": "Cheerful female"},
    {"id": "neutral_male",    "lang": "en", "gender": "m", "label": "Neutral male"},
    {"id": "neutral_female",  "lang": "en", "gender": "f", "label": "Neutral female"},
    {"id": "fr_male",         "lang": "fr", "gender": "m", "label": "French male"},
    {"id": "fr_female",       "lang": "fr", "gender": "f", "label": "French female"},
    {"id": "es_male",         "lang": "es", "gender": "m", "label": "Spanish male"},
    {"id": "es_female",       "lang": "es", "gender": "f", "label": "Spanish female"},
    {"id": "de_male",         "lang": "de", "gender": "m", "label": "German male"},
    {"id": "de_female",       "lang": "de", "gender": "f", "label": "German female"},
    {"id": "it_male",         "lang": "it", "gender": "m", "label": "Italian male"},
    {"id": "it_female",       "lang": "it", "gender": "f", "label": "Italian female"},
    {"id": "pt_male",         "lang": "pt", "gender": "m", "label": "Portuguese male"},
    {"id": "pt_female",       "lang": "pt", "gender": "f", "label": "Portuguese female"},
    {"id": "nl_male",         "lang": "nl", "gender": "m", "label": "Dutch male"},
    {"id": "nl_female",       "lang": "nl", "gender": "f", "label": "Dutch female"},
    {"id": "ar_male",         "lang": "ar", "gender": "m", "label": "Arabic male"},
    {"id": "hi_male",         "lang": "hi", "gender": "m", "label": "Hindi male"},
    {"id": "hi_female",       "lang": "hi", "gender": "f", "label": "Hindi female"},
]

# Marvis TTS — verified against sesame.py SPEAKER_PROMPTS (2 entries).
MARVIS_VOICES = [
    {"id": "conversational_a", "lang": "en", "gender": "f", "label": "Conversational A (female)"},
    {"id": "conversational_b", "lang": "en", "gender": "m", "label": "Conversational B (male)"},
]

# Orpheus — the 8 canonical fine-tune voices (also listed in the catalog
# use_cases). mlx-audio passes the voice straight through to the prompt.
ORPHEUS_VOICES = [
    {"id": "tara", "lang": "en", "gender": "f", "label": "Tara"},
    {"id": "leah", "lang": "en", "gender": "f", "label": "Leah"},
    {"id": "jess", "lang": "en", "gender": "f", "label": "Jess"},
    {"id": "mia",  "lang": "en", "gender": "f", "label": "Mia"},
    {"id": "zoe",  "lang": "en", "gender": "f", "label": "Zoe"},
    {"id": "dan",  "lang": "en", "gender": "m", "label": "Dan"},
    {"id": "leo",  "lang": "en", "gender": "m", "label": "Leo"},
    {"id": "zac",  "lang": "en", "gender": "m", "label": "Zac"},
]

# VibeVoice Realtime 0.5B — verified against the exact voice files shipped in
# mlx-community/VibeVoice-Realtime-0.5B-4bit at revision
# 550877a15358642c1e062aa38ce1fe0623beaa1b. Microsoft treats the seven
# English / Indian-English presets as the supported roster. The additional
# nine languages are explicitly exploratory upstream, so keep their files
# selectable for owner research while labelling them experimental.
VIBEVOICE_PRESET_VOICES = [
    {"id": "en-Carter_man", "label": "Carter", "lang": "en", "gender": "m", "experimental": False},
    {"id": "en-Davis_man", "label": "Davis", "lang": "en", "gender": "m", "experimental": False},
    {"id": "en-Emma_woman", "label": "Emma", "lang": "en", "gender": "f", "experimental": False},
    {"id": "en-Frank_man", "label": "Frank", "lang": "en", "gender": "m", "experimental": False},
    {"id": "en-Grace_woman", "label": "Grace", "lang": "en", "gender": "f", "experimental": False},
    {"id": "en-Mike_man", "label": "Mike", "lang": "en", "gender": "m", "experimental": False},
    {"id": "in-Samuel_man", "label": "Samuel · Indian English", "lang": "en", "locale": "en-IN", "gender": "m", "experimental": False},
    {"id": "de-Spk0_man", "label": "German speaker 0", "lang": "de", "gender": "m", "experimental": True},
    {"id": "de-Spk1_woman", "label": "German speaker 1", "lang": "de", "gender": "f", "experimental": True},
    {"id": "fr-Spk0_man", "label": "French speaker 0", "lang": "fr", "gender": "m", "experimental": True},
    {"id": "fr-Spk1_woman", "label": "French speaker 1", "lang": "fr", "gender": "f", "experimental": True},
    {"id": "it-Spk0_woman", "label": "Italian speaker 0", "lang": "it", "gender": "f", "experimental": True},
    {"id": "it-Spk1_man", "label": "Italian speaker 1", "lang": "it", "gender": "m", "experimental": True},
    {"id": "jp-Spk0_man", "label": "Japanese speaker 0", "lang": "ja", "gender": "m", "experimental": True},
    {"id": "jp-Spk1_woman", "label": "Japanese speaker 1", "lang": "ja", "gender": "f", "experimental": True},
    {"id": "kr-Spk0_woman", "label": "Korean speaker 0", "lang": "ko", "gender": "f", "experimental": True},
    {"id": "kr-Spk1_man", "label": "Korean speaker 1", "lang": "ko", "gender": "m", "experimental": True},
    {"id": "nl-Spk0_man", "label": "Dutch speaker 0", "lang": "nl", "gender": "m", "experimental": True},
    {"id": "nl-Spk1_woman", "label": "Dutch speaker 1", "lang": "nl", "gender": "f", "experimental": True},
    {"id": "pl-Spk0_man", "label": "Polish speaker 0", "lang": "pl", "gender": "m", "experimental": True},
    {"id": "pl-Spk1_woman", "label": "Polish speaker 1", "lang": "pl", "gender": "f", "experimental": True},
    {"id": "pt-Spk0_woman", "label": "Portuguese speaker 0", "lang": "pt", "gender": "f", "experimental": True},
    {"id": "pt-Spk1_man", "label": "Portuguese speaker 1", "lang": "pt", "gender": "m", "experimental": True},
    {"id": "sp-Spk0_woman", "label": "Spanish speaker 0", "lang": "es", "gender": "f", "experimental": True},
    {"id": "sp-Spk1_man", "label": "Spanish speaker 1", "lang": "es", "gender": "m", "experimental": True},
]


def _qwen3_mode_from_repo(repo: str) -> str:
    """Detect the Qwen3-TTS subtype from the repo name.
    Base → 'clone' (uses voice library), CustomVoice → 'custom' (preset speakers),
    VoiceDesign → 'design' (natural language voice prompt)."""
    name = repo.rsplit("/", 1)[-1].lower()
    if "voicedesign" in name:
        return "design"
    if "customvoice" in name:
        return "custom"
    if "base" in name:
        return "clone"
    return "custom"   # safest fallback


# Qwen's Base / ICL clone path does not use the model's built-in newline
# splitting. Owner listening found the 360-character setting could change
# tonation at a boundary while a controlled 288-character run remained stable.
# Keep Base/ICL cloning at that verified conservative ceiling. CustomVoice is a
# different preset-speaker path and retains its existing budget.
_QWEN_CLONE_CHUNK_CHARS = (
    long_form_policy.QWEN_CLONE_SECTION_MAX_CHARACTERS
)
_VIBEVOICE_MAX_TOKENS = 4096
_LONG_FORM_JOIN_PAUSE_S = long_form_policy.DEFAULT_JOIN_PAUSE_SECONDS
_QWEN_SENTENCE_ENDINGS = frozenset(".!?。！？")
_QWEN_TRAILING_CLOSERS = frozenset("\"'”’»）】〕〉")


def _qwen_clone_text_chunks(text: str, max_chars: int = _QWEN_CLONE_CHUNK_CHARS) -> list[str]:
    """Split long Qwen Base clone text at natural narration boundaries.

    Qwen's ICL cloning routine treats its whole input as one sequence, even
    though the non-cloning code path understands newline segments. This keeps
    each independent clone safely short, prefers sentence endings, retains
    paragraph pauses, and falls back to word (then character) boundaries for
    unusually long sentences.
    """
    return _sentence_safe_text_chunks(text, max_chars=max_chars)


def _sentence_safe_text_chunks(text: str, max_chars: int) -> list[str]:
    """Split narration without dropping text or cutting ordinary words.

    This is shared by local engines whose public request can be long while
    their stable synthesis context is much shorter. Paragraph and sentence
    boundaries win; an unusually long sentence falls back to punctuation,
    whitespace, and only then an unavoidable character boundary.
    """
    if max_chars < 40:
        raise ValueError("Sentence-safe chunk size must be at least 40 characters")
    paragraphs = [
        " ".join(part.split())
        for part in text.strip().split("\n\n")
        if part.strip()
    ]
    chunks: list[str] = []
    for paragraph in paragraphs:
        sentences: list[str] = []
        start = 0
        index = 0
        while index < len(paragraph):
            if paragraph[index] in _QWEN_SENTENCE_ENDINGS:
                end = index + 1
                while end < len(paragraph) and paragraph[end] in _QWEN_TRAILING_CLOSERS:
                    end += 1
                if end == len(paragraph) or paragraph[end].isspace():
                    sentence = paragraph[start:end].strip()
                    if sentence:
                        sentences.append(sentence)
                    start = end
                    index = end
                    continue
            index += 1
        remainder = paragraph[start:].strip()
        if remainder:
            sentences.append(remainder)

        current = ""
        for sentence in sentences:
            units = _split_long_text_unit(sentence, max_chars)
            for unit in units:
                if current and len(current) + 1 + len(unit) > max_chars:
                    chunks.append(current)
                    current = ""
                current = f"{current} {unit}".strip()
        if current:
            chunks.append(current)
    return chunks


def _split_long_text_unit(text: str, max_chars: int) -> list[str]:
    """Break one overlong sentence without dropping or rewriting text."""
    pieces: list[str] = []
    remaining = text.strip()
    floor = max(1, int(max_chars * 0.55))
    while len(remaining) > max_chars:
        whitespace = remaining.rfind(" ", floor, max_chars + 1)
        punctuation = max(
            (remaining.rfind(mark, floor, max_chars + 1) + 1 for mark in ",;:、，；："),
            default=0,
        )
        cut = max(whitespace, punctuation)
        if cut <= 0:
            cut = max_chars
        piece = remaining[:cut].strip()
        if not piece:
            cut = max_chars
            piece = remaining[:cut]
        pieces.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _internal_mlx_text_chunks(
    family: str,
    repo: str,
    text: str,
    *,
    max_chars_override: Optional[int] = None,
) -> list[str]:
    """Return safe independent synthesis sections for long-form local TTS.

    A passed model audit may tighten or expand the private section budget for
    one exact checkpoint. Until that evidence exists, the established family
    fallback remains active. Callers still submit one complete script.
    """
    audited = model_audits.input_limits(repo).get(
        "private_section_max_characters"
    )
    policy = long_form_policy.policy_for(
        family,
        repo,
        audited_section_max_characters=audited,
    )
    if policy is None:
        return []
    max_chars = int(max_chars_override or policy["section_max_characters"])
    return _sentence_safe_text_chunks(text, max_chars=max_chars)


def _long_form_join_pause_s(family: str, repo: str) -> float:
    """Return a private, model-path-specific pause between rendered sections."""
    policy = long_form_policy.policy_for(family, repo)
    if policy is None:
        return _LONG_FORM_JOIN_PAUSE_S
    return float(policy["join_pause_seconds"])


def _join_long_form_wavs(segment_paths: list[Path], output_path: Path,
                         family: str, pause_s: float = _LONG_FORM_JOIN_PAUSE_S) -> None:
    """Validate and atomically stream independently synthesized WAV sections."""
    if not segment_paths:
        raise ValueError(f"No {family} audio segments were generated")
    import numpy as np
    import soundfile as sf

    first_info = sf.info(str(segment_paths[0]))
    sample_rate = first_info.samplerate
    channels = first_info.channels
    if sample_rate <= 0 or channels <= 0 or first_info.frames <= 0:
        raise RuntimeError(f"{family} returned an empty or invalid audio segment")

    # Validate every section before creating any candidate final file. A
    # missing, empty, or incompatible section must never look like a successful
    # partial long-form result.
    for path in segment_paths:
        info = sf.info(str(path))
        if info.samplerate != sample_rate or info.channels != channels:
            raise RuntimeError(f"{family} segments returned incompatible audio formats")
        if info.frames <= 0:
            raise RuntimeError(f"{family} returned an empty audio segment: {path.name}")

    pause = np.zeros(
        (round(max(0.0, pause_s) * sample_rate), channels),
        dtype=np.float32,
    )
    joining_path = output_path.parent / (
        f".{output_path.name}.{uuid.uuid4().hex}.joining"
    )
    try:
        with sf.SoundFile(
            str(joining_path),
            mode="w",
            samplerate=sample_rate,
            channels=channels,
            format="WAV",
            subtype=first_info.subtype,
        ) as destination:
            for index, path in enumerate(segment_paths):
                with sf.SoundFile(str(path), mode="r") as source:
                    while True:
                        block = source.read(
                            frames=262_144,
                            dtype="float32",
                            always_2d=True,
                        )
                        if len(block) == 0:
                            break
                        destination.write(block)
                if index < len(segment_paths) - 1 and len(pause):
                    destination.write(pause)
        os.replace(joining_path, output_path)
    finally:
        joining_path.unlink(missing_ok=True)


def _join_qwen_clone_wavs(segment_paths: list[Path], output_path: Path,
                          pause_s: float = _LONG_FORM_JOIN_PAUSE_S) -> None:
    """Compatibility wrapper for the established Qwen regression surface."""
    _join_long_form_wavs(segment_paths, output_path, "qwen3-tts", pause_s)


def _find_ffmpeg_executable() -> Optional[Path]:
    """Find FFmpeg in normal, Pinokio-bundled, and common Apple Silicon paths."""
    override = (os.environ.get("VOICESTUDIO_FFMPEG") or "").strip()
    candidates = [Path(override)] if override else []
    resolved = shutil.which("ffmpeg")
    if resolved:
        candidates.append(Path(resolved))
    # launchd services start with a minimal PATH. Walk upward until the
    # Pinokio root is found so service mode can still use its bundled FFmpeg.
    for parent in Path(__file__).resolve().parents:
        candidates.extend([
            parent / "bin" / "miniforge" / "bin" / "ffmpeg",
            parent / "bin" / "ffmpeg-env" / "bin" / "ffmpeg",
        ])
    candidates.extend([Path("/opt/homebrew/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg")])
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


_POSTPROCESSED_SPEED_FAMILIES = {
    "qwen3-tts": "Qwen",
    "voxcpm-mlx": "VoxCPM2",
    "vibevoice": "VibeVoice",
    "fish-audio-mlx": "Fish Audio S2 Pro",
    # Neither engine's generate() accepts a speed kwarg (verified against the
    # installed mlx-audio source) — the public speed control is applied here
    # as one pitch-preserving tempo pass on the finished WAV, same as Fish.
    "arktts": "Audio8 TTS Preview",
    "moss-tts-nano": "MOSS-TTS-Nano",
    "echo-tts": "Echo-TTS",
    # OmniVoice.generate() takes no speed argument either (verified against the
    # installed mlx-audio source: it declares **kwargs and never reads it), so a
    # passed speed was accepted and silently discarded. It was missing from this
    # map AND from the pass-through exclusion below, which made the public speed
    # control a no-op for every API caller.
    "omnivoice": "OmniVoice",
}


# Qwen CustomVoice and Chatterbox can occasionally continue emitting silent
# acoustic tokens after audible speech has finished.  The defect is distinct
# from a natural pause: it is a multi-second *terminal* tail, sometimes with
# one tiny non-speech blip far after the real narration. Keep a short tail pad
# for natural word decay, and never apply this repair to another family, Qwen
# clone mode, references, or transcription.
_TERMINAL_SILENCE_MIN_SECONDS = 2.0
_TERMINAL_SILENCE_PAD_SECONDS = 0.25
_TERMINAL_SILENCE_FRAME_SECONDS = 0.02
_TERMINAL_SILENCE_RELATIVE_THRESHOLD = 0.015
_TERMINAL_SILENCE_FLOOR = 0.0005
_TERMINAL_BLIP_MAX_SECONDS = 0.10
_TERMINAL_BLIP_BRIDGE_SECONDS = 0.12


def _terminal_silence_correction_label(repo: str, family: str) -> Optional[str]:
    """Return the explicitly audited local model modes that need this repair."""
    if family == "qwen3-tts" and "qwen3-tts" in repo.lower() and _qwen3_mode_from_repo(repo) == "custom":
        return "Qwen CustomVoice"
    if family == "chatterbox-mlx":
        return "Chatterbox"
    return None


def _trim_model_terminal_silence(output_path: Path, repo: str, family: str) -> float:
    """Remove a pathological terminal silent tail from an audited local TTS WAV.

    Returns seconds removed. Audio is scanned and copied in bounded blocks so a
    long-form artifact is not loaded alongside the active MLX model. A small,
    isolated terminal blip after a pathological silent gap is ignored rather
    than preserving the entire gap. Normal interior pauses and short natural
    endings are left byte-for-byte unchanged.
    """
    label = _terminal_silence_correction_label(repo, family)
    if label is None:
        return 0.0

    import numpy as np
    import soundfile as sf

    info = sf.info(str(output_path))
    if info.frames <= 0 or info.samplerate <= 0 or info.channels <= 0:
        raise RuntimeError(f"{label} produced an invalid WAV before silence validation")

    analysis_frame = max(1, round(info.samplerate * _TERMINAL_SILENCE_FRAME_SECONDS))
    block_frames = max(analysis_frame, analysis_frame * 500)
    peak = 0.0
    with sf.SoundFile(str(output_path), mode="r") as reader:
        while True:
            samples = reader.read(block_frames, dtype="float32", always_2d=True)
            if len(samples) == 0:
                break
            peak = max(peak, float(np.max(np.abs(samples))))

    # A fully silent output remains a model failure rather than a misleading
    # zero-length success.  Existing final-artifact validation will reject it
    # only if it is empty, so make this explicit for this faulty model path.
    if peak < _TERMINAL_SILENCE_FLOOR:
        raise RuntimeError(f"{label} produced no audible speech")
    threshold = max(
        _TERMINAL_SILENCE_FLOOR,
        peak * _TERMINAL_SILENCE_RELATIVE_THRESHOLD,
    )

    voiced_frames: list[bool] = []
    with sf.SoundFile(str(output_path), mode="r") as reader:
        while True:
            samples = reader.read(block_frames, dtype="float32", always_2d=True)
            if len(samples) == 0:
                break
            full_frames = len(samples) // analysis_frame
            if full_frames:
                framed = samples[:full_frames * analysis_frame].reshape(
                    full_frames, analysis_frame, info.channels
                )
                rms = np.sqrt(np.mean(np.square(framed), axis=(1, 2)))
                voiced_frames.extend(bool(value) for value in rms >= threshold)
            if full_frames * analysis_frame < len(samples):
                remainder = samples[full_frames * analysis_frame:]
                voiced_frames.append(float(np.sqrt(np.mean(np.square(remainder)))) >= threshold)

    bridge_frames = max(1, round(_TERMINAL_BLIP_BRIDGE_SECONDS / _TERMINAL_SILENCE_FRAME_SECONDS))
    min_meaningful_frames = max(1, round(_TERMINAL_BLIP_MAX_SECONDS / _TERMINAL_SILENCE_FRAME_SECONDS))
    tail_gap_frames = max(1, round(_TERMINAL_SILENCE_MIN_SECONDS / _TERMINAL_SILENCE_FRAME_SECONDS))
    last_audible_end = 0
    index = len(voiced_frames) - 1
    while index >= 0:
        while index >= 0 and not voiced_frames[index]:
            index -= 1
        if index < 0:
            break
        end = index + 1
        start = index
        voiced_count = 1
        previous = index - 1
        while previous >= 0:
            while previous >= 0 and not voiced_frames[previous]:
                previous -= 1
            if previous < 0 or start - previous - 1 > bridge_frames:
                break
            voiced_count += 1
            start = previous
            previous -= 1

        # A one- or two-frame blip after multiple seconds of silence is not
        # narration. Ignore it and continue looking for the final meaningful
        # speech region, while retaining a similarly short sound after a
        # normal pause to avoid clipping natural endings.
        if voiced_count < min_meaningful_frames and previous >= 0 and start - previous - 1 >= tail_gap_frames:
            index = previous
            continue
        last_audible_end = min(info.frames, end * analysis_frame)
        break

    if not last_audible_end:
        raise RuntimeError(f"{label} produced no audible speech")
    keep_frames = min(
        info.frames,
        last_audible_end + round(info.samplerate * _TERMINAL_SILENCE_PAD_SECONDS),
    )
    removed_frames = info.frames - keep_frames
    if removed_frames / info.samplerate < _TERMINAL_SILENCE_MIN_SECONDS:
        return 0.0

    temporary = output_path.with_name(
        f".{output_path.stem}.qwen-terminal-trim-{uuid.uuid4().hex}.wav"
    )
    try:
        with sf.SoundFile(str(output_path), mode="r") as source, sf.SoundFile(
            str(temporary),
            mode="w",
            samplerate=info.samplerate,
            channels=info.channels,
            format="WAV",
            subtype=info.subtype,
        ) as destination:
            remaining = keep_frames
            while remaining > 0:
                samples = source.read(min(block_frames, remaining), dtype="float32", always_2d=True)
                if len(samples) == 0:
                    raise RuntimeError(f"{label} WAV ended during silence correction")
                destination.write(samples)
                remaining -= len(samples)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return removed_frames / info.samplerate


def _trim_qwen_custom_terminal_silence(output_path: Path, repo: str) -> float:
    """Compatibility wrapper for the established Qwen artifact regression tests."""
    return _trim_model_terminal_silence(output_path, repo, "qwen3-tts")


def _apply_mlx_output_speed(output_path: Path, speed: float, family: str) -> bool:
    """Apply pitch-preserving tempo to a finished MLX-family WAV atomically.

    Qwen's current MLX implementation accepts ``speed`` without applying it,
    while VoxCPM2 has no numeric speed parameter at all. FFmpeg's ``atempo``
    changes duration while preserving pitch, so speaker identity survives and
    both short and already-joined long-form output obey one exact public speed
    control. Returns False for the 1.0 no-op.
    """
    engine = _POSTPROCESSED_SPEED_FAMILIES.get(family)
    if engine is None:
        raise ValueError(f"Pitch-preserving output speed is not configured for {family}")
    speed = max(0.5, min(float(speed), 2.0))
    if abs(speed - 1.0) < 1e-6:
        return False
    ffmpeg = _find_ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError(
            f"{engine} speed {speed:.2f}x needs FFmpeg for pitch-preserving tempo, "
            "but Voice Studio could not find FFmpeg. Run Update or reinstall Voice Studio."
        )

    import soundfile as sf

    source = sf.info(str(output_path))
    if source.frames <= 0 or source.samplerate <= 0 or source.channels <= 0:
        raise RuntimeError(f"{engine} produced an invalid WAV before speed adjustment")
    codec = {
        "PCM_16": "pcm_s16le",
        "PCM_24": "pcm_s24le",
        "PCM_32": "pcm_s32le",
        "FLOAT": "pcm_f32le",
        "DOUBLE": "pcm_f64le",
    }.get(source.subtype, "pcm_s16le")
    temporary = output_path.with_name(f".{output_path.stem}.tempo-{uuid.uuid4().hex}.wav")
    try:
        result = subprocess.run(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(output_path), "-filter:a", f"atempo={speed:.6f}",
                "-c:a", codec, str(temporary),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown FFmpeg error").strip()
            raise RuntimeError(f"{engine} speed adjustment failed: {detail[-800:]}")
        adjusted = sf.info(str(temporary))
        expected_frames = source.frames / speed
        tolerance = max(source.samplerate * 0.20, expected_frames * 0.08)
        if (
            adjusted.frames <= 0
            or adjusted.samplerate != source.samplerate
            or adjusted.channels != source.channels
            or abs(adjusted.frames - expected_frames) > tolerance
        ):
            raise RuntimeError(
                f"{engine} speed adjustment produced an invalid audio duration or format"
            )
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _apply_qwen_output_speed(output_path: Path, speed: float) -> bool:
    """Compatibility wrapper for the established Qwen regression surface."""
    return _apply_mlx_output_speed(output_path, speed, "qwen3-tts")


def _requested_output_duration_limit(params: dict) -> Optional[float]:
    raw = params.get("max_output_duration_s")
    if raw is None:
        return None
    limit = float(raw)
    if not math.isfinite(limit) or limit <= 0 or limit > 120:
        raise ValueError("max_output_duration_s must be between 0 and 120 seconds")
    return limit


def _qwen_max_tokens_for_duration(limit_s: float, speed: float) -> int:
    """Translate a final WAV ceiling into Qwen's 12.5-Hz audio-token limit."""
    native_seconds = limit_s * speed
    return max(1, min(1200, math.floor(native_seconds * 12.5)))


def _enforce_output_duration_limit(output_path: Path, params: dict) -> None:
    limit = _requested_output_duration_limit(params)
    if limit is None:
        return
    import soundfile as sf

    info = sf.info(str(output_path))
    if info.samplerate <= 0 or info.frames <= 0:
        raise RuntimeError("Generated audio has invalid duration metadata")
    duration = info.frames / info.samplerate
    if duration > limit + 0.001:
        raise RuntimeError(
            f"Generated audio is {duration:.3f}s, exceeding the requested "
            f"{limit:.3f}s maximum"
        )


_PACKAGE_DISTRIBUTIONS = {
    "mlx_lm": "mlx-lm",
    "mlx_audio": "mlx-audio",
    "mistral_common": "mistral-common",
    "f5_tts": "f5-tts",
}
_PACKAGE_MIN_VERSIONS = {"mistral_common": "1.10.0"}


def _probe_package(name: str) -> dict:
    try:
        import importlib
        mod = importlib.import_module(name)
        version = getattr(mod, "__version__", None)
        if not version:
            try:
                version = metadata.version(_PACKAGE_DISTRIBUTIONS.get(name, name))
            except metadata.PackageNotFoundError:
                version = None
        minimum = _PACKAGE_MIN_VERSIONS.get(name)
        compatible = True
        error = None
        if version and minimum:
            try:
                compatible = Version(version) >= Version(minimum)
            except InvalidVersion:
                compatible = False
            if not compatible:
                error = f"Version {version} is too old; {minimum} or newer is required"
        return {
            "installed": True,
            "compatible": compatible,
            "version": version,
            "minimum_version": minimum,
            "error": error,
        }
    except Exception as e:
        return {
            "installed": False,
            "compatible": False,
            "version": None,
            "minimum_version": _PACKAGE_MIN_VERSIONS.get(name),
            "error": f"{type(e).__name__}: {e}",
        }


def diagnostics() -> dict:
    """Per-package + per-engine health check. The frontend renders this as a
    checklist in the Generate tab so users see what's missing BEFORE they
    submit and hit a cryptic error."""
    pkg_results = []
    pkg_status: dict[str, bool] = {}
    for pkg, role in _PACKAGE_CHECKLIST:
        probe = _probe_package(pkg)
        pkg_results.append({"package": pkg, "role": role, **probe})
        pkg_status[pkg] = probe["installed"] and probe["compatible"]

    engine_results = []
    for family, requires in _ENGINE_REQUIREMENTS.items():
        missing = [p for p in requires if not pkg_status.get(p)]
        deps_ok = not missing
        wired = family in _WIRED_FAMILIES
        engine_results.append({
            "family": family,
            "requires": requires,
            "missing": missing,
            "deps_ok": deps_ok,           # all packages importable?
            "wired": wired,               # backend has a worker for this family?
            "ready": deps_ok and wired,   # both — only "ready" engines can generate
        })

    return {
        "device": _detect_device() if TTS_AVAILABLE else None,
        "packages": pkg_results,
        "engines": engine_results,
        "any_missing": any(not p["compatible"] for p in pkg_results),
        "ready_count": sum(1 for e in engine_results if e["ready"]),
        "total_engines": len(engine_results),
    }


def _release_device_memory(device: str) -> None:
    """Free GPU/MPS/MLX memory between generations so the next call doesn't OOM.

    Important on 16 GB M-series Macs: MLX maintains its own Metal allocation
    cache separate from PyTorch's MPS cache. Without clearing both, sequential
    voxcpm-mlx jobs accumulate activation tensors across calls and eventually
    blow past Metal's per-buffer cap (~9.5 GB on M4 16 GB) — see v1.2.7 fix."""
    try:
        import gc
        gc.collect()
    except Exception:
        pass
    try:
        import torch
        if device == "mps":
            torch.mps.empty_cache()
        elif device == "cuda":
            torch.cuda.empty_cache()
    except Exception:
        pass
    # MLX-specific cache release. Prefer the current API and keep the older
    # mlx.metal fallback for existing installations.
    # Without this, MLX retains buffers from the previous generation and the
    # next mlx-audio call's activations stack on top → Metal alloc OOM.
    try:
        import mlx.core as mx
        if hasattr(mx, "clear_cache"):
            mx.clear_cache()
        elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
            mx.metal.clear_cache()
    except Exception:
        pass


# ───────────── job model ─────────────

@dataclass
class GenerationJob:
    job_id: str
    mode: str                            # "txt2speech"
    params: dict
    state: str = "queued"
    progress: float = 0.0
    output_path: Optional[str] = None
    resolved_seed: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    model_revision: Optional[str] = None
    voice_revision: Optional[str] = None
    media_type: Optional[str] = None
    format: Optional[str] = None
    bytes: Optional[int] = None
    sha256: Optional[str] = None
    audio_duration_s: Optional[float] = None
    audio_duration_ms: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    channels: Optional[int] = None
    resource_usage: Optional[dict] = None  # worker-owned per-job resource evidence
    quality_validation: Optional[dict] = None  # redacted model-owned acceptance evidence
    quality_retry_count: int = 0
    quality_retry_history: list[dict] = field(default_factory=list)
    error_code: Optional[str] = None
    provider: Optional[str] = None          # cloud provider key (None = local engine)
    client_request_params: Optional[dict] = None  # immutable idempotency comparison
    provider_account_id: Optional[str] = None  # credential bound to this paid call
    provider_task_id: Optional[str] = None  # async provider task id — persisted so a
                                            # retry/restart RECALLS it instead of
                                            # re-submitting (never double-charge)
    provider_task_meta: dict = field(default_factory=dict)  # opaque recall URLs/tokens
    chunk_index: Optional[int] = None       # current long-form local segment (1-based)
    chunk_total: Optional[int] = None       # number of long-form local segments
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None

    def serialize(self) -> dict:
        duration = None
        if self.started_at is not None:
            end = self.finished_at if self.finished_at is not None else time.time()
            duration = max(0.0, end - self.started_at)
        public_params = {
            key: value for key, value in self.params.items()
            if not str(key).startswith("_")
        }
        audited_strategy = model_audits.input_limits(
            str(self.params.get("repo") or "")
        ).get("long_form_strategy")
        result = {
            "id": self.job_id,
            "mode": self.mode,
            "state": self.state,
            "provider": self.provider,
            "provider_account_id": self.provider_account_id,
            "provider_task_id": self.provider_task_id,
            "progress": self.progress,
            "chunk_index": self.chunk_index,
            "chunk_total": self.chunk_total,
            "params": public_params,
            "output_path": self.output_path,
            "output_url": f"/api/generate/jobs/{self.job_id}/audio" if self.output_path else None,
            "resolved_seed": self.resolved_seed,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": duration,
            "resource_usage": self.resource_usage,
            "quality_validation": self.quality_validation,
            "quality_retry_count": self.quality_retry_count,
            "quality_retry_history": self.quality_retry_history,
            "error_code": self.error_code,
        }
        return {
            **result,
            **final_tts_result(
                internal_model_id=self.params.get("repo"),
                model_revision=self.model_revision,
                voice_library_id=self.params.get("voice_library_id"),
                voice_revision=self.voice_revision,
                reference_audio_sha256=self.params.get("_reference_audio_sha256"),
                reference_source_sha256=self.params.get("_reference_source_sha256"),
                reference_preparation_revision=self.params.get(
                    "_reference_preparation_revision"
                ),
                reference_duration_s=self.params.get("_reference_duration_s"),
                long_form_strategy=audited_strategy or "unverified",
                chunk_total=self.chunk_total,
                runtime_s=duration,
                media_type=self.media_type,
                format=self.format,
                byte_size=self.bytes,
                sha256=self.sha256,
                audio_duration_s=self.audio_duration_s,
                audio_duration_ms=self.audio_duration_ms,
                sample_rate_hz=self.sample_rate_hz,
                channels=self.channels,
            ),
        }


# ───────────── manager ─────────────

class GenerationManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, GenerationJob] = {}
        # Cache one mlx-audio model at a time (loading is slow — 5-10s for
        # MLX 8-bit dequantization, longer for larger models). When the user
        # switches repos OR switches mlx-audio families (qwen3-tts → kokoro-mlx
        # → chatterbox-mlx etc.), we evict the old one to free Apple Silicon
        # unified memory. One cache slot is enough since unified memory is
        # shared — loading two large mlx-audio models would OOM anyway.
        self._mlx_audio_model = None
        self._mlx_audio_model_repo: Optional[str] = None
        # F5-TTS — single F5TTS instance cached per repo. Holds the flow-matching
        # transformer + VoCoS vocoder (~1.5 GB on disk, more at runtime). Heavy
        # cold-start because the vocoder also loads from HF.
        self._f5_tts_model = None
        self._f5_tts_model_repo: Optional[str] = None
        self._consecutive_memory_failures = 0
        self._last_memory_event: Optional[dict] = None
        self._restart_scheduled = False
        self._last_model_activity_at: Optional[float] = None
        self._load_history()
        self._resume_cloud_jobs()

    def is_available(self) -> bool:
        return TTS_AVAILABLE

    def list_jobs(self) -> list[GenerationJob]:
        return list(self._jobs.values())

    def get(self, job_id: str) -> Optional[GenerationJob]:
        return self._jobs.get(job_id)

    def has_active_jobs(self) -> bool:
        return any(job.state in ("queued", "running", "cancelling") for job in self._jobs.values())

    def loaded_model_keys(self) -> list[tuple[str, str]]:
        loaded: list[tuple[str, str]] = []
        if self._mlx_audio_model is not None and self._mlx_audio_model_repo:
            loaded.append((self._mlx_audio_model_repo, "tts-mlx"))
        if self._f5_tts_model is not None and self._f5_tts_model_repo:
            loaded.append((self._f5_tts_model_repo, "f5-tts"))
        return loaded

    @staticmethod
    def runtime_ready_for_family(family: str) -> bool:
        if family in MLX_AUDIO_FAMILIES:
            return _have_mlx_audio()
        if family == "f5-tts":
            return _have_f5_tts()
        return False

    def model_runtime_status(self, model_entry) -> dict:
        """Truthful per-model load, dependency, and live-memory inventory."""
        loaded_repos = {repo for repo, _runtime in self.loaded_model_keys()}
        loaded = model_entry.repo in loaded_repos
        cold_required = _required_free_memory_gb(model_entry, loaded=False)
        loaded_required = _required_free_memory_gb(model_entry, loaded=True)
        required = loaded_required if loaded else cold_required
        snapshot = _memory_snapshot()
        memory_eligible = None
        # A null catalog floor means the model is deliberately not yet memory
        # qualified. Keep the runtime free-memory guard below, but do not
        # manufacture a total-memory eligibility claim from missing evidence.
        if snapshot is not None and model_entry.min_unified_memory_gb is not None:
            memory_eligible = (
                float(snapshot["total_gb"]) >= float(model_entry.min_unified_memory_gb)
                and float(snapshot["available_gb"]) >= required
            )
        return {
            "loaded": loaded,
            "runtime_ready": self.runtime_ready_for_family(model_entry.family),
            "cold_load_required_free_memory_gb": cold_required,
            "loaded_required_free_memory_gb": loaded_required,
            "required_free_memory_gb": required,
            "memory_eligible": memory_eligible,
        }

    def last_activity_at(self) -> Optional[float]:
        return self._last_model_activity_at

    def release_memory_locked(self, reason: str = "manual") -> dict:
        if self.has_active_jobs():
            raise RuntimeError("voice generation is queued or running")
        return self._evict_loaded_models(reason=reason)

    def cancel(self, job_id: str) -> bool:
        """
        Queued jobs are blocked on `_GEN_LOCK` and can't check the cancel_event
        until they acquire the lock. To make the UI react instantly, flip
        queued → cancelled immediately. The worker still sees cancel_event when
        it eventually wakes up and exits cleanly. Running jobs only get the
        signal — TTS engines (Kokoro/VoxCPM/Bark/mlx-audio) don't honor
        mid-generation cancellation, so the worker discards the result after
        generation completes.
        """
        job = self._jobs.get(job_id)
        if job is None or job.state in ("done", "error", "cancelled"):
            return False
        job.cancel_event.set()
        if job.state == "queued":
            if job.provider and job.provider_task_id:
                try:
                    from . import providers as _P
                    pair = _P.adapter_for(job.params.get("repo", ""))
                    if pair is not None:
                        pair[0].adapter.cancel(
                            _P.get_api_key(job.provider),
                            job.provider_task_id,
                            job.provider_task_meta,
                        )
                except Exception:
                    pass
            job.state = "cancelled"
            job.finished_at = time.time()
            try:
                self._persist()
            except Exception:
                pass
        return True

    def clear_history(self) -> int:
        with self._lock:
            terminal = [jid for jid, j in self._jobs.items()
                        if j.state in ("done", "error", "cancelled")]
            for jid in terminal:
                self._jobs.pop(jid, None)
        self._persist()
        return len(terminal)

    def delete_job(self, job_id: str) -> bool:
        """Remove one finished job from history AND delete its audio file from disk.
        (The DELETE .../jobs/{id} route only cancels active jobs; this is for a
        finished job the user wants gone.)"""
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        if job.output_path:
            try:
                Path(job.output_path).unlink()
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[gen] delete_job unlink failed: {e}", file=sys.stderr, flush=True)
        self._persist()
        return True

    def output_stats(self) -> dict:
        """Total size + count of generated audio in the outputs folder — so the UI
        can show how much disk the outputs are using (history index and the files
        on disk can diverge)."""
        total = 0
        count = 0
        if OUTPUT_DIR.exists():
            for p in OUTPUT_DIR.iterdir():
                if (
                    p.name.startswith(".")
                    or not p.is_file()
                    or p.suffix.lower() not in _AUDIO_OUTPUT_SUFFIXES
                ):
                    continue
                try:
                    total += p.stat().st_size
                    count += 1
                except OSError:
                    pass
        return {"bytes": total, "count": count, "dir": str(OUTPUT_DIR.resolve())}

    def memory_status(self) -> dict:
        """Live memory and recovery state for the UI/Hub diagnostics panels."""
        return {
            "snapshot": _memory_snapshot(),
            "consecutive_failures": self._consecutive_memory_failures,
            "restart_scheduled": self._restart_scheduled,
            "last_event": self._last_memory_event,
            "service_supervised": self._service_installed(),
        }

    def prune_outputs(self, keep_last: int = 0, older_than_days: float = 0.0) -> dict:
        """Delete generated audio files to reclaim disk. Exactly one mode:
          - keep_last > 0: keep the newest N, delete the rest.
          - older_than_days > 0: delete files older than that many days.
        History entries for deleted files are trimmed too."""
        if not OUTPUT_DIR.exists():
            return {"deleted": 0, "freed_bytes": 0}
        audio_files = sorted(
            (
                p for p in OUTPUT_DIR.iterdir()
                if p.is_file() and p.suffix.lower() in _AUDIO_OUTPUT_SUFFIXES
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if keep_last > 0:
            to_delete = audio_files[keep_last:]
        elif older_than_days > 0:
            cutoff = time.time() - older_than_days * 86400
            to_delete = [p for p in audio_files if p.stat().st_mtime < cutoff]
        else:
            return {"deleted": 0, "freed_bytes": 0}
        freed = 0
        deleted = 0
        stems = set()
        for p in to_delete:
            try:
                sz = p.stat().st_size
                p.unlink()
                freed += sz
                deleted += 1
                stems.add(p.stem)
            except OSError:
                pass
        if stems:
            with self._lock:
                for jid in [j for j in self._jobs if j in stems]:
                    self._jobs.pop(jid, None)
            self._persist()
        return {"deleted": deleted, "freed_bytes": freed}

    def start_txt2speech(self, params: dict) -> GenerationJob:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        from . import providers as _P
        parsed = _P.parse_id(params.get("repo", ""))
        request_id = str(params.get("client_request_id") or "").strip()
        with self._lock:
            if request_id:
                existing = next((
                    item for item in self._jobs.values()
                    if str(item.params.get("client_request_id") or "").strip() == request_id
                ), None)
                if existing is not None:
                    original = existing.client_request_params or existing.params
                    if original != params:
                        raise ValueError(
                            "client_request_id was already used for a different request"
                        )
                    return existing
            job = GenerationJob(
                job_id=uuid.uuid4().hex[:12],
                mode="txt2speech",
                params=params,
                provider=(parsed[0] if parsed else None),
                client_request_params=dict(params) if request_id else None,
            )
            self._jobs[job.job_id] = job
        job.thread = threading.Thread(
            target=self._run_txt2speech,
            args=(job,),
            name=f"gen-{job.job_id}",
            daemon=True,
        )
        job.thread.start()
        return job

    @staticmethod
    def _service_installed() -> bool:
        root = Path(__file__).resolve().parents[2]
        return (root / "service" / ".installed").is_file()

    def _evict_loaded_models(self, reason: str = "memory-recovery") -> dict:
        """Drop both cached engines before a memory retry or supervised restart."""
        loaded = [list(item) for item in self.loaded_model_keys()]
        actions: list[str] = []
        for attr in ("_mlx_audio_model", "_f5_tts_model"):
            model = getattr(self, attr, None)
            if model is not None:
                setattr(self, attr, None)
                actions.append(f"cleared {attr.removeprefix('_')}")
            model = None
        self._mlx_audio_model_repo = None
        self._f5_tts_model_repo = None
        _release_device_memory("mps")
        actions.append("cleared Python, PyTorch, MLX and Metal allocator caches")
        return {"released": bool(loaded), "models": loaded, "actions": actions, "reason": reason}

    def _memory_preflight(self, model_entry) -> None:
        """Refuse a job that cannot safely fit in currently available memory."""
        snapshot = _memory_snapshot()
        if snapshot is None:
            print("[gen] memory guard unavailable; continuing without live RAM probe", flush=True)
            return

        minimum_total = float(getattr(model_entry, "min_unified_memory_gb", 0) or 0)
        total = float(snapshot["total_gb"])
        if total < minimum_total:
            raise MemoryGuardError(
                f"Memory guard paused this job: {model_entry.repo} requires at least "
                f"{minimum_total:g} GB unified memory, but this Mac reports {total:.1f} GB. "
                "Choose a smaller model or route the job to a larger Mac."
            )

        cached = (
            (model_entry.family in MLX_AUDIO_FAMILIES
             and self._mlx_audio_model_repo == model_entry.repo
             and self._mlx_audio_model is not None)
            or (model_entry.family == "f5-tts"
                and self._f5_tts_model_repo == model_entry.repo
                and self._f5_tts_model is not None)
        )
        required = _required_free_memory_gb(model_entry, loaded=cached)
        available = float(snapshot["available_gb"])
        if available < required:
            raise MemoryGuardError(
                f"Memory guard paused this job: {required:.1f} GB free is needed, "
                f"but only {available:.1f} GB is available. Close memory-heavy apps "
                "or choose a smaller model; the job was not sent to the engine."
            )
        print(
            f"[gen] memory guard: {available:.1f} GB free, "
            f"{required:.1f} GB reserved ({'cached model' if cached else 'model load'})",
            flush=True,
        )

    def _record_memory_failure(self, job: GenerationJob, exc: BaseException) -> None:
        self._consecutive_memory_failures += 1
        snapshot = _memory_snapshot()
        self._last_memory_event = {
            "time": time.time(),
            "job_id": job.job_id,
            "error": f"{type(exc).__name__}: {exc}",
            "snapshot": snapshot,
        }
        self._evict_loaded_models()
        print(
            f"[gen] memory failure {self._consecutive_memory_failures}/"
            f"{MEMORY_RESTART_FAILURES}; caches evicted",
            file=sys.stderr,
            flush=True,
        )
        if self._consecutive_memory_failures < MEMORY_RESTART_FAILURES:
            return
        if not self._service_installed():
            print(
                "[gen] repeated memory failures detected, but no supervised "
                "startup service is installed; keeping this Pinokio process alive",
                file=sys.stderr,
                flush=True,
            )
            return
        if self._restart_scheduled:
            return
        self._restart_scheduled = True
        self._persist()

        def _exit_for_launchd() -> None:
            print(
                "[gen] restarting Voice Studio after repeated memory failures; "
                "launchd KeepAlive will bring it back",
                file=sys.stderr,
                flush=True,
            )
            os._exit(75)

        threading.Timer(0.75, _exit_for_launchd).start()

    # ----- worker -----

    @staticmethod
    def _is_qwen_clone_job(job: GenerationJob) -> bool:
        return qwen_quality.is_qwen_base_clone(
            str(job.params.get("repo") or ""),
            job.params,
        )

    def _record_qwen_quality_attempt(
        self,
        job: GenerationJob,
        *,
        evidence: dict,
        accepted: bool,
        rejection_code: Optional[str] = None,
    ) -> None:
        """Keep redacted evidence for every Qwen quality attempt.

        The final ``quality_validation`` field intentionally remains the
        latest result for compatibility.  The history makes a one-retry
        failure auditable without retaining the transcript, audio, or a
        filesystem path.
        """
        if not self._is_qwen_clone_job(job):
            return
        record = {
            **dict(evidence or {}),
            "attempt": len(job.quality_retry_history) + 1,
            "accepted": bool(accepted),
        }
        if rejection_code:
            record["rejection_code"] = rejection_code
        job.quality_retry_history.append(record)

    @staticmethod
    def _qwen_job_duration_limit(job: GenerationJob) -> float:
        text = str(job.params.get("text") or "")
        speed = float(job.params.get("speed") or 1.0)
        override = job.params.get("_qwen_section_max_characters")
        chunks = _internal_mlx_text_chunks(
            "qwen3-tts",
            str(job.params.get("repo") or ""),
            text,
            max_chars_override=int(override) if override else None,
        ) or [text]
        pauses = max(0, len(chunks) - 1) * _long_form_join_pause_s(
            "qwen3-tts", str(job.params.get("repo") or "")
        )
        return round(
            sum(qwen_quality.automatic_duration_limit(chunk, speed) for chunk in chunks)
            + pauses,
            3,
        )

    def _validate_qwen_output_locked(
        self,
        job: GenerationJob,
        output_path: Path,
    ) -> None:
        """Accept a Qwen clone only when Whisper agrees with the request."""
        if not self._is_qwen_clone_job(job):
            return
        if not job.params.get("_qwen_reference_validation"):
            raise qwen_quality.QwenQualityError(
                "QWEN_REFERENCE_VALIDATION_REQUIRED",
                "Qwen3-TTS reference validation evidence is missing.",
                {"validator_revision": qwen_quality.VALIDATOR_REVISION},
            )

        # Qwen and Whisper must never co-reside on unified memory. The rejected
        # local artifact is certain and unpaid, so it is safe to validate and,
        # if necessary, regenerate it once.
        self._evict_loaded_models("qwen-output-validation")
        from .transcription import manager as stt_manager

        try:
            result = stt_manager.transcribe_locked(
                str(output_path),
                model_repo=qwen_quality.WHISPER_REPO,
                language=job.params.get("language"),
                word_timestamps=True,
            )
            job.quality_validation = qwen_quality.validate_output(
                str(job.params.get("text") or ""),
                result,
                max_duration_s=self._qwen_job_duration_limit(job),
            )
        except qwen_quality.QwenQualityError:
            raise
        except Exception as exc:
            print(
                f"[gen] Qwen output validator unavailable: {type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
            raise qwen_quality.QwenQualityError(
                "QWEN_OUTPUT_VALIDATION_UNAVAILABLE",
                "Whisper Large could not validate the Qwen output.",
                {
                    "validator_revision": qwen_quality.VALIDATOR_REVISION,
                    "error_type": type(exc).__name__,
                },
            ) from exc
        finally:
            stt_manager.release_memory_locked("qwen-output-validation-complete")

    def _validate_qwen_reference_locked(self, job: GenerationJob) -> None:
        """Validate the exact reference inside the already durable local job."""
        if not self._is_qwen_clone_job(job):
            return
        if job.params.get("_qwen_reference_validation"):
            return
        private_path = str(job.params.get("_reference_audio_path") or "").strip()
        transcript = str(job.params.get("ref_transcript") or "").strip()
        if private_path:
            reference_path = Path(private_path)
        else:
            from . import voices as voices_module

            voice_id = str(job.params.get("voice_library_id") or "").strip()
            reference_path = voices_module.library.reference_path(voice_id)
            if not transcript:
                transcript = voices_module.library.transcript(voice_id) or ""
        if reference_path is None or not reference_path.is_file():
            raise qwen_quality.QwenQualityError(
                "QWEN_REFERENCE_AUDIO_UNAVAILABLE",
                "The selected Qwen reference voice is unavailable.",
                {"validator_revision": qwen_quality.VALIDATOR_REVISION},
            )
        if not transcript.strip():
            raise qwen_quality.QwenQualityError(
                "QWEN_REFERENCE_TRANSCRIPT_REQUIRED",
                "Qwen3-TTS Base needs the exact transcript for its reference audio.",
                {"validator_revision": qwen_quality.VALIDATOR_REVISION},
            )

        cache_key = qwen_quality.reference_cache_key(reference_path, transcript)
        evidence = qwen_quality.cached_reference_evidence(cache_key)
        if evidence is None:
            self._evict_loaded_models("qwen-reference-validation")
            from .transcription import manager as stt_manager

            try:
                result = stt_manager.transcribe_locked(
                    str(reference_path),
                    model_repo=qwen_quality.WHISPER_REPO,
                    language=job.params.get("language"),
                    word_timestamps=True,
                )
                evidence = qwen_quality.validate_reference(transcript, result)
                qwen_quality.save_reference_evidence(cache_key, evidence)
            except qwen_quality.QwenQualityError:
                raise
            except Exception as exc:
                print(
                    f"[gen] Qwen reference validator unavailable: {type(exc).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
                raise qwen_quality.QwenQualityError(
                    "QWEN_REFERENCE_VALIDATION_UNAVAILABLE",
                    "Whisper Large could not validate the Qwen reference.",
                    {
                        "validator_revision": qwen_quality.VALIDATOR_REVISION,
                        "error_type": type(exc).__name__,
                    },
                ) from exc
            finally:
                stt_manager.release_memory_locked("qwen-reference-validation-complete")
        job.params["_qwen_reference_validation"] = evidence

    def _run_txt2speech(self, job: GenerationJob) -> None:
        # NOTE: don't re-set `job.state = "queued"` here. The dataclass default
        # already initialised it to "queued", and `cancel()` may legitimately
        # have flipped it to "cancelled" between submit_job() and this thread
        # being scheduled. Re-asserting "queued" outside the lock clobbers that
        # cancel decision — the cancel_event flag still survives, but the UI
        # would see the job pop back to "queued" until the worker eventually
        # acquired the lock (potentially minutes later).
        with _GEN_LOCK:
            if job.cancel_event.is_set():
                job.state = "cancelled"
                job.finished_at = time.time()
                self._persist()
                return

            job.state = "running"
            job.started_at = time.time()
            if not job.provider:
                self._last_model_activity_at = job.started_at
            job.progress = 0.05          # move the bar off zero the moment work starts
            telemetry = None
            memory_failure_seen = False
            print(
                f"[gen] starting {job.job_id}: repo={job.params.get('repo')} "
                f"text_chars={len(str(job.params.get('text') or ''))} "
                f"private_reference={bool(job.params.get('_reference_audio_path'))}",
                flush=True,
            )

            if not TTS_AVAILABLE and not job.provider:
                job.state = "error"
                job.error = f"TTS engine not installed: {TTS_IMPORT_ERROR}"
                job.finished_at = time.time()
                self._persist()
                return

            if not job.provider:
                telemetry = resource_telemetry.JobResourceSampler(
                    lambda value: setattr(job, "resource_usage", value)
                ).start()

            output_path: Optional[Path] = None
            memory_retries = 0
            quality_retries = 0
            while True:
                try:
                    if job.provider:
                        output_path = self._run_cloud(job)
                        _enforce_output_duration_limit(output_path, job.params)
                    else:
                        final_output_path = OUTPUT_DIR / f"{job.job_id}.wav"
                        output_path = OUTPUT_DIR / f".{job.job_id}.{uuid.uuid4().hex}.partial.wav"
                        self._validate_qwen_reference_locked(job)
                        self._dispatch_txt2speech(job, output_path)
                        _enforce_output_duration_limit(output_path, job.params)
                        self._validate_qwen_output_locked(job, output_path)
                        self._record_qwen_quality_attempt(
                            job,
                            evidence=job.quality_validation or {},
                            accepted=True,
                        )
                        self._record_local_revision_evidence(job)
                        self._record_final_audio_evidence(job, output_path)
                        if not job.cancel_event.is_set():
                            os.replace(output_path, final_output_path)
                            output_path = final_output_path
                    if job.cancel_event.is_set():
                        if output_path is not None:
                            output_path.unlink(missing_ok=True)
                        job.state = "cancelled"
                    else:
                        job.output_path = str(output_path.resolve())
                        job.progress = 1.0
                        job.state = "done"
                        if not job.provider:
                            self._consecutive_memory_failures = 0
                        print(f"[gen] done {job.job_id} → {output_path}", flush=True)
                    break
                except Exception as e:
                    if output_path is not None:
                        try:
                            output_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                    if (
                        not job.provider
                        and isinstance(e, qwen_quality.QwenQualityError)
                        and e.code in qwen_quality.RETRYABLE_OUTPUT_CODES
                        and self._is_qwen_clone_job(job)
                        and quality_retries < 1
                    ):
                        quality_retries += 1
                        job.quality_retry_count = quality_retries
                        job.quality_validation = {
                            **e.evidence,
                            "accepted": False,
                            "rejection_code": e.code,
                        }
                        self._record_qwen_quality_attempt(
                            job,
                            evidence=e.evidence,
                            accepted=False,
                            rejection_code=e.code,
                        )
                        original_seed = (
                            job.resolved_seed
                            if job.resolved_seed is not None
                            else int(job.params.get("seed") or 0)
                        )
                        job.params["_qwen_attempt_seed"] = (
                            int(original_seed) + 1
                        ) % (2**32)
                        job.params["_qwen_section_max_characters"] = (
                            qwen_quality.RETRY_SECTION_MAX_CHARACTERS
                        )
                        self._evict_loaded_models("qwen-quality-retry")
                        print(
                            f"[gen] rejected Qwen clone {job.job_id} ({e.code}); "
                            "retrying once with a new seed and shorter sections",
                            file=sys.stderr,
                            flush=True,
                        )
                        continue
                    if (
                        not job.provider
                        and _is_memory_failure(e)
                        and memory_retries < MEMORY_RETRY_LIMIT
                    ):
                        memory_retries += 1
                        memory_failure_seen = True
                        print(
                            f"[gen] memory failure on {job.job_id}; evicting models "
                            f"and retrying once ({memory_retries}/{MEMORY_RETRY_LIMIT})",
                            file=sys.stderr,
                            flush=True,
                        )
                        self._record_memory_failure(job, e)
                        if self._restart_scheduled:
                            job.state = "error"
                            job.error = (
                                "Generation hit repeated memory failures. Voice Studio "
                                "is restarting automatically to recover."
                            )
                            break
                        continue
                    if job.cancel_event.is_set():
                        job.state = "cancelled"
                    else:
                        job.state = "error"
                        if isinstance(e, qwen_quality.QwenQualityError):
                            job.error_code = e.code
                            job.quality_validation = {
                                **e.evidence,
                                "accepted": False,
                                "rejection_code": e.code,
                            }
                            self._record_qwen_quality_attempt(
                                job,
                                evidence=e.evidence,
                                accepted=False,
                                rejection_code=e.code,
                            )
                        job.error = f"{type(e).__name__}: {e}"
                        if not isinstance(e, MemoryGuardError) and _is_memory_failure(e):
                            memory_failure_seen = True
                            self._record_memory_failure(job, e)
                        print(f"[gen] error {job.job_id}: {job.error}", file=sys.stderr, flush=True)
                        traceback.print_exc()
                    break
            job.finished_at = time.time()
            if not job.provider:
                self._last_model_activity_at = job.finished_at
                if job.state != "done":
                    self._evict_loaded_models("failed-or-cancelled-generation")
                if telemetry is not None:
                    job.resource_usage = telemetry.finish(
                        state=job.state,
                        memory_failure=memory_failure_seen,
                        restart_scheduled=self._restart_scheduled,
                        model_retained=(
                            job.state == "done"
                            and bool(getattr(self, "_loaded_model", None))
                        ),
                    )
            self._persist()

    @staticmethod
    def _record_local_revision_evidence(job: GenerationJob) -> None:
        """Fence supported local output to exact cached weights and voice bytes.

        GenStudio validates this evidence before publishing the final asset. A
        preset voice is versioned by the immutable model snapshot plus its
        engine-owned preset key; a cloned voice is versioned by the digest of
        the exact reference audio Voice Studio used.
        """
        if job.provider:
            return
        repo = str(job.params.get("repo") or "").strip()
        normalized_repo = repo.lower()
        is_qwen = "qwen3-tts" in normalized_repo
        is_voxcpm = "voxcpm2" in normalized_repo
        is_kokoro = "kokoro" in normalized_repo
        is_chatterbox = "chatterbox" in normalized_repo
        is_fish = "fish-audio-s2-pro" in normalized_repo
        is_omnivoice = "omnivoice" in normalized_repo
        if not (
            is_qwen or is_voxcpm or is_kokoro or is_chatterbox
            or is_fish or is_omnivoice
        ):
            return
        revision = cache.snapshot_revision(repo)
        if not revision:
            raise RuntimeError("Local TTS model revision evidence is unavailable")
        job.model_revision = revision
        if is_kokoro:
            voice = str(job.params.get("voice") or "").strip().lower()
            if not voice:
                raise RuntimeError("Kokoro preset voice evidence is unavailable")
            job.voice_revision = f"{revision}:preset:{voice}"
            return
        mode = _qwen3_mode_from_repo(repo) if is_qwen else "voxcpm"
        if is_qwen and mode == "custom":
            speaker = str(job.params.get("preset_speaker") or "").strip().lower()
            if not speaker:
                raise RuntimeError("Qwen3-TTS preset voice evidence is unavailable")
            job.voice_revision = f"{revision}:preset:{speaker}"
            return
        voice_id = str(job.params.get("voice_library_id") or "").strip()
        private_revision = str(
            job.params.get("_reference_audio_sha256") or ""
        ).strip().lower()
        if (
            (is_qwen and mode == "clone")
            or (is_voxcpm and (voice_id or private_revision))
            or is_chatterbox
            or (is_fish and (voice_id or private_revision))
            or (is_omnivoice and (voice_id or private_revision))
        ):
            if private_revision:
                job.voice_revision = private_revision
                return
            from . import voices as voices_module

            if not voice_id:
                raise RuntimeError("Cloned voice revision evidence is unavailable")
            voice = voices_module.library.get(voice_id)
            if voice is None or not voice.audio_sha256:
                raise RuntimeError("Cloned voice revision evidence is unavailable")
            job.voice_revision = voice.audio_sha256.lower()

    @staticmethod
    def _record_qwen_revision_evidence(job: GenerationJob) -> None:
        """Compatibility wrapper retained for existing Qwen callers/tests."""
        GenerationManager._record_local_revision_evidence(job)

    @staticmethod
    def _record_final_audio_evidence(job: GenerationJob, output_path: Path) -> None:
        """Derive immutable media facts from the one final local WAV."""
        import soundfile as sf

        info = sf.info(str(output_path))
        if (
            info.format != "WAV"
            or info.frames <= 0
            or info.samplerate <= 0
            or info.channels not in (1, 2)
        ):
            raise RuntimeError("Generated audio is not a valid mono/stereo WAV")
        payload = output_path.read_bytes()
        if not payload.startswith(b"RIFF") or payload[8:12] != b"WAVE":
            raise RuntimeError("Generated audio has an invalid WAV container")
        duration_s = info.frames / info.samplerate
        job.media_type = "audio/wav"
        job.format = "wav"
        job.bytes = len(payload)
        job.sha256 = hashlib.sha256(payload).hexdigest()
        job.audio_duration_s = round(duration_s, 6)
        job.audio_duration_ms = round(duration_s * 1000)
        job.sample_rate_hz = info.samplerate
        job.channels = info.channels

    def _run_cloud(self, job: "GenerationJob") -> Path:
        """Cloud-provider synthesis. Returns the written audio Path.

        SELF-HEALING: async providers submit once, persist the task id, then poll
        that same id to completion — a retry re-polls instead of re-submitting, so
        a cloud call is never billed twice. ElevenLabs is synchronous: one atomic
        call returns the audio (nothing to recall)."""
        from . import providers as P
        pair = P.adapter_for(job.params.get("repo", ""))
        if pair is None:
            raise ValueError(f"Unknown cloud model: {job.params.get('repo')}")
        prov, model = pair
        if not P.is_live(prov.key):
            raise RuntimeError(
                f"{prov.name} isn't ready — add an API key and enable paid usage "
                f"for it in Settings.")
        text = job.params.get("text", "")
        voice = job.params.get("voice") or job.params.get("voice_id") or ""
        # Cloud TTS bills per character — hard guardrail so a runaway caller
        # (e.g. a Story Studio loop) can't rack up a surprise bill.
        cap = 5000
        if len(text) > cap:
            raise ValueError(
                f"Text is {len(text)} characters — over the {cap}-char safety cap "
                f"for cloud providers. Split it into shorter requests.")
        adapter = prov.adapter
        audio = None
        mime = None
        if prov.key == "elevenlabs":
            audio, mime = self._run_elevenlabs_pool(job, adapter, model, text, voice)
        else:
            api_key = P.get_api_key(prov.key)
        if prov.key != "elevenlabs" and adapter.is_async:
            if not job.provider_task_id:
                sub = adapter.submit(api_key, text, model, voice, job.params)
                job.provider_task_id = sub.task_id
                job.provider_task_meta = dict(sub.metadata or {})
                self._persist()   # persist the task id BEFORE polling — recall-safe
            while True:
                if job.cancel_event.is_set():
                    try:
                        adapter.cancel(
                            api_key, job.provider_task_id, job.provider_task_meta
                        )
                    except Exception:
                        pass
                    return OUTPUT_DIR / f"{job.job_id}.mp3"
                res = adapter.poll(
                    api_key, job.provider_task_id, job.provider_task_meta
                )
                if res.progress:
                    job.progress = max(job.progress, min(0.95, res.progress))
                if res.done:
                    if res.error:
                        raise RuntimeError(res.error)
                    audio, mime = res.audio, res.mime
                    break
                time.sleep(2.0)
        elif prov.key != "elevenlabs":
            job.progress = 0.2
            audio, mime = adapter.synthesize(api_key, text, model, voice, job.params)
        if not audio:
            raise RuntimeError(f"{prov.name} returned no audio data.")
        ext = "mp3" if ("mpeg" in (mime or "") or "mp3" in (mime or "")) else "wav"
        out = OUTPUT_DIR / f"{job.job_id}.{ext}"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio)
        return out

    def _run_elevenlabs_pool(self, job: "GenerationJob", adapter, model: str,
                             text: str, direct_voice: str) -> tuple[bytes, str]:
        """Choose one quota-ready account and its account-specific voice.

        Definite pre-generation failures can fail over to another account.
        A dropped response is first recovered from ElevenLabs History by the
        adapter and is never blindly resubmitted, preventing duplicate charges.
        """
        from . import providers as P, voices as V

        accounts = P.elevenlabs_accounts()
        if not accounts:
            raise RuntimeError("No ElevenLabs accounts are configured.")

        library_id = str(job.params.get("voice_library_id") or "").strip()
        voices_by_account: dict[str, str] = {}
        allowed_ids: Optional[set[str]] = None
        if library_id:
            library_voice = V.library.get(library_id)
            if library_voice is None:
                raise ValueError(f"Voice {library_id} not found in the library.")
            exact = {
                str(tag.get("account_id") or "").strip(): str(tag.get("voice_id") or "").strip()
                for tag in (library_voice.providers or [])
                if tag.get("provider") == "elevenlabs" and tag.get("account_id")
            }
            legacy = next((
                str(tag.get("voice_id") or "").strip()
                for tag in (library_voice.providers or [])
                if tag.get("provider") == "elevenlabs" and not tag.get("account_id")
            ), "")
            primary_id = accounts[0]["id"]
            for account in accounts:
                mapped = exact.get(account["id"])
                if not mapped and legacy and (
                    len(accounts) == 1 or account["id"] == primary_id
                ):
                    mapped = legacy
                if mapped:
                    voices_by_account[account["id"]] = mapped
            allowed_ids = set(voices_by_account)
            if not allowed_ids:
                raise ValueError(
                    f"Voice {library_voice.name!r} has no ElevenLabs mapping for "
                    "an account in the pool. Edit the voice and map each account."
                )
        else:
            if len(accounts) > 1:
                raise ValueError(
                    "Multiple ElevenLabs accounts are configured. Send voice_library_id "
                    "so Voice Studio can choose the matching per-account voice ID."
                )
            if not direct_voice:
                raise ValueError("ElevenLabs needs a mapped library voice.")
            voices_by_account[accounts[0]["id"]] = direct_voice
            allowed_ids = {accounts[0]["id"]}

        candidates = P.elevenlabs_candidates(allowed_ids)
        if not candidates:
            raise RuntimeError(
                "No enabled ElevenLabs account with available credits and a matching "
                "voice mapping is ready. Refresh the account pool in Settings."
            )

        failures = []
        for account in candidates:
            account_id = account["id"]
            voice_id = voices_by_account[account_id]
            job.provider_account_id = account_id
            job.params["provider_account_id"] = account_id
            job.params["provider_account_label"] = account["label"]
            job.params["voice"] = voice_id
            self._persist()
            for attempt in range(2):
                try:
                    job.progress = 0.2
                    audio, mime = adapter.synthesize(
                        account["api_key"], text, model, voice_id, job.params
                    )
                    P.record_elevenlabs_success(account_id, len(text))
                    return audio, mime
                except P.ProviderResultUncertain:
                    raise
                except P.ProviderRequestError as exc:
                    P.report_elevenlabs_error(account_id, exc)
                    failures.append(f"{account['label']}: {exc}")
                    # Invalid auth, exhausted quota, rate/concurrency pressure,
                    # and an account-local missing voice are safe to try on the
                    # next mapped account. Invalid request bodies are not.
                    if exc.status_code in (401, 402, 403, 404, 429):
                        break
                    if exc.status_code >= 500 and attempt == 0:
                        time.sleep(2.0)
                        continue
                    if exc.status_code >= 500:
                        break
                    raise
                except (httpx.ConnectError, httpx.ConnectTimeout,
                        httpx.PoolTimeout) as exc:
                    P.report_elevenlabs_error(account_id, exc)
                    failures.append(f"{account['label']}: {type(exc).__name__}")
                    if attempt == 0:
                        time.sleep(2.0)
                        continue
                    break

        raise RuntimeError(
            "Every eligible ElevenLabs account failed: " + "; ".join(failures[-5:])
        )

    def _dispatch_txt2speech(self, job: GenerationJob, output_path: Path) -> None:
        """Pick the right backend pipeline based on model family."""
        params = job.params
        repo = params["repo"]
        model = catalog.get_model(repo)
        if model is None:
            raise ValueError(f"Repo {repo} is not in the catalog")
        if cache.cache_state(repo) != "cached":
            raise ValueError(f"Model {repo} is not fully cached locally — download it first")

        family = model.family
        self._memory_preflight(model)
        if family == "f5-tts":
            if not _have_f5_tts():
                raise RuntimeError(
                    "The `f5-tts` package isn't installed. Run 'Install Generation' "
                    "from the Pinokio sidebar (this installs f5-tts + vocos + cached_path)."
                )
            self._generate_f5_tts(job, model, output_path)
        elif family in MLX_AUDIO_FAMILIES:
            if not _have_mlx_audio():
                raise RuntimeError(
                    "The `mlx-audio` package isn't installed. Run 'Install Generation' "
                    "from the Pinokio sidebar (this installs the MLX + mlx-audio stack)."
                )
            self._generate_mlx_audio(job, model, output_path)
        else:
            raise NotImplementedError(f"No worker implemented for family '{family}'.")

    # ──────────────────────────────────────────────────────────────────────
    # mlx-audio worker — shared across qwen3-tts, voxcpm-mlx, kokoro-mlx,
    # chatterbox-mlx, spark-tts-mlx, orpheus, and any future mlx-audio-backed
    # family.
    #
    # Architecture:
    # 1. _mlx_audio_snapshot_path: find the HF cache snapshot folder for a repo
    # 2. _mlx_audio_get_model: lazy-load + cache (one slot, evicts on switch)
    # 3. _generate_mlx_audio: main entry — calls the right mode resolver to
    #    build gen_kwargs, then invokes mlx-audio.generate_audio()
    # 4. _resolve_mlx_kwargs_*: per-mode kwarg builders (see MLX_AUDIO_FAMILIES)
    #
    # To add a new mlx-audio family: register it in MLX_AUDIO_FAMILIES, and if
    # its kwarg shape doesn't match an existing mode resolver, add a new one.
    # ──────────────────────────────────────────────────────────────────────

    def _mlx_audio_snapshot_path(self, repo: str) -> Path:
        """Find the actual on-disk snapshot folder for a cached repo.

        Our HF cache has `models--<owner>--<repo>/snapshots/<rev>/...`. The rev
        is either a real commit SHA (downloaded via huggingface_hub) or our
        synthetic 'main' (from the flat-folder import path). We just take the
        first non-hidden subfolder."""
        repo_dir = cache.repo_cache_dir(repo)
        snapshots = repo_dir / "snapshots"
        if not snapshots.exists():
            raise RuntimeError(
                f"No snapshots folder for {repo} at {snapshots}. "
                "Re-download from the Models tab or re-import."
            )
        candidates = [s for s in snapshots.iterdir()
                      if s.is_dir() and not s.name.startswith(".")]
        if not candidates:
            raise RuntimeError(f"No snapshot subfolder under {snapshots}")
        return candidates[0]

    def _mlx_audio_get_model(self, repo: str):
        """Lazy-load and cache the mlx-audio model for `repo`. Evicts any
        previously-loaded model when switching repos so unified memory is only
        ever holding one mlx-audio model at a time — important on Apple Silicon
        where all GPU memory comes out of the same pool as system RAM.

        One slot is enough across ALL mlx-audio families (qwen3-tts, voxcpm-mlx,
        kokoro-mlx, etc.) — loading two large mlx-audio models simultaneously
        would OOM anyway."""
        if self._mlx_audio_model_repo == repo and self._mlx_audio_model is not None:
            return self._mlx_audio_model

        # Evict previous model — important on Apple Silicon to avoid OOM.
        if self._mlx_audio_model is not None:
            print(f"[gen] evicting cached mlx-audio model ({self._mlx_audio_model_repo})", flush=True)
            try:
                del self._mlx_audio_model
            except Exception:
                pass
            self._mlx_audio_model = None
            self._mlx_audio_model_repo = None
            _release_device_memory("mps")

        from mlx_audio.tts.utils import load_model
        snapshot_path = self._mlx_audio_snapshot_path(repo)
        print(f"[gen] loading mlx-audio model from {snapshot_path}", flush=True)
        # IMPORTANT: pass the Path object, NOT str(snapshot_path).
        # mlx-audio's get_model_name_parts walks Path.parts to extract name
        # hints (finds the `models--mlx-community--Spark-TTS-...` segment and
        # parses "spark", "tts", etc.). When given a string it only takes the
        # last "/" segment — which is just the snapshot hash like
        # "be15d8bf101a4a400c568b387fb69dce0d37239b" — and the dispatch falls
        # back to config.json's model_type. Spark-TTS reports `qwen2` there
        # (its LM backbone), no `mlx_audio.tts.models.qwen2` exists, and you
        # get `ValueError: Model type qwen2 not supported for tts.`
        # See v1.2.8 fix.
        # Voxtral's tekken metadata includes voice_num_audio_tokens. mlx-audio
        # reads that field itself, but mistral-common <=1.9 rejects the extra
        # AudioConfig kwarg before the tokenizer can load. Ignore it only while
        # loading this model; mlx-audio already preserved the mapping above.
        audio_config_cls = None
        original_audio_config_init = None
        entry = catalog.get_model(repo)
        if entry is not None and entry.family == "kokoro-mlx":
            _backport_kokoro_sinegen_length_alignment()
        if entry is not None and entry.family == "voxtral-tts":
            try:
                import inspect
                from mistral_common.tokens.tokenizers.tekken import AudioConfig
                if "voice_num_audio_tokens" not in inspect.signature(AudioConfig).parameters:
                    audio_config_cls = AudioConfig
                    original_audio_config_init = AudioConfig.__init__

                    def _compatible_audio_config_init(instance, *args,
                                                      voice_num_audio_tokens=None, **kwargs):
                        return original_audio_config_init(instance, *args, **kwargs)

                    AudioConfig.__init__ = _compatible_audio_config_init
            except (ImportError, TypeError, ValueError):
                pass
        try:
            model = load_model(snapshot_path)
        finally:
            if audio_config_cls is not None and original_audio_config_init is not None:
                audio_config_cls.__init__ = original_audio_config_init
        if entry is not None and entry.family == "voxcpm-mlx":
            # Backport mlx-audio 3b37f335 without advancing the shared pin by
            # 93 unrelated commits: materialize this lazy constant before the
            # cached model is reused by a later generation worker thread.
            import mlx.core as mx
            decoder = getattr(getattr(model, "audio_vae", None), "decoder", None)
            sr_boundaries = getattr(decoder, "_sr_boundaries", None)
            if sr_boundaries is not None:
                mx.eval(sr_boundaries)
        self._mlx_audio_model = model
        self._mlx_audio_model_repo = repo
        self._last_model_activity_at = time.time()
        return model

    def _generate_mlx_audio(self, job: GenerationJob, model_entry, output_path: Path) -> None:
        """
        Unified worker for every mlx-audio-backed TTS family.

        Per-family behavior is configured in MLX_AUDIO_FAMILIES — this function
        is purely scaffolding (load model, build kwargs, call generate_audio,
        save output). The mode resolvers below decide which kwargs to pass.

        mlx-audio's `generate_audio()` writes wav files to an output directory
        rather than returning bytes. We request one joined file so newline and
        sentence segmentation never drops everything after the first segment.
        """
        import tempfile
        from mlx_audio.tts.generate import generate_audio

        params = job.params
        family = model_entry.family
        family_config = MLX_AUDIO_FAMILIES.get(family)
        if family_config is None:
            # Defensive — caller checks this, but keep the guard for tests.
            raise RuntimeError(f"Family {family!r} not in MLX_AUDIO_FAMILIES")

        text = (params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        speed = float(params.get("speed", 1.0))
        speed = max(0.5, min(speed, 2.0))

        gen_kwargs: dict = {"text": text}
        output_duration_limit = _requested_output_duration_limit(params)
        qwen_clone = qwen_quality.is_qwen_base_clone(model_entry.repo, params)
        if qwen_clone:
            # Model-owned default: callers no longer need to remember a safety
            # ceiling. A supplied compatibility limit may tighten it further.
            gen_kwargs["max_tokens"] = qwen_quality.max_tokens_for_text(text, speed)
            if output_duration_limit is not None:
                gen_kwargs["max_tokens"] = min(
                    gen_kwargs["max_tokens"],
                    _qwen_max_tokens_for_duration(output_duration_limit, speed),
                )
        elif family == "qwen3-tts" and output_duration_limit is not None:
            gen_kwargs["max_tokens"] = _qwen_max_tokens_for_duration(output_duration_limit, speed)
        # VoxCPM2 has no numeric speed parameter; its natural-language prompt
        # can shape delivery, while exact requested tempo is applied to the
        # finished WAV below. Passing speed upstream would be silently ignored.
        if family not in {"voxcpm-mlx", "bark", "vibevoice", "fish-audio-mlx", "arktts", "moss-tts-nano", "echo-tts", "omnivoice"}:
            # Qwen accepts this argument but does not apply it upstream. Keep
            # native generation at 1.0 and adjust the finished WAV below.
            gen_kwargs["speed"] = 1.0 if family == "qwen3-tts" else speed
        elif family == "fish-audio-mlx":
            # Fish applies its native speed per generated segment. Keep that at
            # 1.0 so the public speed control is applied exactly once to the
            # fully joined WAV below.
            gen_kwargs["speed"] = 1.0
        if family == "vibevoice":
            # At 7.5 acoustic frames per second this permits about nine minutes
            # per private section. The model normally stops at EOS sooner.
            gen_kwargs["max_tokens"] = _VIBEVOICE_MAX_TOKENS
        if family == "fish-audio-mlx":
            # Prevent a second model-owned split inside Voice Studio's private
            # 300-character sections. Fish still stops naturally at EOS.
            gen_kwargs["chunk_length"] = 100000

        # Dispatch to the per-mode resolver to populate voice / clone / instruct
        # kwargs. Each resolver may raise ValueError if required inputs are missing.
        mode = family_config["mode"]
        mode_label = self._resolve_mlx_kwargs(mode, family, model_entry, params, gen_kwargs)

        if family == "arktts":
            # Confirmed via a real local generation (v1.27.20): arktts.py builds
            # GenerationResult.prompt={"text":..., "ref_text":...} instead of the
            # {"tokens":..., "tokens-per-sec":...} shape every other mlx-audio
            # engine uses. generate_audio()'s verbose block (default True) reads
            # result.prompt['tokens-per-sec'] unconditionally and raises KeyError
            # before the WAV is ever written — turning EVERY Audio8 generation
            # into a silent failure. Voice Studio's own [gen] print lines already
            # cover this family; suppressing mlx-audio's internal verbose output
            # is a safe, narrowly-scoped workaround pending an upstream fix.
            gen_kwargs["verbose"] = False

        # Optional cfg knobs — currently only VoxCPM2 uses them.
        if family_config.get("uses_cfg"):
            gen_kwargs["cfg_value"] = max(0.5, min(float(params.get("cfg_value", 2.0)), 6.0))
            gen_kwargs["inference_timesteps"] = max(4, min(int(params.get("inference_timesteps", 7)), 50))
            gen_kwargs["warmup_patches"] = max(0, min(int(params.get("voxcpm_warmup_patches", 0)), 4))
            gen_kwargs["max_tokens"] = max(256, min(int(params.get("voxcpm_max_tokens", 2000)), 4096))

        # MLX models sample through mlx.core.random. Apply the recorded seed
        # immediately before inference so history reuse is genuinely repeatable.
        seed = params.get("_qwen_attempt_seed", params.get("seed"))
        if seed is None or seed < 0:
            import random
            seed = random.randint(0, 2**32 - 1)
        job.resolved_seed = int(seed)

        if family == "echo-tts":
            # Echo's diffusion sampler draws from its OWN rng_seed kwarg rather
            # than mlx.core.random, so seeding mx alone would not make a reuse
            # repeatable. Feed it the same resolved seed (its own range is a
            # plain int; keep it inside 2**32 like the mx seed below).
            gen_kwargs["rng_seed"] = int(seed) % (2**32)

        if job.cancel_event.is_set():
            return

        model = self._mlx_audio_get_model(model_entry.repo)

        # Unique temp dir per job so concurrent jobs (when we eventually allow
        # them) don't collide on the audio_000.wav name.
        temp_dir = Path(tempfile.mkdtemp(prefix=f"mlxaudio_{family}_{job.job_id}_"))
        try:
            import mlx.core as mx
            mx.random.seed(int(seed) % (2**32))
            log_extras = []
            if family_config.get("uses_cfg"):
                log_extras.append(f"steps={gen_kwargs['inference_timesteps']}")
                log_extras.append(f"cfg={gen_kwargs['cfg_value']}")
                log_extras.append(f"warmup={gen_kwargs['warmup_patches']}")
                log_extras.append(f"max_tokens={gen_kwargs['max_tokens']}")
            extras = f" [{', '.join(log_extras)}]" if log_extras else ""
            print(
                f"[gen] {family} {mode_label} ({len(text)} chars){extras}",
                flush=True,
            )
            internal_chunks = _internal_mlx_text_chunks(
                family,
                model_entry.repo,
                text,
                # The internal Qwen retry override tightens the budget for a
                # known-bad generation and must still win over a caller's
                # qualification override.
                max_chars_override=(
                    params.get("_qwen_section_max_characters")
                    or params.get("section_max_characters")
                ),
            )
            if len(internal_chunks) > 1:
                self._generate_mlx_long_form_sections(
                    job, family, model, gen_kwargs, internal_chunks, temp_dir,
                    output_path, generate_audio, model_entry.repo,
                )
                if not job.cancel_event.is_set():
                    print(
                        f"[gen] {family} joined {len(internal_chunks)} stable sections: {output_path}",
                        flush=True,
                    )
            else:
                generate_audio(
                    model=model,
                    output_path=str(temp_dir),
                    join_audio=True,
                    **gen_kwargs,
                )

                produced = temp_dir / "audio.wav"
                if not produced.exists():
                    # mlx-audio sometimes uses a different naming scheme — find any wav.
                    candidates = sorted(temp_dir.glob("*.wav"))
                    if not candidates:
                        raise RuntimeError(
                            f"mlx-audio didn't produce a wav file. Temp dir: {temp_dir}"
                        )
                    produced = candidates[0]

                trimmed_seconds = _trim_model_terminal_silence(
                    produced, model_entry.repo, family
                )
                if trimmed_seconds:
                    print(
                        f"[gen] {_terminal_silence_correction_label(model_entry.repo, family)} removed {trimmed_seconds:.2f}s "
                        "of pathological terminal silence",
                        flush=True,
                    )
                shutil.move(str(produced), str(output_path))
                sr = model_entry.sample_rate_hz or family_config["default_sample_rate"]
                print(f"[gen] {family} saved WAV at {sr} Hz: {output_path}", flush=True)

            if not job.cancel_event.is_set() and family in _POSTPROCESSED_SPEED_FAMILIES:
                if _apply_mlx_output_speed(output_path, speed, family):
                    print(
                        f"[gen] {family} applied pitch-preserving {speed:.2f}x tempo",
                        flush=True,
                    )
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            # Release MLX Metal cache + Python refs so the NEXT job starts from
            # a clean memory baseline. Without this, sequential VoxCPM2-mlx
            # voice-cloning calls accumulate activation tensors across jobs and
            # the second/third call hits Metal's per-buffer cap (~9.5 GB on M4
            # 16 GB) → Abort trap: 6. The cached `self._mlx_audio_model` stays
            # loaded (model weights are not the OOM trigger); only the
            # per-generation activation buffers get freed. See v1.2.7 fix.
            _release_device_memory("mps")

    @staticmethod
    def _mlx_audio_output_file(output_dir: Path) -> Path:
        """Find the WAV written by mlx-audio across its output naming variants."""
        produced = output_dir / "audio.wav"
        if produced.exists():
            return produced
        candidates = sorted(output_dir.glob("*.wav"))
        if candidates:
            return candidates[0]
        raise RuntimeError(f"mlx-audio didn't produce a wav file. Temp dir: {output_dir}")

    def _generate_mlx_long_form_sections(self, job: GenerationJob, family: str, model,
                                         gen_kwargs: dict, chunks: list[str], temp_dir: Path,
                                         output_path: Path, generate_audio,
                                         model_repo: str = "") -> None:
        """Render independently verified sections, then join them into one WAV."""
        segment_paths: list[Path] = []
        job.chunk_total = len(chunks)
        job.chunk_index = 0
        for index, chunk in enumerate(chunks, start=1):
            if job.cancel_event.is_set():
                return
            job.chunk_index = index
            job.progress = max(job.progress, min(0.93, 0.08 + (index - 1) / len(chunks) * 0.85))
            segment_dir = temp_dir / f"section_{index:03d}"
            segment_dir.mkdir()
            print(
                f"[gen] {family} stable section {index}/{len(chunks)} ({len(chunk)} chars)",
                flush=True,
            )
            generate_audio(
                model=model,
                output_path=str(segment_dir),
                join_audio=True,
                **{
                    **gen_kwargs,
                    "text": chunk,
                    **(
                        {
                            "max_tokens": qwen_quality.max_tokens_for_text(
                                chunk,
                                float(job.params.get("speed") or 1.0),
                            )
                        }
                        if family == "qwen3-tts"
                        and qwen_quality.is_qwen_base_clone(model_repo, job.params)
                        else {}
                    ),
                },
            )
            if job.cancel_event.is_set():
                return
            segment_path = self._mlx_audio_output_file(segment_dir)
            trimmed_seconds = _trim_model_terminal_silence(segment_path, model_repo, family)
            if trimmed_seconds:
                print(
                    f"[gen] {_terminal_silence_correction_label(model_repo, family)} section {index}/{len(chunks)} removed "
                    f"{trimmed_seconds:.2f}s of pathological terminal silence",
                    flush=True,
                )
            segment_paths.append(segment_path)
            job.progress = max(job.progress, min(0.95, 0.08 + index / len(chunks) * 0.85))
        _join_long_form_wavs(
            segment_paths,
            output_path,
            family,
            pause_s=_long_form_join_pause_s(family, model_repo),
        )

    def _generate_qwen_clone_long_form(self, job: GenerationJob, model, gen_kwargs: dict,
                                       chunks: list[str], temp_dir: Path, output_path: Path,
                                       generate_audio) -> None:
        """Compatibility wrapper for Qwen-specific regression tests."""
        self._generate_mlx_long_form_sections(
            job, "qwen3-tts", model, gen_kwargs, chunks, temp_dir,
            output_path, generate_audio,
            "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
        )

    def _resolve_mlx_kwargs(self, mode: str, family: str, model_entry, params: dict,
                            gen_kwargs: dict) -> str:
        """
        Per-mode kwarg resolver. Mutates `gen_kwargs` in place to add the
        family's specific kwargs (voice / instruct / ref_audio / ref_text /
        exaggeration / etc.) and returns a human-readable mode label for the
        log line.

        Modes:
        - "qwen3"             — repo-name picks custom (preset) / design (text) / clone (ref)
        - "voxcpm_flex"       — any combo of ref_audio + ref_text + instruct
        - "voice_picker"      — voice param required, no clone
        - "clone_with_intensity" — needs ref_audio, optional exaggeration
        - "voice_or_clone"    — voice param OR ref_audio (zero-shot or clone)
        - "fish_audio"        — optional ref_audio + optional instruct + full sampling
        - "audio8"            — optional ref_audio (zero-shot otherwise), full sampling, no instruct/language
        - "moss_tts_nano"     — ref_audio REQUIRED (no zero-shot), full sampling, no instruct/language
        - "echo_tts"          — optional ref_audio, NO ref_text at all, diffusion sampler knobs
        """
        from . import voices as voices_module

        if mode == "qwen3":
            return self._mlx_kwargs_qwen3(model_entry, params, gen_kwargs, voices_module)
        if mode == "bark":
            return self._mlx_kwargs_bark(model_entry, params, gen_kwargs)
        if mode == "voxcpm_flex":
            return self._mlx_kwargs_voxcpm_flex(params, gen_kwargs, voices_module)
        if mode == "voice_picker":
            return self._mlx_kwargs_voice_picker(family, params, gen_kwargs)
        if mode == "clone_with_intensity":
            return self._mlx_kwargs_clone_with_intensity(model_entry, params, gen_kwargs, voices_module)
        if mode == "voice_or_clone":
            return self._mlx_kwargs_voice_or_clone(params, gen_kwargs, voices_module)
        if mode == "omnivoice":
            return self._mlx_kwargs_omnivoice(params, gen_kwargs, voices_module)
        if mode == "fish_audio":
            return self._mlx_kwargs_fish_audio(params, gen_kwargs, voices_module)
        if mode == "audio8":
            return self._mlx_kwargs_audio8(params, gen_kwargs, voices_module)
        if mode == "moss_tts_nano":
            return self._mlx_kwargs_moss_tts_nano(params, gen_kwargs, voices_module)
        if mode == "echo_tts":
            return self._mlx_kwargs_echo_tts(params, gen_kwargs, voices_module)
        raise RuntimeError(f"Unknown mlx-audio mode {mode!r} for family {family!r}")

    # --- per-mode kwarg builders ---

    def _mlx_kwargs_bark(self, model_entry, params, gen_kwargs) -> str:
        """Resolve Bark's local history prompt and native sampling controls."""
        preset = (params.get("bark_voice_preset") or "").strip()
        if preset:
            valid_presets = {item["id"] for item in BARK_VOICE_PRESETS}
            if preset not in valid_presets:
                raise ValueError(f"Unknown Bark voice preset: {preset}")
            voice_path = self._mlx_audio_snapshot_path(model_entry.repo) / f"{preset}.npz"
            if not voice_path.exists():
                raise ValueError(
                    f"Bark voice preset {preset} is missing. Re-download the model from Models."
                )
            gen_kwargs["voice"] = str(voice_path)
        else:
            # generate_audio defaults to a Kokoro voice name, which Bark rejects.
            gen_kwargs["voice"] = None

        gen_kwargs["temperature"] = max(
            0.1, min(float(params.get("bark_temperature", 0.7)), 1.5)
        )
        gen_kwargs["max_coarse_history"] = max(
            60, min(int(params.get("bark_max_coarse_history", 60)), 630)
        )
        gen_kwargs["sliding_window_len"] = max(
            30, min(int(params.get("bark_sliding_window_len", 60)), 120)
        )
        gen_kwargs["allow_early_stop"] = bool(
            params.get("bark_allow_early_stop", True)
        )
        return f"preset={preset}" if preset else "random voice"

    def _mlx_kwargs_qwen3(self, model_entry, params, gen_kwargs, voices_module) -> str:
        """Qwen3-TTS: repo-name selects between custom (preset speakers),
        design (natural-language prompt), and clone (reference audio)."""
        repo = model_entry.repo
        mode = _qwen3_mode_from_repo(repo)

        if mode == "custom":
            speaker = (params.get("preset_speaker") or "").strip()
            if not speaker:
                raise ValueError(
                    "CustomVoice mode needs a preset_speaker. Pick one from the speaker dropdown."
                )
            valid_speakers = {s["id"] for s in QWEN3_PRESET_SPEAKERS}
            if speaker not in valid_speakers:
                raise ValueError(
                    f"Unknown preset speaker {speaker!r}. Valid options: {sorted(valid_speakers)}"
                )
            gen_kwargs["voice"] = speaker
            instruct = (params.get("instruct") or "").strip()
            gen_kwargs["instruct"] = instruct or "Normal tone"
            return f"custom (speaker={speaker})"

        if mode == "design":
            instruct = (params.get("voice_design_prompt") or params.get("instruct") or "").strip()
            if not instruct:
                raise ValueError(
                    "VoiceDesign mode needs a voice description. Use natural language: "
                    "'deep gravelly male, slow' or pick a preset."
                )
            gen_kwargs["instruct"] = instruct
            return f"design ({len(instruct)} char prompt)"

        if mode == "clone":
            voice_id = (params.get("voice_library_id") or "").strip()
            if not voice_id and not params.get("_reference_audio_path"):
                raise ValueError(
                    "Voice cloning needs a reference voice or private reference upload."
                )
            self._inject_voice_clone(voice_id, params, gen_kwargs, voices_module,
                                     fallback_transcript="")
            if not str(gen_kwargs.get("ref_text") or "").strip():
                raise ValueError(
                    "Qwen3-TTS 0.6B Base needs the exact transcript for its reference audio."
                )
            return f"clone (voice={voice_id or 'private-reference'})"

        raise RuntimeError(f"Unknown qwen3-tts mode {mode!r}")

    def _mlx_kwargs_voxcpm_flex(self, params, gen_kwargs, voices_module) -> str:
        """VoxCPM2 MLX: zero-shot, voice design, reference cloning, or
        transcript-aware continuation cloning with optional style control."""
        design_prompt = (params.get("voice_design_prompt") or params.get("instruct") or "").strip()
        if design_prompt:
            if len(design_prompt) > 500:
                raise ValueError("VoxCPM2 voice design instructions must be 500 characters or fewer")
            gen_kwargs["instruct"] = design_prompt

        voice_id = (params.get("voice_library_id") or "").strip() or None
        if voice_id or params.get("_reference_audio_path"):
            self._inject_voice_clone(
                voice_id or "", params, gen_kwargs, voices_module,
                fallback_transcript="",
            )
            ref_path = gen_kwargs["ref_audio"]
            transcript = (gen_kwargs.pop("ref_text", "") or "").strip()
            if transcript:
                # VoxCPM2's highest-fidelity path needs the same clip in both
                # reference and continuation slots, paired with its transcript.
                gen_kwargs["prompt_audio"] = str(ref_path)
                gen_kwargs["prompt_text"] = transcript

        if "prompt_audio" in gen_kwargs and "instruct" in gen_kwargs:
            return "ultimate clone + style"
        if "prompt_audio" in gen_kwargs:
            return "ultimate clone (transcript-aware)"
        if "ref_audio" in gen_kwargs and "instruct" in gen_kwargs:
            return "reference clone + style"
        if "ref_audio" in gen_kwargs:
            return "reference clone"
        if "instruct" in gen_kwargs:
            return "voice-design"
        return "zero-shot"

    def _mlx_kwargs_voice_picker(self, family: str, params, gen_kwargs) -> str:
        """Kokoro-MLX / Orpheus / similar: voice param is required (named
        preset voice). No reference audio cloning, no instruction prompt."""
        voice = (params.get("voice") or "").strip()
        if not voice:
            raise ValueError(
                f"{family} needs a preset voice. Pick one from the voice dropdown — "
                "the Voices library doesn't apply here (this family doesn't clone)."
            )

        if family == "vibevoice":
            known_voices = {item["id"] for item in VIBEVOICE_PRESET_VOICES}
            if voice not in known_voices:
                raise ValueError(
                    f"Unknown VibeVoice preset: {voice!r}. Pick a verified checkpoint voice."
                )

        if family == "kokoro-mlx":
            voices = [item.strip() for item in voice.split(",") if item.strip()]
            known_voices = {item["id"] for item in KOKORO_VOICES}
            unknown = [item for item in voices if item not in known_voices]
            if unknown:
                raise ValueError(
                    "Unknown Kokoro voice: " + ", ".join(unknown) +
                    ". Pick a voice from the verified preset list."
                )
            languages = {item[0] for item in voices}
            if len(languages) != 1:
                raise ValueError(
                    "Kokoro can only blend voices from the same language. "
                    "Choose a second voice in the same language as the first."
                )
            voice_language = next(iter(languages))
            requested_language = params.get("language") or ""
            lang_code = _normalize_kokoro_language(requested_language, voice_language)
            if lang_code not in LANG_NAMES:
                raise ValueError(f"Unsupported Kokoro language code: {lang_code}")
            if lang_code != voice_language:
                raise ValueError(
                    f"The selected Kokoro voice is {LANG_NAMES[voice_language]}, "
                    f"but the language control is {LANG_NAMES[lang_code]}."
                )
            gen_kwargs["lang_code"] = lang_code

            # The audited Kokoro checkpoint already contains every verified
            # voicepack.  mlx-audio otherwise resolves the same voice ID from
            # prince-canuma/Kokoro-82M and performs a surprise Hub download on
            # first use.  Pass the checkpoint-local safetensors paths so a
            # cached model is genuinely offline-ready and remains bound to the
            # exact audited revision.  Unit callers without a cache keep the
            # plain IDs; generation itself cannot reach this point without a
            # cached model.
            try:
                snapshot = self._mlx_audio_snapshot_path(
                    "mlx-community/Kokoro-82M-bf16"
                )
            except RuntimeError:
                snapshot = None
            if snapshot is not None:
                local_voices = [
                    snapshot / "voices" / f"{voice_id}.safetensors"
                    for voice_id in voices
                ]
                missing = [path.stem for path in local_voices if not path.is_file()]
                if missing:
                    raise RuntimeError(
                        "The cached Kokoro checkpoint is missing audited voicepacks: "
                        + ", ".join(missing)
                        + ". Re-download this exact model revision."
                    )
                # Keep the snapshot filename instead of resolving its symlink
                # into Hugging Face's extensionless blob path. Kokoro detects
                # a direct local voicepack by the ``.safetensors`` suffix; an
                # extensionless resolved blob is treated as a voice ID and the
                # runtime appends another suffix, so inference completes with
                # no output artifact.
                voice = ",".join(str(path.absolute()) for path in local_voices)

        gen_kwargs["voice"] = voice
        # Some voice-picker families (Orpheus) accept an optional instruct
        # for style nudges — forward it if present.
        instruct = "" if family == "kokoro-mlx" else (params.get("instruct") or "").strip()
        if instruct:
            gen_kwargs["instruct"] = instruct
        language_label = f" lang={gen_kwargs['lang_code']}" if family == "kokoro-mlx" else ""
        return f"voice={voice}{language_label}" + (f" instruct={len(instruct)}c" if instruct else "")

    def _mlx_kwargs_clone_with_intensity(self, model_entry, params, gen_kwargs, voices_module) -> str:
        """Chatterbox (MLX): requires a reference audio for voice cloning,
        plus an optional `exaggeration` knob for emotion intensity."""
        voice_id = (params.get("voice_library_id") or "").strip()
        if not voice_id and not params.get("_reference_audio_path"):
            raise ValueError(
                "Chatterbox needs a reference voice or private reference upload."
            )
        language = (params.get("language") or "").strip().lower()
        catalog_entry = catalog.get_model(model_entry.repo)
        support = getattr(catalog_entry, "language_support", None)
        supported_languages = (
            support.codes if support is not None else catalog.CHATTERBOX_LANGUAGE_CODES
        )
        if not language:
            raise ValueError(
                "Chatterbox needs a language code. Choose one of: "
                + ", ".join(supported_languages)
            )
        if language not in supported_languages:
            raise ValueError(
                f"Unsupported Chatterbox language code: {language}. Choose one of: "
                + ", ".join(supported_languages)
            )
        self._inject_voice_clone(voice_id, params, gen_kwargs, voices_module,
                                 fallback_transcript="")
        gen_kwargs["lang_code"] = language
        # Exaggeration is a Chatterbox-specific dial (0.0–1.0, default 0.5).
        # Surface it via the generic `cfg_value` slot in params so the UI
        # doesn't need a brand-new field per family.
        turbo = "turbo" in model_entry.repo.lower()
        exaggeration = max(0.0, min(float(params.get("cfg_value", 0.5)), 1.0))
        if not turbo:
            gen_kwargs["exaggeration"] = exaggeration
        gen_kwargs["temperature"] = max(0.05, min(float(params.get("temperature", 0.8)), 2.0))
        gen_kwargs["repetition_penalty"] = max(
            1.0, min(float(params.get("chatterbox_repetition_penalty", 1.2)), 2.0)
        )
        gen_kwargs["top_p"] = max(0.05, min(float(params.get("chatterbox_top_p", 1.0)), 1.0))
        if not turbo:
            gen_kwargs["cfg_weight"] = max(
                0.0, min(float(params.get("chatterbox_cfg_weight", 0.5)), 1.0)
            )
            gen_kwargs["min_p"] = max(
                0.0, min(float(params.get("chatterbox_min_p", 0.05)), 1.0)
            )
        detail = "turbo sampling" if turbo else f"exaggeration={exaggeration:.2f}"
        return f"clone (voice={voice_id or 'private-reference'}, {detail})"

    def _mlx_kwargs_omnivoice(self, params, gen_kwargs, voices_module) -> str:
        """OmniVoice MLX supports voice design, cloning, or both together."""
        instruct = (params.get("voice_design_prompt") or "").strip()
        voice_id = (params.get("voice_library_id") or "").strip()
        has_reference = bool(voice_id or params.get("_reference_audio_path"))
        if not instruct and not has_reference:
            raise ValueError(
                "OmniVoice needs either a reference voice or voice traits such as "
                "'female, british accent'."
            )
        if instruct:
            gen_kwargs["instruct"] = instruct
        if has_reference:
            self._inject_voice_clone(
                voice_id, params, gen_kwargs, voices_module, fallback_transcript="."
            )
            gen_kwargs["ref_audio_max_duration_s"] = 10.0

        gen_kwargs["num_steps"] = max(
            4, min(int(params.get("omnivoice_num_steps", 32)), 64)
        )
        gen_kwargs["guidance_scale"] = max(
            0.0, min(float(params.get("omnivoice_guidance_scale", 2.0)), 8.0)
        )
        duration = params.get("omnivoice_duration_s")
        if duration is not None:
            gen_kwargs["duration_s"] = max(0.5, min(float(duration), 120.0))
        reference_label = voice_id or "private-reference"
        if has_reference and instruct:
            return f"combined (clone={reference_label} + traits)"
        if has_reference:
            return f"clone (voice={reference_label})"
        return f"design ({len(instruct)} char traits)"

    def _mlx_kwargs_fish_audio(self, params, gen_kwargs, voices_module) -> str:
        """Fish Audio S2 Pro: optional reference clone plus style/instruct.

        Fish's upstream API accepts a reference audio/transcript pair and a
        natural-language ``instruct``. Voice Studio keeps the reference
        transcript optional because Fish can clone from the clip alone.
        """
        voice_id = (params.get("voice_library_id") or "").strip()
        has_reference = bool(voice_id or params.get("_reference_audio_path"))
        instruct = (params.get("voice_design_prompt") or params.get("instruct") or "").strip()
        if instruct:
            gen_kwargs["instruct"] = instruct[:500]
        if has_reference:
            self._inject_voice_clone(
                voice_id, params, gen_kwargs, voices_module, fallback_transcript=""
            )

        gen_kwargs["max_tokens"] = max(
            128, min(int(params.get("fish_max_tokens", 1024)), 4096)
        )
        gen_kwargs["temperature"] = max(
            0.05, min(float(params.get("fish_temperature", 0.7)), 2.0)
        )
        gen_kwargs["top_p"] = max(
            0.05, min(float(params.get("fish_top_p", 0.7)), 1.0)
        )
        gen_kwargs["top_k"] = max(
            0, min(int(params.get("fish_top_k", 30)), 100)
        )
        reference_label = voice_id or "private-reference"
        if has_reference and instruct:
            return f"clone + style (voice={reference_label})"
        if has_reference:
            return f"clone (voice={reference_label})"
        if instruct:
            return f"zero-shot + style ({len(instruct)} char prompt)"
        return "zero-shot"

    def _mlx_kwargs_audio8(self, params, gen_kwargs, voices_module) -> str:
        """Audio8 TTS Preview (arktts): optional reference clone, otherwise
        the model's single built-in default voice.

        Verified against the installed mlx-audio source: generate() takes
        text/ref_audio/ref_text/temperature/top_p/top_k/max_tokens/do_sample —
        no instruct, no language, no speed. The public speed control is
        applied as one pitch-preserving tempo pass on the finished WAV.
        """
        voice_id = (params.get("voice_library_id") or "").strip()
        has_reference = bool(voice_id or params.get("_reference_audio_path"))
        if has_reference:
            self._inject_voice_clone(
                voice_id, params, gen_kwargs, voices_module, fallback_transcript=""
            )
        gen_kwargs["temperature"] = max(
            0.05, min(float(params.get("audio8_temperature", 0.7)), 2.0)
        )
        gen_kwargs["top_p"] = max(
            0.05, min(float(params.get("audio8_top_p", 0.9)), 1.0)
        )
        gen_kwargs["top_k"] = max(
            0, min(int(params.get("audio8_top_k", 50)), 200)
        )
        gen_kwargs["max_tokens"] = max(
            128, min(int(params.get("audio8_max_tokens", 512)), 2048)
        )
        reference_label = voice_id or "private-reference"
        return f"clone (voice={reference_label})" if has_reference else "zero-shot (default voice)"

    def _mlx_kwargs_moss_tts_nano(self, params, gen_kwargs, voices_module) -> str:
        """MOSS-TTS-Nano: voice_clone is the model's only generation mode —
        a reference clip is always required (verified against the installed
        mlx-audio source: generate() raises ValueError without ref_audio in
        the default mode). No transcript is needed; ref_text is unused in
        voice_clone mode. No instruct, no language, no speed.
        """
        voice_id = (params.get("voice_library_id") or "").strip()
        if not voice_id and not params.get("_reference_audio_path"):
            raise ValueError(
                "MOSS-TTS-Nano needs a reference voice — it has no zero-shot mode."
            )
        self._inject_voice_clone(
            voice_id, params, gen_kwargs, voices_module, fallback_transcript=""
        )
        gen_kwargs["temperature"] = max(
            0.05, min(float(params.get("moss_temperature", 0.8)), 2.0)
        )
        gen_kwargs["top_p"] = max(
            0.05, min(float(params.get("moss_top_p", 0.95)), 1.0)
        )
        gen_kwargs["top_k"] = max(
            0, min(int(params.get("moss_top_k", 25)), 200)
        )
        gen_kwargs["repetition_penalty"] = max(
            1.0, min(float(params.get("moss_repetition_penalty", 1.2)), 2.0)
        )
        return f"clone (voice={voice_id or 'private-reference'})"

    def _mlx_kwargs_echo_tts(self, params, gen_kwargs, voices_module) -> str:
        """Echo-TTS: optional reference clone, otherwise the model's own voice.

        Cloning is AUDIO-ONLY — verified against the installed mlx-audio source:
        Model.generate(text, voice, ref_audio, stream, **kwargs) has no ref_text
        parameter, and everything else (speed, temperature, instruct, lang_code,
        ref_text) falls into **kwargs where generate_latents() filters it against
        the SamplerConfig field names and silently drops non-matches. So a
        reference voice with no saved transcript works fine here, and the public
        speed control is applied as one pitch-preserving tempo pass afterwards.
        """
        voice_id = (params.get("voice_library_id") or "").strip()
        has_reference = bool(voice_id or params.get("_reference_audio_path"))
        if has_reference:
            self._inject_voice_clone(
                voice_id, params, gen_kwargs, voices_module, fallback_transcript=""
            )
            # Echo ignores ref_text; drop it so the kwargs reflect what is used.
            gen_kwargs.pop("ref_text", None)

        # Real SamplerConfig fields (echo_tts/config.py). Anything else is dropped
        # by the engine, so only expose knobs that actually take effect.
        gen_kwargs["num_steps"] = max(
            4, min(int(params.get("echo_num_steps", 40)), 128)
        )
        gen_kwargs["cfg_scale_text"] = max(
            0.0, min(float(params.get("echo_cfg_scale_text", 3.0)), 10.0)
        )
        gen_kwargs["cfg_scale_speaker"] = max(
            0.0, min(float(params.get("echo_cfg_scale_speaker", 8.0)), 20.0)
        )
        reference_label = voice_id or "private-reference"
        return f"clone (voice={reference_label})" if has_reference else "zero-shot (default voice)"

    def _mlx_kwargs_voice_or_clone(self, params, gen_kwargs, voices_module) -> str:
        """Spark-TTS (MLX): EITHER a voice picker (preset) OR a reference
        audio. If both, the reference clip wins (Spark prefers clone over preset)."""
        voice_id = (params.get("voice_library_id") or "").strip() or None
        if voice_id or params.get("_reference_audio_path"):
            self._inject_voice_clone(voice_id or "", params, gen_kwargs, voices_module,
                                     fallback_transcript=".")
            return f"clone (voice={voice_id or 'private-reference'})"

        voice = (params.get("voice") or "").strip()
        if voice:
            gen_kwargs["voice"] = voice
            return f"voice={voice}"

        # Spark accepts pure zero-shot with default voice — useful for quick tests.
        return "zero-shot"

    def _inject_voice_clone(self, voice_id: str, params: dict, gen_kwargs: dict,
                            voices_module, fallback_transcript: str) -> None:
        """Helper — look up `voice_id` in the voices library, validate the
        reference clip exists, and inject ref_audio + ref_text into gen_kwargs.
        Used by every clone-capable mode."""
        private_path = str(params.get("_reference_audio_path") or "").strip()
        if private_path:
            ref_path = Path(private_path)
            if not ref_path.is_file():
                raise ValueError("The private reference audio is no longer available")
        else:
            voice = voices_module.library.get(voice_id)
            if voice is None:
                raise ValueError(f"Voice {voice_id} not found in library")
            ref_path = voices_module.library.reference_path(voice_id)
            if ref_path is None or not ref_path.exists():
                raise ValueError(f"Reference audio for voice {voice_id} is missing on disk")
        gen_kwargs["ref_audio"] = str(ref_path)
        ref_text = (params.get("ref_transcript") or "").strip()
        if not ref_text and voice_id:
            ref_text = voices_module.library.transcript(voice_id) or ""
        gen_kwargs["ref_text"] = ref_text or fallback_transcript

    # ----- F5-TTS (SWivid flow-matching) -----

    def _f5_tts_get_model(self, repo: str, device: str):
        """Lazy-load + cache an F5TTS instance. Evicts on repo switch — the
        model + VoCoS vocoder together hold several GB of MPS memory.

        Note: F5-TTS auto-resolves checkpoint files from HF_HOME based on the
        `model` name argument ('F5TTS_v1_Base'). The catalog's `repo` field
        (`SWivid/F5-TTS`) is informational here — F5-TTS doesn't take a repo
        path; it has hardcoded model registry entries. Other F5-TTS variants
        (E2-TTS, F5TTS_Base, F5TTS_v1_Base_no_zero_init, multilingual ones)
        would need their `model=` string flipped per-entry."""
        if self._f5_tts_model_repo == repo and self._f5_tts_model is not None:
            return self._f5_tts_model

        if self._f5_tts_model is not None:
            print(f"[gen] evicting cached F5-TTS model ({self._f5_tts_model_repo})", flush=True)
            try:
                del self._f5_tts_model
            except Exception:
                pass
            self._f5_tts_model = None
            self._f5_tts_model_repo = None
            _release_device_memory(device)

        # F5-TTS's api uses `cached_path` (a separate library, not huggingface_hub)
        # for the main checkpoint. cached_path has its OWN cache layout that
        # doesn't share with HF Hub's standard `hub/models--<org>--<repo>/...`
        # structure — it creates `models--<org>--<repo>/` directly under the
        # passed cache_dir, no `hub/` segment. So even though our HF Hub cache
        # has the SWivid/F5-TTS files at:
        #   {HF_HOME}/hub/models--SWivid--F5-TTS/snapshots/<hash>/F5TTS_v1_Base/
        # passing hf_cache_dir={HF_HOME} (or even {HF_HOME}/hub) wouldn't make
        # cached_path find them — the layouts are incompatible.
        #
        # v1.3.4 fix: locate the existing checkpoint + vocab files in our HF
        # Hub cache and pass them explicitly via ckpt_file= and vocab_file=.
        # F5TTS skips cached_path entirely when these args are non-empty.
        # The VoCoS vocoder is still auto-downloaded via hf_hub_download (which
        # DOES respect HF_HOME correctly) — small enough (~50 MB) to ignore.
        from f5_tts.api import F5TTS
        snapshot_path = self._mlx_audio_snapshot_path(repo)   # reuses HF Hub layout walker
        ckpt_file = snapshot_path / "F5TTS_v1_Base" / "model_1250000.safetensors"
        vocab_file = snapshot_path / "F5TTS_v1_Base" / "vocab.txt"
        if not ckpt_file.exists():
            raise RuntimeError(
                f"F5-TTS checkpoint missing at {ckpt_file}. "
                "Re-download SWivid/F5-TTS from the Models tab."
            )
        if not vocab_file.exists():
            raise RuntimeError(
                f"F5-TTS vocab file missing at {vocab_file}. "
                "Re-download SWivid/F5-TTS from the Models tab."
            )
        hf_cache = os.environ.get("HF_HOME")
        print(
            f"[gen] loading F5-TTS from local ckpt {ckpt_file.name} "
            f"({ckpt_file.stat().st_size / 1e9:.2f} GB); "
            f"vocoder auto-downloads to {hf_cache or 'default HF cache'}",
            flush=True,
        )
        model = F5TTS(
            model="F5TTS_v1_Base",
            ckpt_file=str(ckpt_file),
            vocab_file=str(vocab_file),
            device=device,
            hf_cache_dir=hf_cache,                 # for the VoCoS vocoder download path
        )
        self._f5_tts_model = model
        self._f5_tts_model_repo = repo
        self._last_model_activity_at = time.time()
        return model

    def _generate_f5_tts(self, job: GenerationJob, model_entry, output_path: Path) -> None:
        """F5-TTS voice cloning. The engine has no zero-shot mode — a reference
        audio clip + transcript are mandatory. Long text auto-chunks into
        ~135-char windows internally (see f5_tts.infer.utils_infer.chunk_text),
        each chunk crossfaded with the next at 0.15s. Output is a single
        stitched WAV at 24 kHz."""
        import soundfile as sf
        from . import voices as voices_module

        params = job.params
        device = _detect_device()

        text = (params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        # F5-TTS requires voice cloning — no zero-shot mode.
        voice_id = (params.get("voice_library_id") or "").strip()
        private_path = str(params.get("_reference_audio_path") or "").strip()
        if not voice_id and not private_path:
            raise ValueError(
                "F5-TTS requires a reference voice or private reference upload."
            )
        if private_path:
            ref_path = Path(private_path)
            if not ref_path.is_file():
                raise ValueError("The private reference audio is no longer available")
        else:
            voice = voices_module.library.get(voice_id)
            if voice is None:
                raise ValueError(f"Voice {voice_id} not found in library")
            ref_path = voices_module.library.reference_path(voice_id)
            if ref_path is None or not ref_path.exists():
                raise ValueError(f"Reference audio for voice {voice_id} is missing on disk")

        # Transcript: prefer per-request override, fall back to library entry.
        ref_text = (params.get("ref_transcript") or "").strip()
        if not ref_text and voice_id:
            ref_text = (voices_module.library.transcript(voice_id) or "").strip()
        if not ref_text:
            raise ValueError(
                "F5-TTS needs a transcript of the reference clip. Edit the voice "
                "in your Voices library to add one, or provide a transcript "
                "override in the Reference transcript field."
            )

        speed = float(params.get("speed", 1.0))
        speed = max(0.5, min(speed, 2.0))

        # F5-TTS knobs we surface via existing UI controls:
        # - inference_timesteps → nfe_step (flow-matching steps, default 32)
        # - cfg_value → cfg_strength (classifier-free guidance, default 2.0)
        nfe_step = int(params.get("inference_timesteps", 32))
        nfe_step = max(8, min(nfe_step, 64))
        cfg_strength = float(params.get("cfg_value", 2.0))
        cfg_strength = max(0.5, min(cfg_strength, 5.0))

        seed = params.get("seed")
        if seed is None or seed < 0:
            import random
            seed = random.randint(0, 2**32 - 1)
        job.resolved_seed = int(seed)

        if job.cancel_event.is_set():
            return

        model = self._f5_tts_get_model(model_entry.repo, device)

        print(
            f"[gen] f5-tts voice-clone ({len(text)} chars, ref={ref_path.name}, "
            f"nfe={nfe_step}, cfg={cfg_strength}, speed={speed})",
            flush=True,
        )
        wav, sr, _spec = model.infer(
            ref_file=str(ref_path),
            ref_text=ref_text,
            gen_text=text,
            nfe_step=nfe_step,
            cfg_strength=cfg_strength,
            speed=speed,
            seed=int(seed),
        )
        sf.write(str(output_path), wav, sr, format="WAV", subtype="PCM_16")
        print(f"[gen] f5-tts saved WAV at {sr} Hz, {len(wav)/sr:.2f}s: {output_path}", flush=True)

    # ----- persistence -----

    def _persist(self) -> None:
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            recoverable = [
                j for j in self._jobs.values()
                if j.provider
                and j.state in ("queued", "running")
                and (
                    j.provider_task_id
                    or (j.provider == "elevenlabs" and j.provider_account_id)
                )
            ]
            terminal = [j for j in self._jobs.values()
                        if j.state in ("done", "error", "cancelled")]
            terminal.sort(key=lambda j: j.finished_at or 0, reverse=True)
            terminal = terminal[:HISTORY_MAX]
            payload = {
                "jobs": [self._to_disk(j) for j in recoverable + terminal]
            }
            tmp = HISTORY_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, default=str))
            os.replace(tmp, HISTORY_FILE)
        except Exception as e:
            print(f"[gen] persist failed: {e}", file=sys.stderr, flush=True)

    def _load_history(self) -> None:
        if not HISTORY_FILE.exists():
            return
        try:
            payload = json.loads(HISTORY_FILE.read_text())
            for raw in payload.get("jobs", []):
                job = self._from_disk(raw)
                if job is not None:
                    self._jobs[job.job_id] = job
            print(f"[gen] loaded {len(self._jobs)} jobs from history", flush=True)
        except Exception as e:
            print(f"[gen] load history failed: {e}", file=sys.stderr, flush=True)

    def _resume_cloud_jobs(self) -> None:
        """Resume persisted async tasks by polling their existing provider id.

        Local jobs and cloud jobs that never received a task id are deliberately
        not resumed: only an existing provider task can be recalled without any
        risk of creating a second paid request.
        """
        async_jobs = [
            job for job in self._jobs.values()
            if job.provider
            and job.provider_task_id
            and job.state in ("queued", "running")
        ]
        for job in async_jobs:
            job.state = "queued"
            job.error = None
            job.finished_at = None
            job.thread = threading.Thread(
                target=self._run_txt2speech,
                args=(job,),
                name=f"gen-recover-{job.job_id}",
                daemon=True,
            )
            job.thread.start()
        elevenlabs_jobs = [
            job for job in self._jobs.values()
            if job.provider == "elevenlabs"
            and job.provider_account_id
            and not job.provider_task_id
            and job.state in ("queued", "running")
        ]
        for job in elevenlabs_jobs:
            job.thread = threading.Thread(
                target=self._recover_elevenlabs_after_restart,
                args=(job,),
                name=f"gen-recover-{job.job_id}",
                daemon=True,
            )
            job.thread.start()
        recoverable = async_jobs + elevenlabs_jobs
        if recoverable:
            print(
                f"[gen] resumed {len(recoverable)} cloud provider task(s)",
                flush=True,
            )

    def _recover_elevenlabs_after_restart(self, job: GenerationJob) -> None:
        """Recover a paid synchronous call after Voice Studio restarts.

        The account binding is persisted immediately before submission. Startup
        only searches History for that exact call; it never submits a new one.
        """
        from . import providers as P
        try:
            pair = P.adapter_for(job.params.get("repo", ""))
            account = P.get_elevenlabs_account(job.provider_account_id or "")
            if pair is None or account is None:
                raise P.ProviderResultUncertain(
                    "The bound ElevenLabs account is no longer available."
                )
            _provider, model = pair
            recovered = pair[0].adapter.recover_recent(
                account["api_key"],
                text=str(job.params.get("text") or ""),
                model=model,
                voice=str(job.params.get("voice") or ""),
                started_at=int(job.started_at or time.time()),
            )
            if recovered is None:
                raise P.ProviderResultUncertain(
                    "Voice Studio restarted during an ElevenLabs request and no "
                    "unique History result could be recovered. The request was "
                    "not resubmitted to avoid charging twice."
                )
            audio, mime = recovered
            ext = "mp3" if ("mpeg" in (mime or "") or "mp3" in (mime or "")) else "wav"
            output_path = OUTPUT_DIR / f"{job.job_id}.{ext}"
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio)
            job.output_path = str(output_path.resolve())
            job.progress = 1.0
            job.state = "done"
            job.error = None
        except Exception as exc:
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = time.time()
            self._persist()

    @staticmethod
    def _to_disk(job: GenerationJob) -> dict:
        return {
            "job_id": job.job_id,
            "mode": job.mode,
            "state": job.state,
            "provider": job.provider,
            "client_request_params": job.client_request_params,
            "provider_account_id": job.provider_account_id,
            "provider_task_id": job.provider_task_id,
            "provider_task_meta": job.provider_task_meta,
            "progress": job.progress,
            "chunk_index": job.chunk_index,
            "chunk_total": job.chunk_total,
            "params": job.params,
            "output_path": job.output_path,
            "resolved_seed": job.resolved_seed,
            "error": job.error,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "model_revision": job.model_revision,
            "voice_revision": job.voice_revision,
            "media_type": job.media_type,
            "format": job.format,
            "bytes": job.bytes,
            "sha256": job.sha256,
            "audio_duration_s": job.audio_duration_s,
            "audio_duration_ms": job.audio_duration_ms,
            "sample_rate_hz": job.sample_rate_hz,
            "channels": job.channels,
            "resource_usage": job.resource_usage,
            "quality_validation": job.quality_validation,
            "quality_retry_count": job.quality_retry_count,
            "quality_retry_history": job.quality_retry_history,
            "error_code": job.error_code,
        }

    @staticmethod
    def _from_disk(raw: dict) -> Optional["GenerationJob"]:
        try:
            output_path = raw.get("output_path")
            if output_path and not Path(output_path).exists():
                output_path = None
            return GenerationJob(
                job_id=raw["job_id"],
                mode=raw.get("mode", "txt2speech"),
                params=raw.get("params") or {},
                state=raw.get("state", "done"),
                provider=raw.get("provider"),
                client_request_params=raw.get("client_request_params"),
                provider_account_id=raw.get("provider_account_id"),
                provider_task_id=raw.get("provider_task_id"),
                provider_task_meta=raw.get("provider_task_meta") or {},
                progress=raw.get("progress", 1.0),
                chunk_index=raw.get("chunk_index"),
                chunk_total=raw.get("chunk_total"),
                output_path=output_path,
                resolved_seed=raw.get("resolved_seed"),
                error=raw.get("error"),
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
                model_revision=raw.get("model_revision"),
                voice_revision=raw.get("voice_revision"),
                media_type=raw.get("media_type"),
                format=raw.get("format"),
                bytes=raw.get("bytes"),
                sha256=raw.get("sha256"),
                audio_duration_s=raw.get("audio_duration_s"),
                audio_duration_ms=raw.get("audio_duration_ms"),
                sample_rate_hz=raw.get("sample_rate_hz"),
                channels=raw.get("channels"),
                resource_usage=raw.get("resource_usage"),
                quality_validation=raw.get("quality_validation"),
                quality_retry_count=int(raw.get("quality_retry_count") or 0),
                quality_retry_history=raw.get("quality_retry_history") or [],
                error_code=raw.get("error_code"),
            )
        except Exception:
            return None


manager = GenerationManager()
