"""
TTS generation manager.

Worker dispatch is keyed off `model.family`. See `_WIRED_FAMILIES` below for
the authoritative list — the audit_truth.py script cross-checks that list
against the actual dispatch branches on every release.

Currently wired (workers exist):
- kokoro          → KPipeline (English-only via misaki[en], no espeak-ng)
- voxcpm          → transformers + custom audiovae
- bark            → transformers BarkModel
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

EXCEPTIONS — loaders that don't accept a path argument:
- KPipeline(lang_code=…) for Kokoro: no path API. Must trust HF_HOME env.
  Document the limitation in the worker comment.

COMPLIANCE TABLE (keep current when adding workers):

| Worker                | Pattern                                                       | Status |
|-----------------------|---------------------------------------------------------------|--------|
| _generate_mlx_audio   | load_model(snapshot_path)  Path not str (v1.2.8)              | OK     |
| _generate_f5_tts      | F5TTS(ckpt_file=…, vocab_file=…)  (v1.3.4)                    | OK     |
| _generate_voxcpm      | voxcpm.VoxCPM.from_pretrained(str(snapshot_path), local_files_only=True) | OK |
| _generate_bark        | BarkModel.from_pretrained(str(snapshot_path), local_files_only=True)     | OK |
| _generate_kokoro      | KPipeline(lang_code=…)  — no path API, trusts HF_HOME         | LIMIT  |

═════════════════════════════════════════════════════════════════════════

Outputs land in `app/output/<job_id>.wav` and are persisted to
`app/output/.history.json` (same shape as MusicStudio's gen history) so they
survive server restarts.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import catalog, cache


# ───────────── module-level state ─────────────

# TTS on MPS can OOM if multiple models are loaded simultaneously. Even
# Kokoro's 82M model + a second model would fight for unified memory.
# Serialize all generations.
_GEN_LOCK = threading.Lock()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
HISTORY_FILE = OUTPUT_DIR / ".history.json"
HISTORY_MAX = 200
_AUDIO_OUTPUT_SUFFIXES = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}


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
KOKORO_AVAILABLE = _package_installed("kokoro")


# ───────────── Kokoro voice catalog ─────────────

# Kokoro v1.0 ships with named preset voices. Voice naming convention:
# - First letter: language code ('a' = American English, 'b' = British English,
#   and others for non-English languages we don't enable yet)
# - Second letter: gender ('f' = female, 'm' = male)
# - Rest: voice nickname
#
# This list is the published set as of Kokoro v1.0. The actual available voices
# depend on what's bundled with the installed `kokoro` package — we expose the
# full set in the UI and the user can try them.
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
]

# Lang code → display name
LANG_NAMES = {
    "a": "American English",
    "b": "British English",
}


def availability() -> dict:
    """Per-engine availability + the static config the frontend needs."""
    qwen3_ok = _have_mlx_audio()
    voxcpm_ok = _have_voxcpm()
    bark_ok = _have_bark()
    omnivoice_ok = qwen3_ok
    f5_tts_ok = _have_f5_tts()
    wired = []
    if KOKORO_AVAILABLE:
        wired.append("kokoro")
    if qwen3_ok:
        # All mlx-audio-backed families share one loader + one worker.
        # If mlx-audio imports, every entry in MLX_AUDIO_FAMILIES is wired.
        for fam in MLX_AUDIO_FAMILIES.keys():
            wired.append(fam)
    if voxcpm_ok:
        wired.append("voxcpm")
    if bark_ok:
        wired.append("bark")
    if f5_tts_ok:
        wired.append("f5-tts")
    return {
        "available": TTS_AVAILABLE,
        "kokoro_available": KOKORO_AVAILABLE,
        "qwen3_available": qwen3_ok,
        "voxcpm_available": voxcpm_ok,
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
        "lang_names": LANG_NAMES,
        "phase": 2,
        "wired_families": wired,
    }


def _have_mlx_audio() -> bool:
    return _package_installed("mlx_audio")


def _have_voxcpm() -> bool:
    return _package_installed("voxcpm")


def _have_bark() -> bool:
    """Bark is bundled with Transformers; diagnostics deep-checks the package."""
    return _package_installed("transformers")


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
    ("transformers",  "VoxCPM / Bark / Spark-TTS architectures"),
    ("kokoro",        "Kokoro TTS pipeline"),
    ("misaki",        "Grapheme→phoneme for Kokoro (auto-pulled by kokoro)"),
    ("diffusers",     "Future engines (F5-TTS etc.)"),
    ("accelerate",    "Multi-device model loading"),
    ("soundfile",     "WAV file writing (libsndfile)"),
    ("numpy",         "Tensor numerics"),
    ("phonemizer",    "IPA conversion for Bark / future engines"),
    # MLX-side packages (Qwen3-TTS family). Apple Silicon native, not PyTorch.
    ("mlx",           "Apple Silicon ML framework (Qwen3-TTS)"),
    ("mlx_audio",     "MLX inference wrapper for audio models (including OmniVoice)"),
    # VoxCPM (OpenBMB) — PyTorch + custom audiovae, official inference wrapper.
    ("voxcpm",        "VoxCPM TTS engine (OpenBMB official inference package)"),
    # F5-TTS (SWivid) — flow-matching voice cloning.
    ("f5_tts",        "F5-TTS flow-matching TTS engine"),
    ("vocos",         "VoCoS vocoder used by F5-TTS"),
]

_ENGINE_REQUIREMENTS = {
    "kokoro":         ["torch", "kokoro", "soundfile", "numpy"],
    "voxcpm":         ["torch", "voxcpm", "soundfile", "numpy"],
    "voxcpm-mlx":     ["mlx", "mlx_audio", "soundfile", "numpy"],
    "bark":           ["torch", "transformers", "soundfile", "accelerate"],
    # Other mlx-audio-backed families. All share the same package set, since
    # mlx-audio is the only inference dep.
    "qwen3-tts":      ["mlx", "mlx_audio", "soundfile", "numpy"],
    "kokoro-mlx":     ["mlx", "mlx_audio", "soundfile", "numpy"],
    "chatterbox-mlx": ["mlx", "mlx_audio", "soundfile", "numpy"],
    "spark-tts-mlx":  ["mlx", "mlx_audio", "soundfile", "numpy"],
    "orpheus":        ["mlx", "mlx_audio", "soundfile", "numpy"],
    "kittentts":      ["mlx", "mlx_audio", "soundfile", "numpy"],
    "vibevoice":      ["mlx", "mlx_audio", "soundfile", "numpy"],
    "omnivoice":      ["mlx", "mlx_audio", "torch", "transformers", "soundfile", "numpy"],
    # F5-TTS (PyTorch, flow-matching). Wired in v1.3.0.
    "f5-tts":     ["f5_tts", "torch", "vocos", "soundfile"],
}

# Which engines have an actual worker implemented in this app — i.e. picking
# one of these models won't trip a NotImplementedError. Keep in sync with the
# branches in `_dispatch_txt2speech` below + the MLX_AUDIO_FAMILIES table.
_WIRED_FAMILIES = {
    "kokoro", "voxcpm", "bark",
    # All mlx-audio-backed families share one worker.
    "qwen3-tts", "voxcpm-mlx", "kokoro-mlx",
    "chatterbox-mlx", "spark-tts-mlx", "orpheus",
    "kittentts", "vibevoice", "voxtral-tts", "marvis",
    "omnivoice",
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
}


# ───────────── Bark preset metadata ─────────────

# Bark ships 130+ preset speakers (v2/<lang>_speaker_0..9 across ~13 languages).
# We surface a curated set — all 10 English speakers + 2-3 popular per other
# language — to keep the picker manageable while letting users explore.
BARK_VOICE_PRESETS = [
    # ── English (all 10) ──
    {"id": "v2/en_speaker_0", "lang": "en", "label": "English · Speaker 0"},
    {"id": "v2/en_speaker_1", "lang": "en", "label": "English · Speaker 1"},
    {"id": "v2/en_speaker_2", "lang": "en", "label": "English · Speaker 2"},
    {"id": "v2/en_speaker_3", "lang": "en", "label": "English · Speaker 3"},
    {"id": "v2/en_speaker_4", "lang": "en", "label": "English · Speaker 4"},
    {"id": "v2/en_speaker_5", "lang": "en", "label": "English · Speaker 5"},
    {"id": "v2/en_speaker_6", "lang": "en", "label": "English · Speaker 6 (popular)"},
    {"id": "v2/en_speaker_7", "lang": "en", "label": "English · Speaker 7"},
    {"id": "v2/en_speaker_8", "lang": "en", "label": "English · Speaker 8"},
    {"id": "v2/en_speaker_9", "lang": "en", "label": "English · Speaker 9"},
    # ── Other languages — first 3 per language for variety ──
    {"id": "v2/zh_speaker_0", "lang": "zh", "label": "Chinese · Speaker 0"},
    {"id": "v2/zh_speaker_4", "lang": "zh", "label": "Chinese · Speaker 4"},
    {"id": "v2/ja_speaker_0", "lang": "ja", "label": "Japanese · Speaker 0"},
    {"id": "v2/ja_speaker_3", "lang": "ja", "label": "Japanese · Speaker 3"},
    {"id": "v2/ko_speaker_0", "lang": "ko", "label": "Korean · Speaker 0"},
    {"id": "v2/fr_speaker_0", "lang": "fr", "label": "French · Speaker 0"},
    {"id": "v2/fr_speaker_3", "lang": "fr", "label": "French · Speaker 3"},
    {"id": "v2/de_speaker_0", "lang": "de", "label": "German · Speaker 0"},
    {"id": "v2/de_speaker_3", "lang": "de", "label": "German · Speaker 3"},
    {"id": "v2/es_speaker_0", "lang": "es", "label": "Spanish · Speaker 0"},
    {"id": "v2/it_speaker_0", "lang": "it", "label": "Italian · Speaker 0"},
    {"id": "v2/pt_speaker_0", "lang": "pt", "label": "Portuguese · Speaker 0"},
    {"id": "v2/ru_speaker_0", "lang": "ru", "label": "Russian · Speaker 0"},
    {"id": "v2/hi_speaker_0", "lang": "hi", "label": "Hindi · Speaker 0"},
    {"id": "v2/pl_speaker_0", "lang": "pl", "label": "Polish · Speaker 0"},
    {"id": "v2/tr_speaker_0", "lang": "tr", "label": "Turkish · Speaker 0"},
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


def _probe_package(name: str) -> dict:
    try:
        import importlib
        mod = importlib.import_module(name)
        version = getattr(mod, "__version__", None)
        return {"installed": True, "version": version, "error": None}
    except Exception as e:
        return {"installed": False, "version": None, "error": f"{type(e).__name__}: {e}"}


def diagnostics() -> dict:
    """Per-package + per-engine health check. The frontend renders this as a
    checklist in the Generate tab so users see what's missing BEFORE they
    submit and hit a cryptic error."""
    pkg_results = []
    pkg_status: dict[str, bool] = {}
    for pkg, role in _PACKAGE_CHECKLIST:
        probe = _probe_package(pkg)
        pkg_results.append({"package": pkg, "role": role, **probe})
        pkg_status[pkg] = probe["installed"]

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
        "any_missing": any(not p["installed"] for p in pkg_results),
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
    # MLX-specific cache release. mlx.metal.clear_cache() was added around
    # mlx 0.18; older versions don't have it and the import fails silently.
    # Without this, MLX retains buffers from the previous generation and the
    # next mlx-audio call's activations stack on top → Metal alloc OOM.
    try:
        import mlx.core as mx
        if hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
            mx.metal.clear_cache()
        elif hasattr(mx, "clear_cache"):
            mx.clear_cache()
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
    provider: Optional[str] = None          # cloud provider key (None = local engine)
    provider_task_id: Optional[str] = None  # async provider task id — persisted so a
                                            # retry/restart RECALLS it instead of
                                            # re-submitting (never double-charge)
    provider_task_meta: dict = field(default_factory=dict)  # opaque recall URLs/tokens
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None

    def serialize(self) -> dict:
        duration = None
        if self.started_at is not None:
            end = self.finished_at if self.finished_at is not None else time.time()
            duration = max(0.0, end - self.started_at)
        return {
            "id": self.job_id,
            "mode": self.mode,
            "state": self.state,
            "provider": self.provider,
            "provider_task_id": self.provider_task_id,
            "progress": self.progress,
            "params": self.params,
            "output_path": self.output_path,
            "output_url": f"/api/generate/jobs/{self.job_id}/audio" if self.output_path else None,
            "resolved_seed": self.resolved_seed,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": duration,
        }


# ───────────── manager ─────────────

class GenerationManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, GenerationJob] = {}
        # Cache the loaded Kokoro pipeline per-language so we don't pay the
        # ~1 second model-load cost on every generation.
        self._kokoro_pipelines: dict[str, object] = {}
        # Cache one mlx-audio model at a time (loading is slow — 5-10s for
        # MLX 8-bit dequantization, longer for larger models). When the user
        # switches repos OR switches mlx-audio families (qwen3-tts → kokoro-mlx
        # → chatterbox-mlx etc.), we evict the old one to free Apple Silicon
        # unified memory. One cache slot is enough since unified memory is
        # shared — loading two large mlx-audio models would OOM anyway.
        self._mlx_audio_model = None
        self._mlx_audio_model_repo: Optional[str] = None
        # Same idea for VoxCPM v1 (PyTorch) — loading takes 10-20 seconds on
        # Apple Silicon (PyTorch + audiovae + tokenizer + optional torch.compile).
        self._voxcpm_model = None
        self._voxcpm_model_repo: Optional[str] = None
        # Bark — both the BarkModel and its AutoProcessor are cached together.
        self._bark_model = None
        self._bark_processor = None
        self._bark_model_repo: Optional[str] = None
        # F5-TTS — single F5TTS instance cached per repo. Holds the flow-matching
        # transformer + VoCoS vocoder (~1.5 GB on disk, more at runtime). Heavy
        # cold-start because the vocoder also loads from HF.
        self._f5_tts_model = None
        self._f5_tts_model_repo: Optional[str] = None
        self._load_history()
        self._resume_cloud_jobs()

    def is_available(self) -> bool:
        return TTS_AVAILABLE

    def list_jobs(self) -> list[GenerationJob]:
        return list(self._jobs.values())

    def get(self, job_id: str) -> Optional[GenerationJob]:
        return self._jobs.get(job_id)

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
                if not p.is_file() or p.suffix.lower() not in _AUDIO_OUTPUT_SUFFIXES:
                    continue
                try:
                    total += p.stat().st_size
                    count += 1
                except OSError:
                    pass
        return {"bytes": total, "count": count, "dir": str(OUTPUT_DIR.resolve())}

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
        job = GenerationJob(
            job_id=uuid.uuid4().hex[:12],
            mode="txt2speech",
            params=params,
            provider=(parsed[0] if parsed else None),   # cloud provider key, else None
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

    # ----- worker -----

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
            job.progress = 0.05          # move the bar off zero the moment work starts
            print(f"[gen] starting {job.job_id}: {job.params}", flush=True)

            if not TTS_AVAILABLE and not job.provider:
                job.state = "error"
                job.error = f"TTS engine not installed: {TTS_IMPORT_ERROR}"
                job.finished_at = time.time()
                self._persist()
                return

            output_path: Optional[Path] = None
            try:
                if job.provider:
                    output_path = self._run_cloud(job)
                else:
                    output_path = OUTPUT_DIR / f"{job.job_id}.wav"
                    self._dispatch_txt2speech(job, output_path)
                if job.cancel_event.is_set():
                    job.state = "cancelled"
                else:
                    job.output_path = str(output_path.resolve())
                    job.progress = 1.0
                    job.state = "done"
                    print(f"[gen] done {job.job_id} → {output_path}", flush=True)
            except Exception as e:
                if job.cancel_event.is_set():
                    job.state = "cancelled"
                else:
                    job.state = "error"
                    job.error = f"{type(e).__name__}: {e}"
                    print(f"[gen] error {job.job_id}: {job.error}", file=sys.stderr, flush=True)
                    traceback.print_exc()
                if output_path is not None:
                    try:
                        output_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            finally:
                job.finished_at = time.time()
                self._persist()

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
        api_key = P.get_api_key(prov.key)
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
        if adapter.is_async:
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
        else:
            job.progress = 0.2
            audio, mime = adapter.synthesize(api_key, text, model, voice, job.params)
        if not audio:
            raise RuntimeError(f"{prov.name} returned no audio data.")
        ext = "mp3" if ("mpeg" in (mime or "") or "mp3" in (mime or "")) else "wav"
        out = OUTPUT_DIR / f"{job.job_id}.{ext}"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio)
        return out

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
        if family == "kokoro":
            if not KOKORO_AVAILABLE:
                raise RuntimeError(
                    "The `kokoro` package isn't installed. Run 'Install Generation' "
                    "from the Pinokio sidebar (this installs the TTS deps including kokoro)."
                )
            self._generate_kokoro(job, model, output_path)
        elif family == "voxcpm":
            if not _have_voxcpm():
                raise RuntimeError(
                    "The `voxcpm` package isn't installed. Run 'Install Generation' "
                    "from the Pinokio sidebar (this installs the VoxCPM stack)."
                )
            self._generate_voxcpm(job, model, output_path)
        elif family == "bark":
            if not _have_bark():
                raise RuntimeError(
                    "BarkModel isn't importable from your installed transformers. "
                    "Run 'Install Generation' from the Pinokio sidebar to upgrade."
                )
            self._generate_bark(job, model, output_path)
        elif family == "f5-tts":
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

    # ----- Kokoro -----

    def _generate_kokoro(self, job: GenerationJob, model_entry, output_path: Path) -> None:
        """
        Run Kokoro via the `kokoro` KPipeline. Streams sentence-chunks of audio
        and concatenates them into a single 24 kHz WAV.

        Kokoro auto-loads weights from hexgrad/Kokoro-82M via huggingface_hub.
        Because we've already cached the repo through our own download manager,
        HF will find it in HF_HOME locally — no re-download.
        """
        import torch
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline

        params = job.params
        device = _detect_device()

        # Pick voice + language code from params
        voice = (params.get("voice") or "af_bella").strip()
        # Derive lang_code from the voice prefix if not explicitly given.
        # ('a' = American English, 'b' = British English)
        lang_code = (params.get("language") or "").strip().lower()
        if not lang_code:
            lang_code = voice[0] if voice and voice[0] in ("a", "b") else "a"
        if lang_code not in ("a", "b"):
            # Other languages (e/f/h/i/j/p/z) need misaki[<lang>] which often
            # depends on espeak-ng. Kokoro currently ships English-only here —
            # surface a clear error if the user picked an unsupported language.
            raise ValueError(
                f"Language '{lang_code}' isn't enabled for Kokoro yet. "
                "American (a) and British (b) English work today. "
                "Other languages need espeak-ng installed — not wired yet."
            )

        speed = float(params.get("speed", 1.0))
        speed = max(0.5, min(speed, 2.0))   # clamp to a sane range

        seed = params.get("seed")
        if seed is None or seed < 0:
            import random
            seed = random.randint(0, 2**32 - 1)
        job.resolved_seed = int(seed)
        torch.manual_seed(int(seed))
        if device == "mps":
            try:
                torch.mps.manual_seed(int(seed))
            except Exception:
                pass

        text = (params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        # Reuse a cached KPipeline per language so back-to-back generations
        # skip the ~1s model-load cost. KPipeline is thread-safe enough for
        # serial use behind _GEN_LOCK.
        pipeline = self._kokoro_pipelines.get(lang_code)
        if pipeline is None:
            print(f"[gen] loading Kokoro pipeline ({lang_code}) on {device}", flush=True)
            pipeline = KPipeline(lang_code=lang_code, device=device)
            self._kokoro_pipelines[lang_code] = pipeline

        if job.cancel_event.is_set():
            return

        print(f"[gen] generating {len(text)} chars with voice={voice} speed={speed}", flush=True)
        # KPipeline returns a generator yielding (graphemes, phonemes, audio)
        # for each sentence chunk. We concatenate the audio tensors.
        chunks: list[np.ndarray] = []
        # Rough chunk estimate for the progress bar — Kokoro's pipeline yields one
        # audio chunk per sentence, but we don't know the count up front. Capped at
        # 0.92 so it never overshoots; the worker snaps progress to 1.0 when the
        # WAV is written. (regex-free to avoid an extra import.)
        _est_chunks = max(1, len([p for p in text.replace("!", ".").replace("?", ".").replace("\n", ".").split(".") if p.strip()]))
        try:
            generator = pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+")
            for i, (gs, ps, audio) in enumerate(generator):
                if job.cancel_event.is_set():
                    print(f"[gen] cancel observed after chunk {i}", flush=True)
                    return
                # audio may be a torch tensor or numpy array; normalize to np
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                if audio.ndim > 1:
                    audio = audio.squeeze()
                chunks.append(audio.astype("float32"))
                job.progress = min(0.92, 0.05 + 0.9 * (i + 1) / _est_chunks)
        except Exception:
            # Drop the cached pipeline if generation blew up — it might be in
            # a bad state. Next call will reload.
            self._kokoro_pipelines.pop(lang_code, None)
            _release_device_memory(device)
            raise

        if not chunks:
            raise RuntimeError("Kokoro produced no audio. Try shorter text or a different voice.")

        full = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        sr = 24000   # Kokoro v1.0 always outputs 24 kHz
        sf.write(str(output_path), full, sr, format="WAV", subtype="PCM_16")
        print(f"[gen] saved WAV at {sr} Hz, {len(full) / sr:.2f}s: {output_path}", flush=True)

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
        self._mlx_audio_model = model
        self._mlx_audio_model_repo = repo
        return model

    def _generate_mlx_audio(self, job: GenerationJob, model_entry, output_path: Path) -> None:
        """
        Unified worker for every mlx-audio-backed TTS family.

        Per-family behavior is configured in MLX_AUDIO_FAMILIES — this function
        is purely scaffolding (load model, build kwargs, call generate_audio,
        save output). The mode resolvers below decide which kwargs to pass.

        mlx-audio's `generate_audio()` writes wav files to an output directory
        rather than returning bytes — we hand it a temp dir, then move the
        resulting `audio_000.wav` to our canonical path.
        """
        import shutil
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

        gen_kwargs: dict = {"text": text, "speed": speed}

        # Dispatch to the per-mode resolver to populate voice / clone / instruct
        # kwargs. Each resolver may raise ValueError if required inputs are missing.
        mode = family_config["mode"]
        mode_label = self._resolve_mlx_kwargs(mode, family, model_entry, params, gen_kwargs)

        # Optional cfg knobs — currently only VoxCPM2 uses them.
        if family_config.get("uses_cfg"):
            gen_kwargs["cfg_value"] = float(params.get("cfg_value", 2.0))
            gen_kwargs["inference_timesteps"] = int(params.get("inference_timesteps", 7))

        # Record seed for history — mlx-audio doesn't expose a seed kwarg in
        # current versions, but we want history "Reuse params" to make sense.
        seed = params.get("seed")
        if seed is None or seed < 0:
            import random
            seed = random.randint(0, 2**32 - 1)
        job.resolved_seed = int(seed)

        if job.cancel_event.is_set():
            return

        model = self._mlx_audio_get_model(model_entry.repo)

        # Unique temp dir per job so concurrent jobs (when we eventually allow
        # them) don't collide on the audio_000.wav name.
        temp_dir = Path(tempfile.mkdtemp(prefix=f"mlxaudio_{family}_{job.job_id}_"))
        try:
            log_extras = []
            if family_config.get("uses_cfg"):
                log_extras.append(f"steps={gen_kwargs['inference_timesteps']}")
                log_extras.append(f"cfg={gen_kwargs['cfg_value']}")
            extras = f" [{', '.join(log_extras)}]" if log_extras else ""
            print(
                f"[gen] {family} {mode_label} ({len(text)} chars){extras}",
                flush=True,
            )
            generate_audio(model=model, output_path=str(temp_dir), **gen_kwargs)

            produced = temp_dir / "audio_000.wav"
            if not produced.exists():
                # mlx-audio sometimes uses a different naming scheme — find any wav.
                candidates = sorted(temp_dir.glob("*.wav"))
                if not candidates:
                    raise RuntimeError(
                        f"mlx-audio didn't produce a wav file. Temp dir: {temp_dir}"
                    )
                produced = candidates[0]

            shutil.move(str(produced), str(output_path))
            sr = model_entry.sample_rate_hz or family_config["default_sample_rate"]
            print(f"[gen] {family} saved WAV at {sr} Hz: {output_path}", flush=True)
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
        """
        from . import voices as voices_module

        if mode == "qwen3":
            return self._mlx_kwargs_qwen3(model_entry, params, gen_kwargs, voices_module)
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
        raise RuntimeError(f"Unknown mlx-audio mode {mode!r} for family {family!r}")

    # --- per-mode kwarg builders ---

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
            if not voice_id:
                raise ValueError(
                    "Voice cloning needs a reference voice. Pick one from your Voices library — "
                    "go to the Voices tab to upload one if it's empty."
                )
            self._inject_voice_clone(voice_id, params, gen_kwargs, voices_module,
                                     fallback_transcript=".")
            return f"clone (voice={voice_id})"

        raise RuntimeError(f"Unknown qwen3-tts mode {mode!r}")

    def _mlx_kwargs_voxcpm_flex(self, params, gen_kwargs, voices_module) -> str:
        """VoxCPM2 (MLX) / Spark-TTS (MLX) / similar: any combination of
        ref_audio + ref_text + instruct. Falls back to zero-shot if neither
        is provided."""
        design_prompt = (params.get("voice_design_prompt") or params.get("instruct") or "").strip()
        if design_prompt:
            gen_kwargs["instruct"] = design_prompt

        voice_id = (params.get("voice_library_id") or "").strip() or None
        if voice_id:
            self._inject_voice_clone(voice_id, params, gen_kwargs, voices_module,
                                     fallback_transcript=".")

        if "ref_audio" in gen_kwargs and "instruct" in gen_kwargs:
            return "combined (clone + design)"
        if "ref_audio" in gen_kwargs:
            return "voice-cloning"
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
        gen_kwargs["voice"] = voice
        # Some voice-picker families (Orpheus) accept an optional instruct
        # for style nudges — forward it if present.
        instruct = (params.get("instruct") or "").strip()
        if instruct:
            gen_kwargs["instruct"] = instruct
        return f"voice={voice}" + (f" instruct={len(instruct)}c" if instruct else "")

    def _mlx_kwargs_clone_with_intensity(self, model_entry, params, gen_kwargs, voices_module) -> str:
        """Chatterbox (MLX): requires a reference audio for voice cloning,
        plus an optional `exaggeration` knob for emotion intensity."""
        voice_id = (params.get("voice_library_id") or "").strip()
        if not voice_id:
            raise ValueError(
                "Chatterbox needs a reference voice. Pick one from your Voices library."
            )
        self._inject_voice_clone(voice_id, params, gen_kwargs, voices_module,
                                 fallback_transcript="")
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
        return f"clone (voice={voice_id}, {detail})"

    def _mlx_kwargs_omnivoice(self, params, gen_kwargs, voices_module) -> str:
        """OmniVoice MLX supports voice design, cloning, or both together."""
        instruct = (params.get("voice_design_prompt") or "").strip()
        voice_id = (params.get("voice_library_id") or "").strip()
        if not instruct and not voice_id:
            raise ValueError(
                "OmniVoice needs either a reference voice or voice traits such as "
                "'female, british accent'."
            )
        if instruct:
            gen_kwargs["instruct"] = instruct
        if voice_id:
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
        if voice_id and instruct:
            return f"combined (clone={voice_id} + traits)"
        if voice_id:
            return f"clone (voice={voice_id})"
        return f"design ({len(instruct)} char traits)"

    def _mlx_kwargs_voice_or_clone(self, params, gen_kwargs, voices_module) -> str:
        """Spark-TTS (MLX): EITHER a voice picker (preset) OR a reference
        audio. If both, the reference clip wins (Spark prefers clone over preset)."""
        voice_id = (params.get("voice_library_id") or "").strip() or None
        if voice_id:
            self._inject_voice_clone(voice_id, params, gen_kwargs, voices_module,
                                     fallback_transcript=".")
            return f"clone (voice={voice_id})"

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
        voice = voices_module.library.get(voice_id)
        if voice is None:
            raise ValueError(f"Voice {voice_id} not found in library")
        ref_path = voices_module.library.reference_path(voice_id)
        if ref_path is None or not ref_path.exists():
            raise ValueError(f"Reference audio for voice {voice_id} is missing on disk")
        gen_kwargs["ref_audio"] = str(ref_path)
        ref_text = (params.get("ref_transcript") or "").strip()
        if not ref_text:
            ref_text = voices_module.library.transcript(voice_id) or ""
        gen_kwargs["ref_text"] = ref_text or fallback_transcript

    # ----- VoxCPM (OpenBMB) -----

    def _voxcpm_get_model(self, repo: str, device: str):
        """Lazy-load + cache the VoxCPM model. Evicts any previously-loaded
        VoxCPM model on repo switch (each model is several GB on MPS unified
        memory)."""
        if self._voxcpm_model_repo == repo and self._voxcpm_model is not None:
            return self._voxcpm_model

        if self._voxcpm_model is not None:
            print(f"[gen] evicting cached VoxCPM model ({self._voxcpm_model_repo})", flush=True)
            try:
                del self._voxcpm_model
            except Exception:
                pass
            self._voxcpm_model = None
            self._voxcpm_model_repo = None
            _release_device_memory(device)

        import voxcpm
        # v1.3.5 — explicit-path standard. Resolve our HF Hub cache snapshot
        # and pass it as the local path instead of the repo string. This
        # bypasses voxcpm's internal HF lookup entirely, so we're immune to
        # the kind of cache-layout drift that bit F5-TTS in v1.3.4 (where
        # cached_path has a non-HF-Hub layout). transformers' from_pretrained
        # accepts both repo strings and local paths interchangeably.
        snapshot_path = self._mlx_audio_snapshot_path(repo)
        print(f"[gen] loading VoxCPM model from {snapshot_path} on {device}", flush=True)
        # load_denoiser=False keeps the model self-contained — the modelscope
        # zipenhancer denoiser is several hundred MB and we don't currently
        # surface a denoise toggle. Re-enable when wiring the denoise UI.
        # optimize=False skips torch.compile — compile takes 30-60s on first
        # generation and benefits batch use more than one-off generations.
        model = voxcpm.VoxCPM.from_pretrained(
            str(snapshot_path),
            optimize=False,
            load_denoiser=False,
            device=device,
            local_files_only=True,
        )
        self._voxcpm_model = model
        self._voxcpm_model_repo = repo
        return model

    def _generate_voxcpm(self, job: GenerationJob, model_entry, output_path: Path) -> None:
        """
        Run VoxCPM v1 via the official `voxcpm` package. Two effective modes:

        - **Plain** (with optional emotion/tone control): just text, optionally
          prefixed with `(control_text)` for emotion. Reads `instruct` from
          params and wraps it in parentheses.
        - **Voice cloning (continuation)**: pair `voice_library_id` with
          `ref_transcript`. VoxCPM v1 calls this "continuation mode" and
          *requires* both the reference clip AND its transcript. If transcript
          is missing on the library voice, we error with a clear message.

        VoxCPM v1 does NOT support `reference_wav_path` (that's a v2-only
        argument), so we only use `prompt_wav_path` + `prompt_text`.
        """
        import soundfile as sf
        from . import voices as voices_module

        params = job.params
        device = _detect_device()

        text = (params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        # Emotion / tone control — wrapped in parentheses per VoxCPM convention.
        # Strip any pre-existing parens from the user's input so we don't break
        # the `(control)text` prompt format the model expects.
        import re
        control_raw = (params.get("instruct") or "").strip()
        control = re.sub(r"[()（）]", "", control_raw).strip()
        final_text = f"({control}){text}" if control else text

        # Voice-cloning path: needs both prompt_wav AND prompt_text.
        prompt_wav_path: Optional[str] = None
        prompt_text: Optional[str] = None
        voice_id = (params.get("voice_library_id") or "").strip() or None
        if voice_id:
            voice = voices_module.library.get(voice_id)
            if voice is None:
                raise ValueError(f"Voice {voice_id} not found in library")
            ref_path = voices_module.library.reference_path(voice_id)
            if ref_path is None or not ref_path.exists():
                raise ValueError(f"Reference audio for voice {voice_id} is missing on disk")
            # Transcript can come from explicit override or the library's
            # stored transcript. VoxCPM v1 requires both prompt_wav AND
            # prompt_text — empty transcript is not allowed.
            override = (params.get("ref_transcript") or "").strip()
            stored = voices_module.library.transcript(voice_id) or ""
            prompt_text = override or stored.strip()
            if not prompt_text:
                raise ValueError(
                    "VoxCPM voice cloning needs a transcript of the reference clip. "
                    "Edit the voice in your Voices library to add one, or provide "
                    "a transcript override in the Reference transcript field."
                )
            prompt_wav_path = str(ref_path)
            print(f"[gen] voxcpm continuation mode: ref={ref_path.name} transcript_len={len(prompt_text)}", flush=True)
        else:
            print(f"[gen] voxcpm plain mode (control: {control[:30]!r})", flush=True)

        cfg_value = float(params.get("cfg_value", 2.0))
        cfg_value = max(0.5, min(cfg_value, 8.0))
        inference_timesteps = int(params.get("inference_timesteps", 10))
        inference_timesteps = max(2, min(inference_timesteps, 50))
        normalize = bool(params.get("normalize_text", False))

        # Seed — VoxCPM doesn't expose a seed kwarg directly; we set torch
        # manual seed for reproducibility of the diffusion sampler.
        seed = params.get("seed")
        if seed is None or seed < 0:
            import random
            seed = random.randint(0, 2**32 - 1)
        job.resolved_seed = int(seed)
        try:
            import torch
            torch.manual_seed(int(seed))
            if device == "mps":
                try:
                    torch.mps.manual_seed(int(seed))
                except Exception:
                    pass
        except Exception:
            pass

        if job.cancel_event.is_set():
            return

        model = self._voxcpm_get_model(model_entry.repo, device)

        gen_kwargs: dict = {
            "text": final_text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
            "normalize": normalize,
            "denoise": False,
            "retry_badcase": True,
        }
        if prompt_wav_path:
            gen_kwargs["prompt_wav_path"] = prompt_wav_path
            gen_kwargs["prompt_text"] = prompt_text

        print(
            f"[gen] generating voxcpm "
            f"(text_len={len(final_text)}, cfg={cfg_value}, steps={inference_timesteps}, "
            f"normalize={normalize}, clone={bool(prompt_wav_path)})",
            flush=True,
        )
        wav = model.generate(**gen_kwargs)

        sr = int(getattr(getattr(model, "tts_model", None), "sample_rate", 16000) or 16000)
        # VoxCPM returns a 1D float32 numpy array; soundfile.write handles both
        # 1D mono and 2D (samples, channels) shapes.
        sf.write(str(output_path), wav, sr, format="WAV", subtype="PCM_16")
        print(f"[gen] voxcpm saved WAV at {sr} Hz: {output_path}", flush=True)

    # ----- Bark (Suno via transformers) -----

    def _bark_get_model(self, repo: str, device: str):
        """Lazy-load + cache the Bark model. Bark on MPS holds a lot of memory
        (the full bark is ~4 GB; bark-small ~1.6 GB) — evict on repo switch."""
        if self._bark_model_repo == repo and self._bark_model is not None:
            return self._bark_model, self._bark_processor

        if self._bark_model is not None:
            print(f"[gen] evicting cached Bark model ({self._bark_model_repo})", flush=True)
            try:
                del self._bark_model
                del self._bark_processor
            except Exception:
                pass
            self._bark_model = None
            self._bark_processor = None
            self._bark_model_repo = None
            _release_device_memory(device)

        from transformers import AutoProcessor, BarkModel
        # v1.3.5 — explicit-path standard. Resolve our HF Hub cache snapshot
        # and pass it as the local path instead of the repo string. See the
        # F5-TTS v1.3.4 fix for the failure mode this defends against.
        snapshot_path = self._mlx_audio_snapshot_path(repo)
        print(f"[gen] loading Bark from {snapshot_path} on {device}", flush=True)
        processor = AutoProcessor.from_pretrained(str(snapshot_path), local_files_only=True)
        model = BarkModel.from_pretrained(str(snapshot_path), local_files_only=True)
        model = model.to(device)
        model.eval()
        self._bark_model = model
        self._bark_processor = processor
        self._bark_model_repo = repo
        return model, processor

    def _generate_bark(self, job: GenerationJob, model_entry, output_path: Path) -> None:
        """
        Run Bark via transformers.BarkModel. Supports:

        - **Voice preset**: pass `bark_voice_preset` (e.g. "v2/en_speaker_6") for
          a specific speaker, or omit/null for Bark's random voice.
        - **Inline tags**: the user types `[laughter]`, `[singing]`, `♪ ♪`, etc.
          directly into the text — Bark recognizes these as non-verbal cues.
          The UI provides a quick-chip inserter so users don't have to remember
          tag syntax.

        Output is 24 kHz mono float32, saved as 16-bit PCM WAV.
        """
        import torch
        import numpy as np
        import soundfile as sf

        params = job.params
        device = _detect_device()

        text = (params.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        # Seed Bark for reproducibility — same text + voice + seed = same output.
        seed = params.get("seed")
        if seed is None or seed < 0:
            import random
            seed = random.randint(0, 2**32 - 1)
        job.resolved_seed = int(seed)
        try:
            torch.manual_seed(int(seed))
            if device == "mps":
                try:
                    torch.mps.manual_seed(int(seed))
                except Exception:
                    pass
        except Exception:
            pass

        voice_preset = (params.get("bark_voice_preset") or "").strip() or None
        if voice_preset:
            print(f"[gen] bark voice_preset={voice_preset}", flush=True)
        else:
            print(f"[gen] bark random voice (no preset)", flush=True)

        if job.cancel_event.is_set():
            return

        model, processor = self._bark_get_model(model_entry.repo, device)

        # Build processor inputs. AutoProcessor for Bark accepts voice_preset
        # as a string identifier — it resolves to the corresponding speaker
        # embedding internally.
        proc_kwargs = {"text": text, "return_tensors": "pt"}
        if voice_preset:
            proc_kwargs["voice_preset"] = voice_preset
        try:
            inputs = processor(**proc_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Bark processor rejected the input ({e}). "
                f"If you used a voice_preset, double-check the id (e.g. 'v2/en_speaker_6')."
            )
        # Move tensor inputs to the target device. BatchEncoding has a .to method.
        if hasattr(inputs, "to"):
            inputs = inputs.to(device)
        else:
            # Dict fallback for older transformers versions.
            inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}

        print(f"[gen] bark generating ({len(text)} chars)", flush=True)
        with torch.no_grad():
            try:
                audio_array = model.generate(**inputs)
            except Exception:
                # If the input was a dict (older transformers), retry with **inputs unchanged
                raise

        # `audio_array` shape varies: (batch=1, samples) → squeeze to 1D.
        audio_np = audio_array.detach().cpu().to(torch.float32).numpy()
        if audio_np.ndim > 1:
            audio_np = audio_np.squeeze()

        sr = int(getattr(getattr(model, "generation_config", None), "sample_rate", 24000) or 24000)
        sf.write(str(output_path), audio_np, sr, format="WAV", subtype="PCM_16")
        print(f"[gen] bark saved WAV at {sr} Hz, {len(audio_np)/sr:.2f}s: {output_path}", flush=True)

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
        if not voice_id:
            raise ValueError(
                "F5-TTS requires a reference voice (it has no zero-shot mode). "
                "Pick a voice from your Voices library."
            )

        voice = voices_module.library.get(voice_id)
        if voice is None:
            raise ValueError(f"Voice {voice_id} not found in library")
        ref_path = voices_module.library.reference_path(voice_id)
        if ref_path is None or not ref_path.exists():
            raise ValueError(f"Reference audio for voice {voice_id} is missing on disk")

        # Transcript: prefer per-request override, fall back to library entry.
        ref_text = (params.get("ref_transcript") or "").strip()
        if not ref_text:
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
                and j.provider_task_id
                and j.state in ("queued", "running")
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
        recoverable = [
            job for job in self._jobs.values()
            if job.provider
            and job.provider_task_id
            and job.state in ("queued", "running")
        ]
        for job in recoverable:
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
        if recoverable:
            print(
                f"[gen] resumed {len(recoverable)} cloud provider task(s)",
                flush=True,
            )

    @staticmethod
    def _to_disk(job: GenerationJob) -> dict:
        return {
            "job_id": job.job_id,
            "mode": job.mode,
            "state": job.state,
            "provider": job.provider,
            "provider_task_id": job.provider_task_id,
            "provider_task_meta": job.provider_task_meta,
            "progress": job.progress,
            "params": job.params,
            "output_path": job.output_path,
            "resolved_seed": job.resolved_seed,
            "error": job.error,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
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
                provider_task_id=raw.get("provider_task_id"),
                provider_task_meta=raw.get("provider_task_meta") or {},
                progress=raw.get("progress", 1.0),
                output_path=output_path,
                resolved_seed=raw.get("resolved_seed"),
                error=raw.get("error"),
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
            )
        except Exception:
            return None


manager = GenerationManager()
