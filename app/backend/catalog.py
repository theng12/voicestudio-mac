"""
Static catalog of text-to-speech models for VoiceStudio (Mac).

Each entry describes a Hugging Face repo plus metadata the UI uses: download
size (AFTER per-repo filtering), gating status, hardware floor, capabilities
(tts / voice-cloning / multilingual / expressive / streaming), and a long-form
"best for" description.

Capability vocabulary:
- "tts"             — basic text-to-speech with default voice(s)
- "voice-cloning"   — clones a target voice from a reference audio clip
- "multilingual"    — supports more than English
- "expressive"      — emotion / style tags or control sliders
- "streaming"       — supports real-time / streaming generation (low-latency)
- "lyrics"          — can sing (rare in open-source; ACE-Step does it elsewhere)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class TextGuidance:
    # Soft character threshold. None = effectively unlimited (sentence-chunked
    # under the hood). For "hard-cap" engines this is the cliff past which
    # output is known to degrade.
    soft_max_chars: Optional[int]
    # "unlimited"  — engine cleanly handles arbitrary length (Kokoro KPipeline)
    # "auto-split" — wrapper or engine splits long text by sentence and stitches
    # "hard-cap"   — fixed training-window past which output silences /
    #                hallucinates (Bark, Orpheus, XTTS). UI should soft-block.
    chunking: str
    # One-liner shown under the textarea + as the chip tooltip.
    note: str


@dataclass(frozen=True)
class Family:
    id: str
    label: str
    summary: str
    how_to_use: str
    text_guidance: TextGuidance


FAMILIES: dict[str, Family] = {
    "voxcpm": Family(
        id="voxcpm",
        label="VoxCPM",
        summary=(
            "OpenBMB's text-to-speech with voice cloning and voice design. Strong "
            "multilingual support including English, Chinese, and many others. "
            "VoxCPM2 is the newer release; both run on Apple Silicon via MPS."
        ),
        how_to_use=(
            "Provide text, optionally a reference audio clip (3–10 seconds) for "
            "voice cloning, and pick a language. Without a reference, it uses a "
            "default voice. Great for narration and conversational TTS."
        ),
        # Audit (v1.2.4): voxcpm/core.py:189 max_len=4096 audio tokens @ 6.25 Hz ≈ 11 min ENGINE max.
        # Hardware fix (v1.2.6 → 1.2.7): TWO ceilings hit simultaneously on 16 GB Macs:
        #   1) Metal per-buffer cap (~9.5 GB on M4): sequential voice-cloning jobs accumulated
        #      activation tensors across calls → OOM at 2nd job. Fixed by clearing MLX cache
        #      after each job in _generate_mlx_audio (v1.2.7).
        #   2) Quality cliff: user-reported voice drift / jibberish past ~30 sec of generated
        #      audio per call. Engine architecturally supports more but output quality fails.
        # Cap now reflects #2 (~60 sec @ ~13 chars/sec speech), with safety margin under #1.
        text_guidance=TextGuidance(
            soft_max_chars=800,
            chunking="auto-split",
            note="Best at ~800 chars (~60 sec audio) per call. Past ~30 sec, voice tends to drift / become jibberish — split into multiple shorter requests.",
        ),
    ),
    "kokoro": Family(
        id="kokoro",
        label="Kokoro",
        summary=(
            "Tiny (82M parameters), MIT-licensed, insanely fast TTS. Runs in real "
            "time even on M1 base models. English-focused with a handful of "
            "high-quality preset voices. No voice cloning — pick from the bundled "
            "voicepacks."
        ),
        how_to_use=(
            "Pick a voicepack (af_bella, am_michael, etc.) and provide text. "
            "Generation finishes in under a second per sentence. Best for "
            "scripted narration where you don't need to clone a specific voice."
        ),
        # Audit (v1.2.4): KPipeline auto-chunks on `split_pattern=r"\n+"` — no per-call ceiling.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="unlimited",
            note="No practical length limit — long text auto-splits into sentences and stitches transparently.",
        ),
    ),
    "f5-tts": Family(
        id="f5-tts",
        label="F5-TTS",
        summary=(
            "High-quality flow-matching TTS with voice cloning from a short "
            "reference clip. Strong English performance; multilingual checkpoints "
            "available. Released by SWivid; non-commercial license."
        ),
        how_to_use=(
            "Upload a 5–15 second voice reference, paste your text, and "
            "generate. Quality is among the best open-source for voice cloning. "
            "Slower than Kokoro — expect 5–10 seconds of compute per sentence."
        ),
        # Audit (v1.2.4): f5_tts/infer/utils_infer.py chunk_text(max_chars=135) auto-splits +
        # 0.15s crossfade. Engine handles long-form transparently; soft cap would mislead.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="unlimited",
            note="No practical length limit — auto-chunks long text and crossfades segments. Keep ref clip 5-15 sec for best results.",
        ),
    ),
    "bark": Family(
        id="bark",
        label="Suno Bark",
        summary=(
            "Suno's text-to-audio model. Generates expressive speech with embedded "
            "tags ([laughter], [sighs], [singing], [MUSIC]). Slower than dedicated "
            "TTS models but uniquely expressive. MIT licensed."
        ),
        how_to_use=(
            "Use special tags in the prompt for non-speech: [laughter], [sighs], "
            "[gasps], [MUSIC], [singing]. Pick a preset voice (v2/en_speaker_0..9) "
            "or use the random default. Great for character voices and dramatic "
            "delivery; less precise than F5-TTS for plain narration."
        ),
        # Audit (v1.2.4): Suno's FAQ — "output limited to ~13-14 seconds" (GPT-style with
        # 1024-token semantic/coarse context). Our _generate_bark feeds whole text one-shot.
        text_guidance=TextGuidance(
            soft_max_chars=150,
            chunking="hard-cap",
            note="Hard cap ~150 chars (~13 sec). Past the cap, Bark hallucinates or goes silent — split into short lines.",
        ),
    ),
    "voxcpm-mlx": Family(
        id="voxcpm-mlx",
        label="VoxCPM2 (MLX)",
        summary=(
            "OpenBMB's VoxCPM2 ported to MLX for native Apple Silicon inference "
            "(via Prince Canuma's mlx-audio). 2B parameters, 30 languages, 48 kHz "
            "studio-quality output, faster-than-realtime on M-series chips. "
            "Combines voice cloning + voice design + zero-shot into one model. "
            "Strictly better than VoxCPM v1 if you have mlx-audio installed."
        ),
        how_to_use=(
            "Three modes activate based on what you fill in: leave both fields "
            "blank → zero-shot with the default voice; type a natural-language "
            "voice description → voice design; pick a reference voice from your "
            "library → voice cloning (transcript optional but recommended). You "
            "can also combine the description + library voice for stylized cloning."
        ),
        # Audit (v1.2.4): mlx_audio voxcpm/voxcpm.py:259 max_tokens=4096 @ 6.25 Hz ≈ 11 min ENGINE max.
        # Hardware fix (v1.2.6 → 1.2.7): TWO ceilings hit on 16 GB Macs:
        #   1) Metal per-buffer cap (~9.5 GB on M4): sequential voice-cloning jobs accumulated
        #      activations across calls → OOM at 2nd call. Fixed by clearing MLX cache after
        #      each job in _generate_mlx_audio (v1.2.7).
        #   2) Quality cliff: user-reported voice drift / jibberish past ~30 sec audio per call.
        # Cap now reflects the quality cliff (~60 sec @ ~13 chars/sec) with safety margin.
        text_guidance=TextGuidance(
            soft_max_chars=800,
            chunking="auto-split",
            note="Best at ~800 chars (~60 sec audio) per call. Past ~30 sec, voice tends to drift / become jibberish — split into multiple shorter requests.",
        ),
    ),
    "qwen3-tts": Family(
        id="qwen3-tts",
        label="Qwen3-TTS (MLX)",
        summary=(
            "Alibaba's Qwen3-TTS, quantized to 8-bit and ported to MLX for native "
            "Apple Silicon inference (via Prince Canuma's mlx-audio). Two model "
            "tiers (0.6B / 1.7B) × two specialties (CustomVoice cloning / "
            "VoiceDesign from natural-language descriptions). Apache-2.0."
        ),
        how_to_use=(
            "Pick by use case. CustomVoice variants take a reference clip and "
            "clone that voice. VoiceDesign takes a natural-language prompt like "
            "'deep male voice, slow, contemplative' and synthesizes a matching "
            "voice without needing audio. 1.7B variants are noticeably better; "
            "0.6B is faster on lower-memory Macs."
        ),
        # Audit (v1.2.4): mlx_audio qwen3_tts/qwen3_tts.py:1149 max_tokens=4096 per segment
        # @ 12 Hz ≈ 5.7 min. Default split_pattern="\n" for transparent text splitting.
        text_guidance=TextGuidance(
            soft_max_chars=3000,
            chunking="auto-split",
            note="Best at ~3000 chars (~5.7 min audio) per call. Auto-splits on newlines — use \\n between paragraphs for clean cuts.",
        ),
    ),
    "kokoro-mlx": Family(
        id="kokoro-mlx",
        label="Kokoro (MLX)",
        summary=(
            "Kokoro 82M ported to MLX for native Apple Silicon inference (via "
            "Prince Canuma's mlx-audio). Same tiny + fast TTS as PyTorch Kokoro, "
            "but with the lower memory footprint and faster cold-start of MLX. "
            "English-focused with 28 preset voicepacks. MIT licensed."
        ),
        how_to_use=(
            "Pick a voicepack (af_bella, am_michael, etc.) and provide text. "
            "Generation is sub-second per sentence on any Apple Silicon. Pick "
            "this over PyTorch Kokoro if you'd rather keep the PyTorch stack "
            "uninstalled — mlx-audio is your only dep."
        ),
        # Audit (v1.2.4): mlx-audio's kokoro auto-chunks at sentence boundaries — no per-call ceiling.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="unlimited",
            note="No practical length limit — long text auto-splits into sentences and stitches transparently.",
        ),
    ),
    "chatterbox-mlx": Family(
        id="chatterbox-mlx",
        label="Chatterbox (MLX)",
        summary=(
            "Resemble AI's Chatterbox ported to MLX for native Apple Silicon "
            "inference (via mlx-audio). Same MIT-licensed voice-cloning + "
            "expressive-intensity dial as the PyTorch original, runs on lower "
            "memory budgets thanks to MLX quantization."
        ),
        how_to_use=(
            "Pick a reference voice from your Voices library and provide text. "
            "Tune the exaggeration slider for more or less expressive delivery "
            "(values above 0.7 get dramatic fast). Recommended over PyTorch "
            "Chatterbox on M-series Macs — same quality, smaller memory budget."
        ),
        # Audit (v1.2.4): mlx_audio chatterbox_turbo.py:859 max_chars_per_chunk =
        # (max_tokens // 8) * 4. Default max_tokens=1000 → 500. Turbo uses 800 → 400.
        text_guidance=TextGuidance(
            soft_max_chars=500,
            chunking="auto-split",
            note="Best at ~500 chars (~40 sec) per call. Auto-chunks longer text; exaggeration may drift across chunks.",
        ),
    ),
    "spark-tts-mlx": Family(
        id="spark-tts-mlx",
        label="Spark-TTS (MLX)",
        summary=(
            "SparkAudio's Spark-TTS ported to MLX for native Apple Silicon "
            "inference (via mlx-audio). 0.5B-parameter LLM-based TTS with "
            "zero-shot voice cloning + natural-language style control. Apache-2.0."
        ),
        how_to_use=(
            "Two modes: zero-shot with a default voice (just type text), or "
            "voice cloning by picking a reference voice from your library. "
            "Spark also accepts natural-language style hints — feed them via "
            "the voice description field."
        ),
        # Audit (v1.2.4): same as spark-tts — mlx_audio spark/spark.py:229 max_tokens=3000
        # audio tokens, BiCodec local stream ~50 Hz → ~60 sec audio ≈ ~780 chars.
        text_guidance=TextGuidance(
            soft_max_chars=750,
            chunking="auto-split",
            note="Best at ~750 chars (~60 sec audio) per call. Auto-chunks longer text by sentence.",
        ),
    ),
    "orpheus": Family(
        id="orpheus",
        label="Orpheus (MLX)",
        summary=(
            "Canopy Labs' Orpheus — a 3B-parameter LLaMA-architecture TTS with "
            "expressive emotion tags (<laugh>, <sigh>, <cough>, <giggle>, "
            "<gasp>, <yawn>) and named preset voices. Quantized to MLX for "
            "native Apple Silicon. Apache-2.0."
        ),
        how_to_use=(
            "Pick a preset voice (tara, dan, leah, etc.) and provide text. "
            "Embed emotion tags inline — '<laugh> That was hilarious!' — for "
            "expressive delivery. 4-bit is the recommended pick for most users; "
            "bf16 only if you want maximum fidelity."
        ),
        # Audit (v1.2.4): mlx_audio llama/llama.py:367,525 max_tokens=1200 per segment.
        # Orpheus emits ~85 SNAC tokens/sec → ~14 sec audio. Architecture max is 8192 tokens.
        text_guidance=TextGuidance(
            soft_max_chars=170,
            chunking="hard-cap",
            note="Hard cap ~170 chars (~14 sec). Past the cap, Orpheus output degrades or silences — split into shorter lines.",
        ),
    ),
    "kittentts": Family(
        id="kittentts",
        label="KittenTTS (MLX)",
        summary=(
            "KittenML's KittenTTS — an ultra-tiny TTS (7M–74M parameters across "
            "Nano / Micro / Mini tiers) with 8 preset voices. Smaller than "
            "Kokoro by an order of magnitude. Apache-2.0. MLX port by the "
            "mlx-community via mlx-audio."
        ),
        how_to_use=(
            "Pick a preset voice (Bella, Jasper, Luna, Bruno, Rosie, Hugo, "
            "Kiki, Leo) and provide text. The Mini tier (~64M params at 4-bit) "
            "is the recommended quality/size balance; Nano (~7M) is the "
            "absolute lightest option for embedded / demo use. Requires "
            "espeak-ng on the system (`brew install espeak-ng` on macOS)."
        ),
        # Audit (v1.2.4): mlx_audio kitten_tts/kitten_tts.py:42 chunk_text(max_len=400)
        # auto-splits on sentence boundaries. Per-chunk ceiling 400 chars; engine auto-chunks.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="unlimited",
            note="No practical length limit — tiny model auto-chunks at ~400 chars per sentence and stitches transparently.",
        ),
    ),
    "vibevoice": Family(
        id="vibevoice",
        label="VibeVoice Realtime (MLX)",
        summary=(
            "Microsoft's VibeVoice-Realtime — a 0.5B Qwen2.5-based streaming "
            "TTS designed for low-latency real-time output. MIT-licensed. "
            "MLX port via mlx-audio. English-only today."
        ),
        how_to_use=(
            "Pick a preset voice (e.g. `en-Emma_woman`) and provide text. "
            "Built for streaming / long-form speech with sub-realtime latency. "
            "4-bit is the recommended pick; fp16 only if you have headroom."
        ),
        # Audit (v1.2.4): mlx_audio vibevoice/vibevoice.py:397 max_tokens=512 per segment
        # (~43 sec @ 12 Hz). Streaming architecture multi-segments transparently.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="unlimited",
            note="Designed for streaming. No practical length limit — auto-segments long text. May drift on very long single takes.",
        ),
    ),
    "omnivoice": Family(
        id="omnivoice",
        label="OmniVoice (MLX)",
        summary=(
            "k2-fsa's OmniVoice — a 0.6B-parameter diffusion language-model TTS "
            "supporting 600+ languages with voice design (gender / accent / age "
            "/ whisper via natural-language) and non-verbal symbols ([laughter], "
            "[cough]). MLX backend (experimental) by ailuntx. Apache-2.0. "
            "Diffusion LM in MLX + audio tokenizer on PyTorch — hybrid stack."
        ),
        how_to_use=(
            "Type your voice-design prompt into the Voice description field "
            "(e.g. 'female, british accent', 'elderly man, raspy, slow') and "
            "the text to speak. Generation is voice-design-only on the MLX "
            "backend today; voice cloning support will land once the upstream "
            "MLX loader exposes ref_audio. 4-bit is the recommended starter; "
            "fp32 only if you want maximum fidelity."
        ),
        # Audit (v1.2.4): mlx_audio omnivoice/omnivoice.py:483 — flow-matching (diffusion).
        # Takes explicit duration_s or estimates via RuleDurationEstimator. No GPT-style cliff.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="unlimited",
            note="No practical length limit. For multi-minute renders, splitting into multiple calls usually gives more consistent results.",
        ),
    ),
    "voxtral-tts": Family(
        id="voxtral-tts",
        label="Voxtral-4B-TTS (MLX)",
        summary=(
            "Voxtral-4B-TTS — a multilingual TTS with 20 built-in preset voices "
            "across 9 languages (English, French, Spanish, German, Italian, "
            "Portuguese, Dutch, Arabic, Hindi). No cloning needed. Runs faster "
            "than real-time on Apple Silicon (~0.97× RTF at 4-bit). MLX-native "
            "via mlx-audio."
        ),
        how_to_use=(
            "Pick a preset voice (e.g. `casual_male`, `cheerful_female`, "
            "`fr_female`, `hi_male`) and provide text. The voice name selects "
            "both the speaker and its language. 4-bit is the recommended pick "
            "for 8 GB Macs; bf16 only if you have 16 GB+ headroom."
        ),
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Handles long text by auto-chunking. 20 preset voices across 9 languages — the voice name sets the language.",
        ),
    ),
    "marvis": Family(
        id="marvis",
        label="Marvis TTS (MLX)",
        summary=(
            "Marvis TTS — a 250M-parameter CSM/Llama-based conversational TTS "
            "built by the mlx-audio author for low-latency streaming on Apple "
            "Silicon, iPhone and iPad. Ships 2 built-in voices and is fully "
            "self-contained (no gated dependencies). MLX-native. Apache-2.0."
        ),
        how_to_use=(
            "Pick one of the 2 built-in voices — `conversational_a` (female) "
            "or `conversational_b` (male) — and provide text. Optimised for "
            "natural conversational delivery and streaming; best on shorter "
            "conversational turns, longer text auto-segments."
        ),
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Conversational streaming model with 2 built-in voices. Best on shorter turns; long text auto-segments and may drift on very long single takes.",
        ),
    ),
}


@dataclass(frozen=True)
class ModelEntry:
    repo: str
    label: str
    family: str
    size_gb: float                       # approximate on-disk size AFTER filtering
    gated: bool
    min_unified_memory_gb: int = 8
    recommended_hardware: str = ""
    capabilities: tuple[str, ...] = ("tts",)
    best_for: str = ""
    sample_rate_hz: int = 24000           # most TTS engines output 22–24 kHz
    languages: tuple[str, ...] = ("en",)
    # huggingface_hub-style glob patterns of files to SKIP during download.
    # F5-TTS in particular ships 4–5 alternate checkpoints in one repo (different
    # training stages and vocoders) — keep just one. Chatterbox has multiple
    # t3_*.safetensors variants. See musicstudio's catalog for the prior art.
    ignore_patterns: tuple[str, ...] = ()
    # Structured per-model use cases — each entry is (kind, text) where kind is
    # one of "good" / "weak" / "avoid". The UI renders these as ✅ / ⚠️ / ❌
    # bullets so users can set realistic expectations BEFORE submitting.
    use_cases: tuple[tuple[str, str], ...] = field(default_factory=tuple)


CATALOG: tuple[ModelEntry, ...] = (
    # ──────────── VoxCPM family ────────────
    ModelEntry(
        repo="openbmb/VoxCPM2",
        label="VoxCPM2 (4.4B)",
        family="voxcpm",
        # Repo is 4.62 GB total — no duplicates, keep everything.
        size_gb=4.6,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended. 8 GB works but tight.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="The strongest open multilingual TTS available — supports 30+ languages with voice cloning. The recommended default if you want one model that handles English, Chinese, and beyond. Slower than Kokoro but much higher fidelity for cloned voices.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "ru", "ar", "hi", "+20 more"),
        use_cases=(
            ("good",  "Multilingual narration — 30+ languages from one model"),
            ("good",  "Voice cloning from a 3-15 sec reference (Voices library)"),
            ("good",  "Emotion / tone control via natural-language description"),
            ("good",  "Long-form content (audiobooks, podcasts) where consistency matters"),
            ("weak",  "Slower per-generation than Kokoro (10-20 sec for a paragraph)"),
            ("avoid", "8 GB Macs — model is 4.6 GB on disk + needs working memory. Use VoxCPM v1 instead."),
        ),
    ),
    ModelEntry(
        repo="openbmb/VoxCPM-0.5B",
        label="VoxCPM v1 (0.5B)",
        family="voxcpm",
        size_gb=1.6,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "multilingual"),
        best_for="The original VoxCPM at smaller scale — much faster than VoxCPM2 and still solid quality. Pick this on lower-memory machines or when you want quick iteration.",
        sample_rate_hz=24000,
        languages=("en", "zh"),
        use_cases=(
            ("good",  "Fast iteration on 8 GB Macs — much lighter than VoxCPM2"),
            ("good",  "English + Chinese narration"),
            ("good",  "Voice cloning when you have both reference audio AND a transcript"),
            ("weak",  "REQUIRES a reference transcript for voice cloning — empty transcript will error"),
            ("avoid", "Languages beyond English / Chinese — use VoxCPM2 for those"),
            ("avoid", "Emotion control — VoxCPM v1's expressivity is weaker than v2"),
        ),
    ),

    # ──────────── Kokoro ────────────
    ModelEntry(
        repo="hexgrad/Kokoro-82M",
        label="Kokoro v1.0 (82M)",
        family="kokoro",
        # Only kokoro-v1_0.pth (312 MB) + tiny config files.
        size_gb=0.34,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac. Real-time on M1 base.",
        capabilities=("tts", "streaming"),
        best_for="The recommended starter — tiny, MIT, real-time. Use for narration, audiobook drafts, voiceover scratch tracks. No voice cloning, but the bundled preset voices are surprisingly good.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Audiobook + podcast narration — 28 preset voices to pick from"),
            ("good",  "YouTube voiceover scratch tracks (real-time on any Apple Silicon)"),
            ("good",  "Quick text-to-speech for blog posts, articles, scripts"),
            ("good",  "MIT licensed — commercial use OK"),
            ("avoid", "Voice cloning — Kokoro uses fixed voicepacks, can't clone your reference"),
            ("avoid", "Non-English content — only American + British English are wired today"),
            ("avoid", "Expressive / emotional delivery — Kokoro is steady-narrator, not character-acting"),
        ),
    ),

    # ──────────── F5-TTS ────────────
    ModelEntry(
        repo="SWivid/F5-TTS",
        label="F5-TTS v1 Base",
        family="f5-tts",
        # Repo is 6.28 GB — ships 4 alternate checkpoints (F5TTS_Base/,
        # F5TTS_v1_Base/, F5TTS_Base_bigvgan/, F5TTS_v1_Base_no_zero_init/),
        # plus .pt + .safetensors dupes. Keep only the v1_Base safetensors.
        size_gb=1.3,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Best-in-class open-source voice cloning quality from a short reference clip (5–15 seconds). Slower per-generation than VoxCPM but often more natural for English voices. Non-commercial license — fine for personal use.",
        sample_rate_hz=24000,
        languages=("en",),
        ignore_patterns=(
            "F5TTS_Base/*",
            "F5TTS_Base_bigvgan/*",
            "F5TTS_v1_Base_no_zero_init/*",
            "F5TTS_v1_Base/*.pt",          # keep only .safetensors of v1_Base
        ),
        use_cases=(
            ("good",  "Best-in-class voice cloning quality for English"),
            ("good",  "Natural English prosody — often beats VoxCPM v1 on native English voices"),
            ("good",  "Auto-chunks long text at ~135 chars + 0.15s crossfade — no manual splitting needed"),
            ("weak",  "Voice cloning only — no zero-shot mode. Requires a library voice with transcript."),
            ("weak",  "Non-commercial license — personal projects only"),
        ),
    ),

    # ──────────── Bark ────────────
    ModelEntry(
        repo="suno/bark",
        label="Suno Bark (full)",
        family="bark",
        # Repo is 20.68 GB — has both transformers-format pytorch_model.bin
        # (4.3) AND the original .pt checkpoints (16+ GB). Skip the .pt files.
        size_gb=4.3,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "expressive"),
        best_for="Character voices, dramatic narration, and audio with embedded tags ([laughter], [singing], [MUSIC]). Slower and less precise than dedicated TTS, but uniquely expressive. MIT licensed.",
        sample_rate_hz=24000,
        languages=("en", "zh", "fr", "de", "hi", "it", "ja", "ko", "pl", "pt", "ru", "es", "tr"),
        ignore_patterns=("*.pt",),
        use_cases=(
            ("good",  "Character voices + dramatic delivery (vs Kokoro's steady narrator)"),
            ("good",  "Inline non-verbal tags: [laughter], [sighs], [singing], [MUSIC]"),
            ("good",  "13 language support with preset speakers (en/zh/fr/de/ja/ko/+)"),
            ("good",  "MIT licensed"),
            ("weak",  "SLOW — 30-60 sec for a single sentence on M-series Macs"),
            ("weak",  "Less consistent than dedicated TTS — same prompt + seed can vary"),
            ("avoid", "Long-form narration — too slow + inconsistent. Use Kokoro / VoxCPM"),
            ("avoid", "Precise lip-sync or timing-critical work — Bark's pacing varies"),
        ),
    ),
    ModelEntry(
        repo="suno/bark-small",
        label="Suno Bark small",
        family="bark",
        size_gb=1.6,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any 8 GB+ Mac.",
        capabilities=("tts", "expressive"),
        best_for="Half-size Bark — most of the capability at lower fidelity. Run Bark's tag system on 8 GB machines or for quick iteration.",
        sample_rate_hz=24000,
        languages=("en", "zh", "fr", "de", "hi", "it", "ja", "ko", "pl", "pt", "ru", "es", "tr"),
        use_cases=(
            ("good",  "Try Bark's tag system on 8 GB Macs without the full download"),
            ("good",  "Faster iteration than full Bark (smaller model)"),
            ("weak",  "Lower fidelity than full Bark — final renders should use the full variant"),
            ("avoid", "Anything except experimentation — full Bark is the production-grade tier"),
        ),
    ),

    # ──────────── VoxCPM2 (MLX) ────────────
    # MLX ports of openbmb/VoxCPM2. 2B params, 30 languages, 48 kHz, one model
    # that does zero-shot + voice design + cloning. Inference via `mlx-audio`
    # — same library as Qwen3-TTS, so the worker shares load_model + generate.
    # Apache-2.0. 4-bit is the recommended pick (faster + smaller, minimal
    # quality loss per OpenBMB's own benchmarks).
    ModelEntry(
        repo="mlx-community/VoxCPM2-4bit",
        label="VoxCPM2 4-bit (MLX) — recommended",
        family="voxcpm-mlx",
        # 2.14 GB on HF — no duplicates to filter.
        size_gb=2.1,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. Fastest VoxCPM2 variant at near-realtime.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="The recommended VoxCPM2 pick for most users. 4-bit quantized — fastest and smallest, with minimal quality loss vs bf16. 48 kHz studio-quality output, 30 languages, voice cloning + voice design in one model.",
        sample_rate_hz=48000,
        languages=("en", "zh", "ja", "ko", "id", "fr", "de", "es", "it", "pt", "ru", "ar", "hi", "+19 more"),
        use_cases=(
            ("good",  "Recommended starter for multilingual TTS on Apple Silicon"),
            ("good",  "48 kHz studio output — sharpest sample rate in the catalog"),
            ("good",  "Zero-shot mode (just type text) OR voice cloning from library"),
            ("good",  "Voice design from natural-language prompt ('elderly male, gravelly')"),
            ("weak",  "4-bit quantization can occasionally fumble on rare-word pronunciation"),
            ("avoid", "Final renders where you can't afford ANY artifact — use 8-bit or bf16"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/VoxCPM2-8bit",
        label="VoxCPM2 8-bit (MLX)",
        family="voxcpm-mlx",
        size_gb=3.0,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="Higher-precision middle tier. Same capabilities as the 4-bit but with more headroom for nuanced prosody. Pick this if 4-bit shows quantization artifacts in your specific voice.",
        sample_rate_hz=48000,
        languages=("en", "zh", "ja", "ko", "id", "fr", "de", "es", "it", "pt", "ru", "ar", "hi", "+19 more"),
        use_cases=(
            ("good",  "Sweet spot — near-bf16 quality at ⅔ the size + speed"),
            ("good",  "Fix the rare 4-bit pronunciation fumbles without going full bf16"),
            ("good",  "Voice cloning + voice design + zero-shot in one model"),
            ("weak",  "Slower than 4-bit by ~30%"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/VoxCPM2-bf16",
        label="VoxCPM2 bf16 (MLX) — full precision",
        family="voxcpm-mlx",
        size_gb=4.6,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended for headroom.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="Full bf16 precision — slower (RTF ~0.5×) but the reference quality. Pick when you're doing final renders and quality matters more than speed.",
        sample_rate_hz=48000,
        languages=("en", "zh", "ja", "ko", "id", "fr", "de", "es", "it", "pt", "ru", "ar", "hi", "+19 more"),
        use_cases=(
            ("good",  "Reference quality — the bf16 weights are openbmb's published model"),
            ("good",  "Final renders, audiobook production, anything where artifacts can't slip through"),
            ("weak",  "Slowest VoxCPM2 variant — RTF ~0.5× (half realtime, so 2 min audio = 4 min compute)"),
            ("avoid", "8 GB Macs — tight memory will swap and slow generations further"),
            ("avoid", "Quick iteration — use 4-bit for the prompt scouting, then upgrade to bf16 for finals"),
        ),
    ),

    # ──────────── Qwen3-TTS (MLX) ────────────
    # All four variants come pre-quantized to 8-bit by mlx-community for native
    # Apple Silicon inference. Inference is via the `mlx-audio` package (not
    # transformers/diffusers), so the worker is a separate code path. Apache-2.0.
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
        label="Qwen3-TTS 0.6B Base — voice cloning (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=1.9,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. MLX-native (no PyTorch).",
        # Base model handles voice CLONING from a reference audio clip — pair
        # with a voice from the Voices library. Not a "plain TTS" model.
        capabilities=("tts", "voice-cloning", "multilingual"),
        best_for="Voice cloning at the smaller / faster tier. Pair with a reference clip from your Voices library and Qwen3-TTS will clone that voice. Pick this when memory is tight; the 1.7B CustomVoice is preferred for richer preset voices.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Smaller / faster voice cloning tier — 8 GB Mac friendly"),
            ("good",  "Multilingual cloning across en/zh/ja/ko/fr/de/+5 more"),
            ("good",  "MLX-native — no PyTorch install needed"),
            ("weak",  "Less prosodic nuance than the 1.7B tier — voice character may sound flatter"),
            ("avoid", "If you have 16 GB+, the 1.7B CustomVoice is a clearer pick"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
        label="Qwen3-TTS 0.6B CustomVoice — preset speakers (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=1.9,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        # CustomVoice = pick from 9 preset speakers (Ryan, Vivian, Sohee, etc.)
        # with optional emotion/tone instruction. NOT voice cloning.
        capabilities=("tts", "multilingual", "expressive"),
        best_for="9 preset speakers across English / Chinese / Japanese / Korean, with emotion control via natural-language instructions ('sad and crying, speaking slowly'). The fastest tier — pick this for quick narration with named voices.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Fastest Qwen3-TTS tier — 8 GB Mac friendly"),
            ("good",  "9 preset speakers (Ryan, Vivian, Sohee, Ono_Anna, etc.) across en/zh/ja/ko"),
            ("good",  "Emotion / tone steering via natural-language instructions"),
            ("avoid", "Voice cloning — this variant doesn't clone, use the Base variant for that"),
            ("avoid", "Final-quality work — the 1.7B CustomVoice is noticeably richer"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        label="Qwen3-TTS 1.7B CustomVoice — preset speakers (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=2.9,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="The recommended Qwen3-TTS pick. 9 preset speakers + emotion/tone control, at ~3× the params of the 0.6B — noticeably more natural prosody and richer voice character. Still fast on Apple Silicon thanks to MLX 8-bit.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Recommended Qwen3-TTS pick — best balance of quality + speed"),
            ("good",  "9 preset speakers with rich prosody (much better than 0.6B)"),
            ("good",  "Emotion / tone control via natural-language instructions"),
            ("good",  "Multilingual: en/zh/ja/ko + 7 more"),
            ("avoid", "Voice cloning — use the 0.6B Base variant for that"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        label="Qwen3-TTS 1.7B VoiceDesign (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=2.9,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="The standout feature: voice design from natural-language prompts. 'A deep male voice, slow, gravelly, like a 60-year-old narrator' — no reference clip needed. Pick this when you want a specific voice character without sourcing reference audio.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Voice design from text — no reference audio needed"),
            ("good",  "Character creation: 'gruff old man', 'cheerful young woman', 'sinister whisper'"),
            ("good",  "Rapid iteration on voice character without sourcing clips"),
            ("weak",  "Same description twice may produce slightly different voices (no preset stability)"),
            ("avoid", "Cloning a specific real voice — use the 0.6B Base or VoxCPM2 for that"),
        ),
    ),

    # ──────────── Kokoro (MLX) ────────────
    # Kokoro 82M ported to MLX. All variants run on any Apple Silicon Mac
    # comfortably — pick by precision preference. bf16 is the safe default;
    # 4-bit shaves another ~50% off the memory footprint at marginal quality cost.
    ModelEntry(
        repo="mlx-community/Kokoro-82M-bf16",
        label="Kokoro 82M bf16 (MLX) — recommended",
        family="kokoro-mlx",
        size_gb=0.34,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac. Real-time on M1 base.",
        capabilities=("tts", "streaming"),
        best_for="The Kokoro starter on MLX. Tiny (~340 MB), real-time on any Apple Silicon, 28 preset voicepacks, MIT licensed. Pick this over PyTorch Kokoro if you'd rather not install PyTorch — mlx-audio is the only dep.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Same as PyTorch Kokoro (audiobook + podcast narration) without the PyTorch install"),
            ("good",  "Tiny — 340 MB on disk, sub-second per sentence"),
            ("good",  "MIT licensed, commercial use OK"),
            ("good",  "MLX-native — only mlx-audio as a dep"),
            ("avoid", "Voice cloning — use the same voicepacks as PyTorch Kokoro, can't clone"),
            ("avoid", "Non-English content — English-only voicepacks"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Kokoro-82M-4bit",
        label="Kokoro 82M 4-bit (MLX)",
        family="kokoro-mlx",
        size_gb=0.18,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac. Half the size of bf16 with no perceptible quality loss.",
        capabilities=("tts", "streaming"),
        best_for="Smallest Kokoro. Same quality as bf16 for narration use, half the disk + memory. Pick when you're packaging Kokoro into a larger pipeline and want every MB to count.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Smallest TTS in the catalog — only 180 MB on disk"),
            ("good",  "No perceptible quality drop from bf16 for narration use"),
            ("good",  "Ideal for embedding in larger pipelines / scripts"),
            ("avoid", "Same caveats as bf16 Kokoro — no voice cloning, English-only"),
        ),
    ),

    # ──────────── Chatterbox (MLX) ────────────
    # Resemble AI's Chatterbox ported to MLX. Voice cloning + expressive-
    # intensity dial. Pair with a Voices library reference clip.
    ModelEntry(
        repo="mlx-community/chatterbox-mlx-4bit",
        label="Chatterbox 4-bit (MLX) — recommended",
        family="chatterbox-mlx",
        size_gb=1.0,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. Drastically smaller than PyTorch Chatterbox.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="The recommended Chatterbox pick on Apple Silicon. Voice cloning from a short reference clip + the signature exaggeration / intensity dial, at a fraction of PyTorch Chatterbox's memory footprint. MIT licensed.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Expressive voice cloning — exaggeration dial for drama / restraint"),
            ("good",  "Character voices, audiobook narration with emotion"),
            ("good",  "MIT licensed, 8 GB Mac friendly"),
            ("weak",  "REQUIRES a reference voice from your library — no zero-shot mode"),
            ("weak",  "Exaggeration > 0.7 can produce unstable / glitchy output"),
            ("avoid", "Plain neutral narration — use Kokoro or VoxCPM2 instead (cleaner output)"),
            ("avoid", "Non-English content — English-only"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/chatterbox-mlx-8bit",
        label="Chatterbox 8-bit (MLX)",
        family="chatterbox-mlx",
        size_gb=1.7,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB for headroom.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Higher-precision Chatterbox if 4-bit shows quantization artifacts on your specific voice. Same capabilities, slightly more nuanced prosody.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Higher fidelity Chatterbox when 4-bit shows artifacts on your reference voice"),
            ("good",  "More nuanced prosody at the same expressivity settings"),
            ("weak",  "Slower + ~2× memory of 4-bit"),
            ("avoid", "8 GB Macs — too tight, stick with 4-bit"),
        ),
    ),
    # Newer mlx-community conversions (Jan 2026, mlx-audio 0.2.7). Different
    # repo namespace (no `-mlx` suffix) but same upstream + loader. Add as
    # alternatives — users with the old repos still work.
    ModelEntry(
        repo="mlx-community/chatterbox-4bit",
        label="Chatterbox 4-bit (MLX, 2026 build) — recommended",
        family="chatterbox-mlx",
        size_gb=0.6,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive", "multilingual"),
        best_for="Newer Chatterbox 4-bit MLX conversion (Jan 2026). Same upstream as chatterbox-mlx-4bit but smaller (~600 MB) and reports 23-language support. Recommended if you're picking Chatterbox fresh today.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "+16 more"),
        use_cases=(
            ("good",  "Newest MLX conversion of ResembleAI/chatterbox — smaller than the older `-mlx-` build"),
            ("good",  "23 languages — broader than the old build"),
            ("good",  "Same voice cloning + exaggeration knob"),
            ("weak",  "Same caveat: reference voice required, exaggeration > 0.7 gets glitchy"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/chatterbox-8bit",
        label="Chatterbox 8-bit (MLX, 2026 build)",
        family="chatterbox-mlx",
        size_gb=1.0,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive", "multilingual"),
        best_for="Higher-precision newer Chatterbox. Pick if 4-bit shows artifacts on your reference voice.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "+16 more"),
        use_cases=(
            ("good",  "Newer 8-bit conversion, 23 languages"),
            ("good",  "Voice cloning + exaggeration dial"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/chatterbox-fp16",
        label="Chatterbox fp16 (MLX, 2026 build) — full precision",
        family="chatterbox-mlx",
        size_gb=2.1,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "voice-cloning", "expressive", "multilingual"),
        best_for="Full-precision fp16 Chatterbox. Reference quality for final renders.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "+16 more"),
        use_cases=(
            ("good",  "Reference Chatterbox quality — no quantization"),
            ("weak",  "2.1 GB on disk — biggest standard Chatterbox tier"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/chatterbox-turbo-4bit",
        label="Chatterbox Turbo 4-bit (MLX) — faster variant",
        family="chatterbox-mlx",
        size_gb=0.6,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="ResembleAI's Chatterbox Turbo — faster sibling of standard Chatterbox. 4-bit MLX conversion. Same voice-cloning API; tradeoff is quality vs latency.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Faster inference than standard Chatterbox at the same precision"),
            ("good",  "Same voice cloning + exaggeration controls"),
            ("weak",  "Quality may differ subtly from standard Chatterbox — A/B test on your reference voice"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/chatterbox-turbo-8bit",
        label="Chatterbox Turbo 8-bit (MLX)",
        family="chatterbox-mlx",
        size_gb=1.0,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Higher-precision Chatterbox Turbo. Pick when Turbo 4-bit shows artifacts.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Faster than standard Chatterbox 8-bit"),
            ("good",  "Higher fidelity than Turbo 4-bit"),
        ),
    ),

    # ──────────── Spark-TTS (MLX) ────────────
    # SparkAudio's Spark-TTS ported to MLX. Zero-shot voice cloning + natural-
    # language style control. Apache-2.0. Variants actually published by
    # mlx-community: bf16, 4-6bit (mixed quant), 6bit, 8bit. No plain 4-bit.
    # Each repo also bundles wav2vec2-large-xlsr-53 (~1.26 GB) as reference
    # encoder, which dominates the on-disk size below.
    ModelEntry(
        repo="mlx-community/Spark-TTS-0.5B-4-6bit",
        label="Spark-TTS 0.5B 4-6bit (MLX) — recommended",
        family="spark-tts-mlx",
        size_gb=1.6,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="The smallest Spark-TTS MLX build — mixed 4-/6-bit quantization. Same Apache-2.0 license + zero-shot voice cloning, but with the smallest memory footprint. Recommended starter pick on 8 GB Macs.",
        sample_rate_hz=16000,
        languages=("en", "zh"),
        use_cases=(
            ("good",  "Smallest Spark-TTS MLX quant (model.safetensors ~300 MB)"),
            ("good",  "Apache-2.0 — commercial-friendly voice cloning"),
            ("good",  "Zero-shot (no reference) OR clone-from-reference modes"),
            ("good",  "Natural-language style hints ('cheerful young female')"),
            ("good",  "8 GB Mac friendly"),
            ("weak",  "16 kHz output — lower fidelity than Kokoro / VoxCPM2 (24 / 48 kHz)"),
            ("weak",  "English + Chinese only"),
            ("weak",  "wav2vec2 reference encoder (~1.26 GB) is bundled — dominates the on-disk size"),
            ("avoid", "Final-quality audiobook work — sample rate caps the polish"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Spark-TTS-0.5B-6bit",
        label="Spark-TTS 0.5B 6-bit (MLX)",
        family="spark-tts-mlx",
        size_gb=1.7,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Higher precision than 4-6bit mixed quant. Pick when 4-6bit shows quantization artifacts on your specific reference voice.",
        sample_rate_hz=16000,
        languages=("en", "zh"),
        use_cases=(
            ("good",  "Higher fidelity than 4-6bit at modest size bump"),
            ("good",  "Apache-2.0, 8 GB Mac friendly"),
            ("weak",  "Same 16 kHz output ceiling"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Spark-TTS-0.5B-8bit",
        label="Spark-TTS 0.5B 8-bit (MLX)",
        family="spark-tts-mlx",
        size_gb=1.7,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Higher-precision Spark-TTS. Pick when the 4-bit's quantization shows up in your specific reference voice, or when you want the cleanest possible cloned output.",
        sample_rate_hz=16000,
        languages=("en", "zh"),
        use_cases=(
            ("good",  "Higher fidelity Spark-TTS when 4-6bit shows artifacts"),
            ("good",  "Better preservation of subtle voice characteristics during cloning"),
            ("weak",  "Still 16 kHz sample rate — same fidelity ceiling"),
            ("avoid", "8 GB Macs — 4-6bit is the right pick"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Spark-TTS-0.5B-bf16",
        label="Spark-TTS 0.5B bf16 (MLX) — full precision",
        family="spark-tts-mlx",
        size_gb=2.3,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Full bf16 Spark-TTS — reference-quality voice cloning for final renders. Worth the extra GB if you have the memory.",
        sample_rate_hz=16000,
        languages=("en", "zh"),
        use_cases=(
            ("good",  "Reference Spark-TTS quality — no quantization"),
            ("good",  "Best for cloning subtle / hard-to-capture reference voices"),
            ("weak",  "2.3 GB on disk — biggest Spark-TTS tier"),
            ("avoid", "8 GB Macs — won't fit comfortably"),
        ),
    ),

    # ──────────── Orpheus (MLX) ────────────
    # Canopy Labs' Orpheus 3B — LLaMA-architecture TTS with expressive emotion
    # tags (<laugh>, <sigh>, etc.) and named preset voices. Apache-2.0.
    ModelEntry(
        repo="mlx-community/orpheus-3b-0.1-ft-4bit",
        label="Orpheus 3B 4-bit (MLX) — recommended",
        family="orpheus",
        size_gb=1.8,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "expressive"),
        best_for="The recommended Orpheus pick. 3B LLaMA-based TTS with expressive emotion tags (<laugh>, <sigh>, <gasp>) and named preset voices (tara, dan, leah, etc.). 4-bit makes it tractable on any Apple Silicon. Apache-2.0.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Expressive character voices with inline tags (<laugh>, <sigh>, <gasp>, <giggle>, <yawn>, <cough>)"),
            ("good",  "8 named preset voices: tara, dan, leah, jess, leo, mia, zac, zoe"),
            ("good",  "Apache-2.0 — commercial use OK"),
            ("good",  "Faster than Bark for similar expressive output"),
            ("weak",  "English-only"),
            ("avoid", "Voice cloning — Orpheus uses preset voices, no clone-from-reference"),
            ("avoid", "Long-form narration without tags — Kokoro is a better fit for plain text"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/orpheus-3b-0.1-ft-8bit",
        label="Orpheus 3B 8-bit (MLX)",
        family="orpheus",
        size_gb=3.4,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "expressive"),
        best_for="Quality middle tier for Orpheus. Pick when 4-bit's quantization shows in your output, or for final renders.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Sharper prosody than 4-bit at moderate memory cost"),
            ("good",  "Fewer 4-bit hallucinations on long sentences"),
            ("weak",  "16 GB recommended for headroom"),
            ("avoid", "8 GB Macs — stick with 4-bit"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/orpheus-3b-0.1-ft-bf16",
        label="Orpheus 3B bf16 (MLX) — full precision",
        family="orpheus",
        size_gb=6.4,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware="M2 Pro / M3 16 GB+ for comfortable headroom.",
        capabilities=("tts", "expressive"),
        best_for="Full bf16 precision Orpheus — reference quality at the cost of memory. Pick this for final renders where every bit of prosody counts.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Reference Orpheus quality — full bf16 weights"),
            ("good",  "Final renders for podcasts, character voice production"),
            ("weak",  "6.4 GB on disk — biggest Orpheus tier"),
            ("weak",  "Slowest of the three precision tiers"),
            ("avoid", "16 GB Macs — needs headroom, will be tight"),
        ),
    ),

    # ──────────── KittenTTS (MLX) ────────────
    # KittenML's tiny preset-voice TTS — Apache-2.0, loaded via mlx-audio.
    # Three size tiers (Nano / Micro / Mini); 8 preset voices: Bella, Jasper,
    # Luna, Bruno, Rosie, Hugo, Kiki, Leo. Needs espeak-ng on the system.
    ModelEntry(
        repo="mlx-community/kitten-tts-mini-0.8-4bit",
        label="KittenTTS Mini 4-bit (MLX) — recommended",
        family="kittentts",
        size_gb=0.07,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. Trivial RAM footprint.",
        capabilities=("tts",),
        best_for="The recommended KittenTTS pick. 63M-param 4-bit quant — smaller than a single Bark voice preset, but with 8 named voices and Apache-2.0 license. Real-time on any M-series.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Smallest TTS in the catalog by an order of magnitude (~70 MB)"),
            ("good",  "8 preset voices — Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo"),
            ("good",  "Apache-2.0 — commercial use OK"),
            ("good",  "Real-time + low memory — perfect for embedded / demo apps"),
            ("weak",  "Requires espeak-ng on the system (`brew install espeak-ng`)"),
            ("weak",  "English-only"),
            ("avoid", "Voice cloning — preset voices only"),
            ("avoid", "Final-quality audiobook production — use VoxCPM2 / F5-TTS"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/kitten-tts-mini-0.8-fp16",
        label="KittenTTS Mini fp16 (MLX)",
        family="kittentts",
        size_gb=0.15,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts",),
        best_for="Full-precision KittenTTS Mini — still tiny (~150 MB). Pick if 4-bit shows artifacts on a specific voice.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Higher fidelity when 4-bit Mini shows artifacts"),
            ("good",  "Still under 200 MB — basically free"),
            ("avoid", "Voice cloning — preset voices only"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/kitten-tts-micro-0.8-4bit",
        label="KittenTTS Micro 4-bit (MLX)",
        family="kittentts",
        size_gb=0.03,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts",),
        best_for="Middle tier — 27M params, ~30 MB on disk. Quality tradeoff vs Mini, but absurdly small.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "~30 MB total — even more compact than Mini"),
            ("good",  "8 preset voices, Apache-2.0"),
            ("weak",  "Voice quality below Mini — pick Mini unless size is critical"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/kitten-tts-nano-0.8-fp16",
        label="KittenTTS Nano fp16 (MLX) — smallest",
        family="kittentts",
        size_gb=0.03,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac. Runs basically anywhere.",
        capabilities=("tts",),
        best_for="The smallest TTS in the catalog. 14.6M params at fp16, well under 30 MB. For demos, embedded use, or testing — not final quality.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Smallest possible TTS — sub-30 MB, sub-second cold start"),
            ("good",  "Demo / embedded / proof-of-concept use"),
            ("weak",  "Voice quality is below Mini / Micro — Nano is the lightest tier"),
            ("avoid", "Production audio — pick Mini or another family"),
        ),
    ),

    # ──────────── VibeVoice Realtime (MLX) ────────────
    # Microsoft's streaming TTS — MIT, MLX port via mlx-audio.
    ModelEntry(
        repo="mlx-community/VibeVoice-Realtime-0.5B-4bit",
        label="VibeVoice Realtime 0.5B 4-bit (MLX) — recommended",
        family="vibevoice",
        size_gb=0.7,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "streaming"),
        best_for="Microsoft's VibeVoice-Realtime, 4-bit. Designed for streaming / real-time TTS — low latency, long-form friendly. MIT-licensed, 8 GB Mac friendly. Recommended starter.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Real-time / streaming TTS use cases"),
            ("good",  "Long-form generation without manual chunking"),
            ("good",  "MIT license — commercial-friendly"),
            ("good",  "Preset voices like `en-Emma_woman`"),
            ("weak",  "English-only (today)"),
            ("avoid", "Voice cloning — preset voices only"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/VibeVoice-Realtime-0.5B-8bit",
        label="VibeVoice Realtime 0.5B 8-bit (MLX)",
        family="vibevoice",
        size_gb=0.8,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "streaming"),
        best_for="Higher-precision VibeVoice — modest size bump over 4-bit, slightly cleaner output.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Slightly higher fidelity than 4-bit at minimal size cost"),
            ("good",  "Same MIT / streaming benefits"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/VibeVoice-Realtime-0.5B-fp16",
        label="VibeVoice Realtime 0.5B fp16 (MLX) — full precision",
        family="vibevoice",
        size_gb=1.0,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended for headroom.",
        capabilities=("tts", "streaming"),
        best_for="Full fp16 VibeVoice. Reference quality for streaming use. Worth picking if you have the memory.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Reference-quality streaming TTS"),
            ("weak",  "1 GB on disk — biggest VibeVoice tier"),
        ),
    ),

    # ──────────── OmniVoice (MLX) ────────────
    # k2-fsa's OmniVoice ported to MLX by ailuntx. 0.6B diffusion-LM TTS with
    # voice design + 646-language support. Apache-2.0. Voice cloning exists in
    # the official PyTorch API but isn't yet exposed in the experimental MLX
    # variant — voice-design only for now.
    ModelEntry(
        repo="mlx-community/OmniVoice-4bit",
        label="OmniVoice 0.6B 4-bit (MLX) — recommended",
        family="omnivoice",
        size_gb=0.5,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="The recommended OmniVoice pick. Tiny 4-bit quant of k2-fsa's 0.6B diffusion-LM TTS — covers 646 languages with voice design (gender / accent / age / whisper). Apache-2.0, commercial use OK. RTF ~0.025 (40× real-time).",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "es", "fr", "de", "ar", "hi", "ru", "+636 more"),
        use_cases=(
            ("good",  "Truly multilingual TTS — 646 languages from one tiny model"),
            ("good",  "Voice design via natural language ('female, british accent, slow')"),
            ("good",  "Non-verbal symbols inline ([laughter], [cough])"),
            ("good",  "Apache-2.0 — commercial use OK (rare for multilingual TTS)"),
            ("good",  "8 GB Mac friendly — only 0.5 GB on disk"),
            ("weak",  "Voice cloning NOT yet wired on the MLX backend (use VoxCPM2 or Spark for cloning)"),
            ("weak",  "Upstream MLX backend is marked experimental — quality may vary by language"),
            ("avoid", "Tasks requiring voice cloning today — wait for upstream MLX clone support"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/OmniVoice-8bit",
        label="OmniVoice 0.6B 8-bit (MLX)",
        family="omnivoice",
        size_gb=0.9,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="Higher-precision OmniVoice. Pick when 4-bit shows quantization artifacts in your target language or voice description. Still 8 GB Mac friendly.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "es", "fr", "de", "ar", "hi", "ru", "+636 more"),
        use_cases=(
            ("good",  "Higher fidelity when 4-bit shows artifacts in a specific language"),
            ("good",  "Apache-2.0 — commercial-friendly multilingual TTS"),
            ("weak",  "~2× memory of 4-bit, slightly slower"),
            ("avoid", "Voice cloning — not yet wired on MLX backend"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/OmniVoice-bfloat16",
        label="OmniVoice 0.6B bf16 (MLX)",
        family="omnivoice",
        size_gb=1.3,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="Full bf16 OmniVoice — reference quality at modest memory cost. Recommended over fp32 unless you specifically need fp32 numerics.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "es", "fr", "de", "ar", "hi", "ru", "+636 more"),
        use_cases=(
            ("good",  "Reference-quality OmniVoice at half the size of fp32"),
            ("good",  "Apache-2.0, 646 languages, voice design"),
            ("weak",  "12 GB recommended"),
            ("avoid", "8 GB Macs — use 4-bit or 8-bit instead"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/OmniVoice-fp32",
        label="OmniVoice 0.6B fp32 (MLX) — full precision",
        family="omnivoice",
        size_gb=2.4,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware="M2 Pro / M3 16 GB+ for comfortable headroom.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="Dense fp32 reference export. Mostly useful as a baseline against the quants — bf16 has the same numerics for inference at half the size.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "es", "fr", "de", "ar", "hi", "ru", "+636 more"),
        use_cases=(
            ("good",  "Numerical reference vs the quants for debugging quality drift"),
            ("weak",  "2.4 GB on disk — biggest OmniVoice tier"),
            ("weak",  "No quality gain over bf16 for inference"),
            ("avoid", "Day-to-day use — pick bf16 / 8-bit / 4-bit instead"),
        ),
    ),

    # ──────────── Voxtral-4B-TTS family (multilingual preset voices) ────────────
    ModelEntry(
        repo="mlx-community/Voxtral-4B-TTS-2603-mlx-4bit",
        label="Voxtral-4B-TTS 4-bit (MLX) — recommended",
        family="voxtral-tts",
        size_gb=2.5,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. ~0.97× RTF (faster than real-time).",
        capabilities=("tts", "multilingual"),
        best_for="The recommended Voxtral pick. 20 built-in preset voices across 9 languages — no cloning needed. Faster than real-time on Apple Silicon. Pick a voice name like casual_male / cheerful_female / fr_female / hi_male; the voice selects the language.",
        sample_rate_hz=24000,
        languages=("en", "fr", "es", "de", "it", "pt", "nl", "ar", "hi"),
        use_cases=(
            ("good",  "Multilingual preset narration — 20 voices across en/fr/es/de/it/pt/nl/ar/hi, no reference clip"),
            ("good",  "Quick voiceovers where you want a named voice instantly (casual/cheerful/neutral)"),
            ("good",  "Faster-than-real-time on 8 GB Apple Silicon"),
            ("good",  "More non-English voices than Qwen3-TTS (adds de/it/pt/nl/ar)"),
            ("weak",  "English only has 5 voices (casual/cheerful/neutral) — fewer than Kokoro's ~28"),
            ("avoid", "Voice cloning — Voxtral uses fixed preset voices, no clone-from-reference"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Voxtral-4B-TTS-2603-mlx-bf16",
        label="Voxtral-4B-TTS bf16 (MLX) — full precision",
        family="voxtral-tts",
        size_gb=8.0,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware="M2 Pro / M3 16 GB+ recommended.",
        capabilities=("tts", "multilingual"),
        best_for="Full-precision Voxtral — cleaner output than 4-bit for final renders. Same 20 voices / 9 languages. Pick only if you have 16 GB+; on 8 GB use the 4-bit.",
        sample_rate_hz=24000,
        languages=("en", "fr", "es", "de", "it", "pt", "nl", "ar", "hi"),
        use_cases=(
            ("good",  "Final-quality multilingual renders at the Voxtral tier"),
            ("good",  "Same 20 preset voices as 4-bit, cleaner prosody"),
            ("weak",  "~8 GB on disk + working memory"),
            ("avoid", "8 GB Macs — use the 4-bit instead"),
        ),
    ),

    # ──────────── Marvis TTS family (conversational, 2 preset voices) ────────────
    ModelEntry(
        repo="Marvis-AI/marvis-tts-250m-v0.1",
        label="Marvis TTS 250M (MLX)",
        family="marvis",
        size_gb=2.3,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. Built for low-latency streaming.",
        capabilities=("tts", "expressive"),
        best_for="A 250M CSM/Llama-based conversational TTS by the mlx-audio author, built for low-latency streaming on Apple Silicon. 2 built-in voices (conversational_a female, conversational_b male), fully self-contained. Apache-2.0.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Natural conversational delivery with 2 built-in voices (conversational_a / conversational_b)"),
            ("good",  "Low-latency / streaming use on 8 GB Apple Silicon"),
            ("good",  "Fully self-contained — no gated dependencies, Apache-2.0"),
            ("weak",  "Only 2 voices and English-only"),
            ("avoid", "Long single-take narration — best on shorter conversational turns"),
            ("avoid", "Voice cloning — uses its 2 built-in voices (clone support is roadmap upstream)"),
        ),
    ),
)


def get_model(repo: str) -> Optional[ModelEntry]:
    for m in CATALOG:
        if m.repo == repo:
            return m
    return None


def ignore_patterns_for(repo: str) -> tuple[str, ...]:
    """Return the per-repo download skip-list, or () if the repo is unknown
    or has no filtering. Used by downloads.py to thin out huge HF repos that
    ship redundant weight formats or alternate checkpoints."""
    m = get_model(repo)
    if m is None:
        return ()
    return m.ignore_patterns


# ───────────── Companion (helper) models ─────────────
#
# Some engines load a SECOND model at generation time — an audio codec /
# tokenizer that lives in a *different* HF repo than the catalog model. If we
# only download the catalog repo, the first generation triggers a surprise
# download (the user thinks the model is "ready" but then waits again).
#
# To make a download complete-on-first-run, every family whose engine pulls an
# external companion is listed here. downloads.py fetches these right after the
# main model, and /api/catalog marks a model "partial" until its companions are
# present too — so the cached badge stays honest.
#
# Each companion: {repo, allow_patterns, label}.
#   allow_patterns=None → whole repo. A tuple → only those files (used for
#   kyutai/moshiko-pytorch-bf16, where we need ONE codec file out of a ~15 GB
#   repo, NOT the whole thing).
#
# VERIFIED against the installed mlx-audio engine source:
#   - marvis (sesame)   → sesame.py: MIMI_REPO + Mimi.from_pretrained(...,
#                         filename="tokenizer-e351c8d8-checkpoint125.safetensors")
#   - orpheus (llama)   → llama.py loads mlx-community/snac_24khz
#   - chatterbox-mlx    → chatterbox.py loads mlx-community/S3TokenizerV2
# OmniVoice / Spark load their codecs from inside their own repo (no companion).
FAMILY_COMPANIONS: dict[str, tuple[dict, ...]] = {
    "marvis": (
        {
            "repo": "kyutai/moshiko-pytorch-bf16",
            "allow_patterns": ("tokenizer-e351c8d8-checkpoint125.safetensors",),
            "label": "Mimi audio codec",
        },
    ),
    "orpheus": (
        {
            "repo": "mlx-community/snac_24khz",
            "allow_patterns": None,
            "label": "SNAC 24 kHz codec",
        },
    ),
    "chatterbox-mlx": (
        {
            "repo": "mlx-community/S3TokenizerV2",
            "allow_patterns": None,
            "label": "S3 speech tokenizer",
        },
    ),
}


def companions_for(repo: str) -> tuple[dict, ...]:
    """Companion (codec/tokenizer) models the engine pulls at generation time
    for the family that owns `repo`. Empty tuple when the family is
    self-contained or the repo is unknown."""
    m = get_model(repo)
    if m is None:
        return ()
    return FAMILY_COMPANIONS.get(m.family, ())


def serialize_model(m: ModelEntry) -> dict:
    # Per-model hardware-fit verdict against the running Mac's detected RAM.
    # Lazy import dodges any potential cycle at module-load time.
    try:
        from . import system_info
        fit = system_info.fit_for(m.min_unified_memory_gb)
    except Exception:
        fit = None
    # Naming-compat with the imagestudio/musicstudio frontend code —
    # "apple_optimized" there refers to MLX. The default-ON "MLX only" filter
    # hides any model where this is False, so EVERY MLX-audio family must be
    # listed here. Keep this set in sync with generation.MLX_AUDIO_FAMILIES
    # (catalog.py can't import generation.py without a circular import, hence
    # the explicit enumeration). The "-mlx" suffix catches voxcpm-mlx /
    # kokoro-mlx / chatterbox-mlx / spark-tts-mlx; the rest are named.
    _MLX_AUDIO_FAMILIES = (
        "qwen3-tts", "orpheus", "kittentts", "vibevoice",
        "omnivoice", "voxtral-tts", "marvis",
    )
    apple_optimized = m.family.endswith("-mlx") or m.family in _MLX_AUDIO_FAMILIES
    return {
        "repo": m.repo,
        "label": m.label,
        "family": m.family,
        "family_label": FAMILIES[m.family].label,
        "size_gb": m.size_gb,
        "gated": m.gated,
        "min_unified_memory_gb": m.min_unified_memory_gb,
        "recommended_hardware": m.recommended_hardware,
        "capabilities": list(m.capabilities),
        "best_for": m.best_for,
        "sample_rate_hz": m.sample_rate_hz,
        # No fixed max duration for TTS — output length scales with text length.
        # Frontend will use text length as the user-visible cost signal instead.
        "max_duration_seconds": None,
        "languages": list(m.languages),
        "apple_optimized": apple_optimized,
        "quantization": None,
        "aliases": [],
        "ignore_patterns": list(m.ignore_patterns),
        # New in v1.1 — structured use cases + hardware fit verdict.
        "use_cases": [{"kind": k, "text": t} for k, t in m.use_cases],
        "fit": fit,
    }


def serialize_family(f: Family) -> dict:
    return {
        "id": f.id,
        "label": f.label,
        "summary": f.summary,
        "how_to_use": f.how_to_use,
        "text_guidance": {
            "soft_max_chars": f.text_guidance.soft_max_chars,
            "chunking": f.text_guidance.chunking,
            "note": f.text_guidance.note,
        },
    }
