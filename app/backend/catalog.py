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
        label="Suno Bark (MLX)",
        summary=(
            "Suno's text-to-audio model running natively through MLX. Generates expressive speech with embedded "
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
        # 1024-token semantic/coarse context). The MLX worker feeds the text one-shot.
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
            "This is the current VoxCPM architecture and replaces the older "
            "PyTorch v1 and duplicate v2 entries."
        ),
        how_to_use=(
            "Three modes activate based on what you fill in: leave both fields "
            "blank → zero-shot with the default voice; type a natural-language "
            "voice description → voice design; pick a reference voice from your "
            "library → voice cloning. A saved transcript automatically enables "
            "the highest-fidelity continuation-cloning path. You can also combine "
            "the description + library voice for controlled cloning."
        ),
        # VoxCPM publishes audio patch/context limits, not a word or character
        # limit. Real clone fidelity can drift after roughly 30 seconds, so Voice
        # Studio independently renders sentence-safe ~400-character sections and
        # reuses the original reference for every section.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long scripts auto-split into sentence-safe ~400-character sections. Every section reuses the original reference, then Voice Studio verifies and joins the audio.",
        ),
    ),
    "qwen3-tts": Family(
        id="qwen3-tts",
        label="Qwen3-TTS (MLX)",
        summary=(
            "Alibaba's Qwen3-TTS, quantized to 8-bit and ported to MLX for native "
            "Apple Silicon inference (via mlx-audio). Base models clone a reference "
            "voice, CustomVoice provides named speakers with emotion control, and "
            "VoiceDesign creates a voice from a description. Apache-2.0."
        ),
        how_to_use=(
            "Pick a Base model to clone a voice from a short reference clip. "
            "CustomVoice uses built-in preset speakers; it does not clone. "
            "VoiceDesign takes a natural-language prompt like "
            "'deep male voice, slow, contemplative' and synthesizes a matching "
            "voice without needing audio. Use 0.6B Base for speed or 1.7B Base "
            "for the strongest cloning quality."
        ),
        # Qwen's ICL/Base clone path bypasses mlx-audio's newline splitter. Voice
        # Studio therefore renders a long clone in short sentence-aware sections
        # and joins them with clean pauses before returning one chapter audio file.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long voice-clone scripts are split into short sentence-safe sections, rendered with the same reference, and joined with relaxed narration pauses into one chapter. No manual splitting needed.",
        ),
    ),
    "kokoro-mlx": Family(
        id="kokoro-mlx",
        label="Kokoro v1.0 (MLX)",
        summary=(
            "The latest Kokoro v1.0 82M release, ported to MLX for native Apple "
            "Silicon inference via mlx-audio. Tiny, fast, Apache-2.0 licensed, and bundled "
            "with 54 preset voices across nine language variants."
        ),
        how_to_use=(
            "Choose a language, pick a voice, and adjust speaking speed. You can "
            "optionally blend two voices in equal proportions. The selected voice "
            "sets the pronunciation pipeline automatically."
        ),
        # Voice Studio owns long-form sections for progress and all-or-nothing
        # validation. Kokoro then performs its model-native phoneme split inside
        # each section.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long scripts are split privately at sentence boundaries, rendered in stable sections, and returned as one final audio file.",
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
        # Resemble publishes a 1,000 generated-speech-token default, not a word
        # cap. Voice Studio converts that to conservative independent synthesis
        # windows: 500 characters for standard, 400 for Turbo.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long scripts auto-split at sentence boundaries (about 500 chars standard / 400 Turbo), then Voice Studio verifies and joins every section.",
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
        # Voice Studio supplies the acoustic budget and owns sentence-safe
        # sections; callers receive only the verified joined result.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long scripts are split privately into stable sections, joined into one final file, then receive the requested speed adjustment once.",
        ),
    ),
    "omnivoice": Family(
        id="omnivoice",
        label="OmniVoice (MLX)",
        summary=(
            "k2-fsa's OmniVoice — a 0.6B-parameter diffusion language-model TTS "
            "supporting 600+ languages with voice design (gender / accent / age "
            "/ whisper via natural-language) and non-verbal symbols ([laughter], "
            "[cough]). The current mlx-audio backend supports both voice design "
            "and zero-shot cloning from a 3–10 second clip. Apache-2.0."
        ),
        how_to_use=(
            "Choose a reference voice to clone it, enter voice traits to design a "
            "new voice, or combine both to steer the cloned delivery. The bf16 "
            "checkpoint is the supported MLX option; allow extra memory headroom "
            "for longer or higher-step generations."
        ),
        # Audit (v1.2.4): mlx_audio omnivoice/omnivoice.py:483 — flow-matching (diffusion).
        # Takes explicit duration_s or estimates via RuleDurationEstimator. No GPT-style cliff.
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long scripts are split privately into short sentence-safe sections using the same reference voice, then joined into one final file.",
        ),
    ),
    "fish-audio-mlx": Family(
        id="fish-audio-mlx",
        label="Fish Audio S2 Pro (MLX)",
        summary=(
            "Fish Audio's S2 Pro 5B multilingual TTS running through the MLX-Audio "
            "v0.4.6 backend. It supports zero-shot voice cloning from a reference "
            "clip plus expressive instruction prompts and includes its own codec."
        ),
        how_to_use=(
            "Choose a Fish S2 Pro checkpoint, optionally select a reference voice, "
            "and describe the delivery in the style field. Voice Studio privately "
            "splits long scripts at safe boundaries, joins the sections, and applies "
            "the requested final speed once. Check Fish Audio's license before "
            "commercial use: the public model license is research/non-commercial "
            "unless you have a separate commercial grant."
        ),
        text_guidance=TextGuidance(
            soft_max_chars=None,
            chunking="auto-split",
            note="Long scripts are split privately at sentence-safe ~300-character sections, rendered with the same clone/style controls, joined, and tempo-adjusted once.",
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
class LanguageSupport:
    """Truthful language capability metadata for catalog and Studio Hub clients.

    ``codes`` is present only when it is a complete, actionable enumeration.
    Large upstream coverage claims use a count/lower-bound instead of a
    fabricated pseudo-language such as ``+70 more``.
    """
    input_selection: str = "none"  # none | required | optional
    enumeration_status: str = "exact"  # exact | claimed_count | claimed_lower_bound
    codes: tuple[str, ...] = ()
    claimed_count: Optional[int] = None
    claimed_lower_bound: Optional[int] = None
    runtime_enforced: bool = False


VOXCPM2_LANGUAGE_CODES = (
    "ar", "my", "zh", "da", "nl", "en", "fi", "fr", "de", "el",
    "he", "hi", "id", "it", "ja", "km", "ko", "lo", "ms", "no",
    "pl", "pt", "ru", "es", "sw", "sv", "tl", "th", "tr", "vi",
)

CHATTERBOX_LANGUAGE_CODES = (
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
    "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
    "sw", "tr", "zh",
)


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
    language_support: Optional[LanguageSupport] = None
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

    # ──────────── Bark (MLX) ────────────
    ModelEntry(
        repo="mlx-community/bark",
        label="Suno Bark (MLX) — current",
        family="bark",
        # The repo duplicates every preset under speaker_embeddings/. Keep the
        # root v2/*.npz roster plus the two native MLX weight files.
        size_gb=4.5,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="Apple Silicon with 16 GB recommended; 12 GB is the practical floor.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="Native-MLX character voices, dramatic narration, and audio with embedded tags ([laughter], [singing], [MUSIC]). Includes all 130 v2 presets across 13 languages. MIT licensed.",
        sample_rate_hz=24000,
        languages=("en", "zh", "fr", "de", "hi", "it", "ja", "ko", "pl", "pt", "ru", "es", "tr"),
        ignore_patterns=("speaker_embeddings/*",),
        use_cases=(
            ("good",  "Native Apple Silicon character voices and dramatic delivery"),
            ("good",  "Inline non-verbal tags: [laughter], [sighs], [singing], [MUSIC]"),
            ("good",  "All 130 v2 preset speakers across 13 languages"),
            ("good",  "MIT licensed"),
            ("weak",  "Slow — Bark remains heavier than dedicated narration models"),
            ("weak",  "Less consistent than dedicated TTS — same prompt + seed can vary"),
            ("avoid", "Long-form narration — use Kokoro or VoxCPM instead"),
            ("avoid", "Precise lip-sync or timing-critical work — Bark's pacing varies"),
        ),
    ),

    # ──────────── VoxCPM2 (MLX) ────────────
    # MLX ports of openbmb/VoxCPM2. 2B params, 30 languages, 48 kHz, one model
    # that does zero-shot + voice design + cloning. Inference via `mlx-audio`
    # — same library as Qwen3-TTS, so the worker shares load_model + generate.
    # Apache-2.0. 4-bit is the recommended pick (faster + smaller, minimal
    # quality loss per the MLX conversion benchmarks). Keep bf16 as the
    # final-render tier; the 8-bit middle row has no distinct workflow.
    ModelEntry(
        repo="mlx-community/VoxCPM2-4bit",
        label="VoxCPM2 4-bit (MLX) — recommended",
        family="voxcpm-mlx",
        size_gb=2.3,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB. Fastest VoxCPM2 variant at near-realtime.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="The recommended VoxCPM2 pick for most users. 4-bit quantized — fastest and smallest, with minimal quality loss vs bf16. 48 kHz studio-quality output, 30 languages, voice cloning + voice design in one model.",
        sample_rate_hz=48000,
        languages=VOXCPM2_LANGUAGE_CODES,
        language_support=LanguageSupport(
            input_selection="none",
            enumeration_status="exact",
            codes=VOXCPM2_LANGUAGE_CODES,
        ),
        use_cases=(
            ("good",  "Recommended starter for multilingual TTS on Apple Silicon"),
            ("good",  "48 kHz studio output — sharpest sample rate in the catalog"),
            ("good",  "Zero-shot mode (just type text) OR voice cloning from library"),
            ("good",  "Voice design from natural-language prompt ('elderly male, gravelly')"),
            ("weak",  "4-bit quantization can occasionally fumble on rare-word pronunciation"),
            ("avoid", "Final renders where you can't afford a quantization artifact — use bf16"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/VoxCPM2-bf16",
        label="VoxCPM2 bf16 (MLX) — full precision",
        family="voxcpm-mlx",
        size_gb=5.0,
        gated=False,
        min_unified_memory_gb=12,
        recommended_hardware="M1 Pro / M2 16 GB recommended for headroom.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="Full bf16 precision — slower (RTF ~0.5×) but the reference quality. Pick when you're doing final renders and quality matters more than speed.",
        sample_rate_hz=48000,
        languages=VOXCPM2_LANGUAGE_CODES,
        language_support=LanguageSupport(
            input_selection="none",
            enumeration_status="exact",
            codes=VOXCPM2_LANGUAGE_CODES,
        ),
        use_cases=(
            ("good",  "Reference quality — the bf16 weights are openbmb's published model"),
            ("good",  "Final renders, audiobook production, anything where artifacts can't slip through"),
            ("weak",  "Slowest VoxCPM2 variant — RTF ~0.5× (half realtime, so 2 min audio = 4 min compute)"),
            ("avoid", "8 GB Macs — tight memory will swap and slow generations further"),
            ("avoid", "Quick iteration — use 4-bit for the prompt scouting, then upgrade to bf16 for finals"),
        ),
    ),

    # ──────────── Qwen3-TTS (MLX) ────────────
    # Four focused variants come pre-quantized to 8-bit by mlx-community for native
    # Apple Silicon inference. Inference is via the `mlx-audio` package (not
    # transformers/diffusers), so the worker is a separate code path. Apache-2.0.
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
        label="Qwen3-TTS 0.6B Base",
        family="qwen3-tts",
        size_gb=1.9,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware=(
            "Apple Silicon with 16 GB unified memory minimum; 24 GB preferred "
            "for normal memory pressure and faster generation."
        ),
        # Base model handles voice CLONING from a reference audio clip — pair
        # with a voice from the Voices library. Not a "plain TTS" model.
        capabilities=("tts", "voice-cloning", "multilingual"),
        best_for="Fast, memory-friendly voice cloning. Pair it with a reference clip from the Voices library; use the 1.7B Base model when likeness and prosody matter more than speed.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"),
        use_cases=(
            ("good",  "Qualified transcript-assisted voice cloning on 16 GB and 24 GB Macs"),
            ("good",  "Multilingual cloning across the ten upstream-supported languages"),
            ("good",  "MLX-native — no PyTorch install needed"),
            ("avoid", "8 GB Macs — measured urgent memory pressure and swap make production unsafe"),
            ("weak",  "Less prosodic nuance than the 1.7B tier — voice character may sound flatter"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
        label="Qwen3-TTS 0.6B CustomVoice — M1 preset speakers (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=1.9,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware=(
            "Any Apple Silicon Mac with 8 GB. The smaller preset-voice tier "
            "for memory-constrained M1 workers."
        ),
        capabilities=("tts", "multilingual", "expressive"),
        best_for=(
            "Ryan, Aiden, and the other nine Qwen preset speakers on 8 GB M1 "
            "workers. Prefer the 1.7B CustomVoice model on 16 GB machines when "
            "maximum prosody quality matters more than capacity."
        ),
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru"),
        use_cases=(
            ("good", "Smallest Qwen preset-speaker model for 8 GB Apple Silicon"),
            ("good", "Ryan and Aiden English voices with natural-language style control"),
            ("good", "MLX 8-bit runtime is about 1 GB smaller than the 1.7B tier"),
            ("weak", "Less prosodic depth than 1.7B CustomVoice"),
            ("avoid", "Voice cloning — use either Base variant for that"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
        label="Qwen3-TTS 1.7B Base — quality voice cloning (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=2.9,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware="Apple Silicon with 16 GB or more.",
        capabilities=("tts", "voice-cloning", "multilingual"),
        best_for="The preferred Qwen3 voice-cloning model. It uses the larger 1.7B Base checkpoint for better speaker likeness, phrasing, and cross-lingual consistency from the same short reference clip.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Best Qwen3 speaker likeness and natural prosody from a reference clip"),
            ("good",  "Multilingual and cross-lingual cloning across 11 languages"),
            ("good",  "MLX 8-bit keeps the larger model practical on Apple Silicon"),
            ("weak",  "Slower and roughly 1 GB larger than the 0.6B Base tier"),
            ("avoid", "8 GB Macs under memory pressure — use 0.6B Base instead"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        label="Qwen3-TTS 1.7B CustomVoice — preset speakers (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=2.9,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware="Apple Silicon with 16 GB or more.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="The recommended Qwen3-TTS pick. 9 preset speakers + emotion/tone control, at ~3× the params of the 0.6B — noticeably more natural prosody and richer voice character. Still fast on Apple Silicon thanks to MLX 8-bit.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Recommended Qwen3-TTS pick — best balance of quality + speed"),
            ("good",  "9 preset speakers with rich prosody (much better than 0.6B)"),
            ("good",  "Emotion / tone control via natural-language instructions"),
            ("good",  "Multilingual: en/zh/ja/ko + 7 more"),
            ("avoid", "Voice cloning — use either Base variant for that"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        label="Qwen3-TTS 1.7B VoiceDesign (MLX 8-bit)",
        family="qwen3-tts",
        size_gb=2.9,
        gated=False,
        min_unified_memory_gb=16,
        recommended_hardware="Apple Silicon with 16 GB or more.",
        capabilities=("tts", "multilingual", "expressive"),
        best_for="The standout feature: voice design from natural-language prompts. 'A deep male voice, slow, gravelly, like a 60-year-old narrator' — no reference clip needed. Pick this when you want a specific voice character without sourcing reference audio.",
        sample_rate_hz=24000,
        languages=("en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "ar"),
        use_cases=(
            ("good",  "Voice design from text — no reference audio needed"),
            ("good",  "Character creation: 'gruff old man', 'cheerful young woman', 'sinister whisper'"),
            ("good",  "Rapid iteration on voice character without sourcing clips"),
            ("weak",  "Same description twice may produce slightly different voices (no preset stability)"),
            ("avoid", "Cloning a specific real voice — use the 1.7B Base model for that"),
        ),
    ),

    # ──────────── Kokoro (MLX) ────────────
    # One curated MLX build only. The 4-bit repository currently occupies about
    # 670 MB because it bundles duplicate PyTorch + safetensors weights, so it is
    # larger on disk than this 340 MB bf16 build without a useful quality tradeoff.
    ModelEntry(
        repo="mlx-community/Kokoro-82M-bf16",
        label="Kokoro v1.0 82M (MLX bf16) — recommended",
        family="kokoro-mlx",
        size_gb=0.34,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware=(
            "Any Apple Silicon Mac with at least 8 GB unified memory. "
            "Real-time on M1 base."
        ),
        capabilities=("tts", "multilingual", "voice-mixing"),
        best_for="Fast local narration on any Apple Silicon Mac. This full-quality MLX build is only ~340 MB and includes all 54 Kokoro v1.0 voices across nine language variants.",
        sample_rate_hz=24000,
        languages=("en", "es", "fr", "hi", "it", "pt", "ja", "zh"),
        ignore_patterns=("*.pt",),  # MLX loads safetensors; skip duplicate PyTorch voicepacks.
        use_cases=(
            ("good",  "Audiobook, podcast, and video narration with 54 preset voices"),
            ("good",  "Tiny — 340 MB on disk with native MLX inference"),
            ("good",  "Apache-2.0 licensed, commercial use OK"),
            ("good",  "Optional equal blending of two voices for a custom timbre"),
            ("weak",  "Non-English voices have less training data than the strongest English voices"),
            ("avoid", "Voice cloning — Kokoro uses fixed voicepacks; use Qwen3 Base or Chatterbox"),
        ),
    ),

    # ──────────── Chatterbox (MLX) ────────────
    # Resemble AI's Chatterbox ported to MLX. Voice cloning + expressive-
    # intensity dial. Pair with a Voices library reference clip.
    ModelEntry(
        repo="mlx-community/chatterbox-4bit",
        label="Chatterbox 4-bit (MLX, 2026 build) — recommended",
        family="chatterbox-mlx",
        size_gb=0.6,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="Any Apple Silicon Mac with 8 GB.",
        capabilities=("tts", "voice-cloning", "expressive", "multilingual"),
        best_for="Compact 4-bit MLX conversion of ResembleAI/chatterbox (~600 MB on disk), reporting 23-language support. The recommended Chatterbox pick.",
        sample_rate_hz=24000,
        languages=CHATTERBOX_LANGUAGE_CODES,
        language_support=LanguageSupport(
            input_selection="required",
            enumeration_status="exact",
            codes=CHATTERBOX_LANGUAGE_CODES,
            runtime_enforced=True,
        ),
        use_cases=(
            ("good",  "Compact MLX conversion of ResembleAI/chatterbox (~600 MB on disk)"),
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
        languages=CHATTERBOX_LANGUAGE_CODES,
        language_support=LanguageSupport(
            input_selection="required",
            enumeration_status="exact",
            codes=CHATTERBOX_LANGUAGE_CODES,
            runtime_enforced=True,
        ),
        use_cases=(
            ("good",  "Newer 8-bit conversion, 23 languages"),
            ("good",  "Voice cloning + exaggeration dial"),
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
        language_support=LanguageSupport(
            input_selection="required",
            enumeration_status="exact",
            codes=("en",),
            runtime_enforced=True,
        ),
        use_cases=(
            ("good",  "Faster inference than standard Chatterbox at the same precision"),
            ("good",  "Same voice cloning + exaggeration controls"),
            ("weak",  "Quality may differ subtly from standard Chatterbox — A/B test on your reference voice"),
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
        size_gb=2.2,
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
        repo="mlx-community/Spark-TTS-0.5B-8bit",
        label="Spark-TTS 0.5B 8-bit (MLX)",
        family="spark-tts-mlx",
        size_gb=2.5,
        gated=False,
        min_unified_memory_gb=8,
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
        size_gb=2.9,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "voice-cloning", "expressive"),
        best_for="Full bf16 Spark-TTS — reference-quality voice cloning for final renders. Worth the extra GB if you have the memory.",
        sample_rate_hz=16000,
        languages=("en", "zh"),
        use_cases=(
            ("good",  "Reference Spark-TTS quality — no quantization"),
            ("good",  "Best for cloning subtle / hard-to-capture reference voices"),
            ("weak",  "2.9 GB on disk — biggest Spark-TTS tier"),
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
        size_gb=0.25,
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
        size_gb=0.3,
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
        size_gb=0.06,
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
        size_gb=1.2,
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
        size_gb=2.1,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="M1 Pro / M2 16 GB recommended for headroom.",
        capabilities=("tts", "streaming"),
        best_for="Full fp16 VibeVoice. Reference quality for streaming use. Worth picking if you have the memory.",
        sample_rate_hz=24000,
        languages=("en",),
        use_cases=(
            ("good",  "Reference-quality streaming TTS"),
            ("weak",  "2.1 GB on disk — biggest VibeVoice tier"),
        ),
    ),

    # ──────────── OmniVoice (MLX) ────────────
    # k2-fsa's OmniVoice through mlx-audio. The published 4-bit and 8-bit
    # conversions use a custom row-wise scale layout that the v0.4.6 generic
    # loader cannot load. Keep the compatible bfloat16 checkpoint visible.
    ModelEntry(
        repo="mlx-community/OmniVoice-bfloat16",
        label="OmniVoice 0.6B bf16 (MLX) — recommended",
        family="omnivoice",
        size_gb=2.0,
        gated=False,
        min_unified_memory_gb=8,
        recommended_hardware="M1 Pro / M2 16 GB recommended.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="The reliable OmniVoice MLX option for multilingual cloning and voice design. It preserves the reference checkpoint precision without the redundant fp32 download.",
        sample_rate_hz=24000,
        languages=(),
        language_support=LanguageSupport(
            enumeration_status="claimed_count",
            claimed_count=646,
        ),
        use_cases=(
            ("good",  "Reference-quality OmniVoice at half the size of fp32"),
            ("good",  "Apache-2.0, 646 languages, voice cloning and voice design"),
            ("weak",  "16 GB recommended; the published compact conversions are not compatible with the current MLX engine"),
        ),
    ),

    # ──────────── Fish Audio S2 Pro (MLX) ────────────
    # v0.4.6 is the first pinned mlx-audio release in this app with the Fish
    # S2 Pro engine. The model repo bundles its codec.safetensors, so it needs
    # no companion download. The public Fish model license is not commercial.
    ModelEntry(
        repo="mlx-community/fish-audio-s2-pro-8bit",
        label="Fish Audio S2 Pro 5B 8-bit (MLX) — fleet candidate",
        family="fish-audio-mlx",
        size_gb=6.73,
        gated=False,
        min_unified_memory_gb=24,
        recommended_hardware="Apple Silicon with 24 GB as the practical floor; 32 GB preferred for long-form cloning.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="The practical Fish S2 Pro MLX tier. It bundles the model and codec in about 6.73 GB, claims 80+ language coverage and supports reference-voice cloning, but the public Fish Audio research license is not a commercial-use grant.",
        sample_rate_hz=44100,
        languages=(),
        language_support=LanguageSupport(
            enumeration_status="claimed_lower_bound",
            claimed_lower_bound=80,
        ),
        use_cases=(
            ("good",  "High-quality multilingual voice cloning with natural-language style control"),
            ("good",  "Single download includes the S2 Pro model and bundled codec"),
            ("weak",  "24 GB unified memory is the practical floor; 32 GB is safer for long-form jobs"),
            ("avoid", "Commercial customer work unless you have Fish Audio's separate commercial license"),
        ),
    ),
    ModelEntry(
        repo="mlx-community/fish-audio-s2-pro-bf16",
        label="Fish Audio S2 Pro 5B bf16 (MLX)",
        family="fish-audio-mlx",
        size_gb=11.01,
        gated=False,
        min_unified_memory_gb=32,
        recommended_hardware="Apple Silicon with 32 GB or more; not suitable for the 8/16 GB fleet tier.",
        capabilities=("tts", "voice-cloning", "multilingual", "expressive"),
        best_for="Full-precision Fish S2 Pro for reference-quality cloning and qualification work on high-memory Apple Silicon Macs. The public model license is research/non-commercial unless separately licensed.",
        sample_rate_hz=44100,
        languages=(),
        language_support=LanguageSupport(
            enumeration_status="claimed_lower_bound",
            claimed_lower_bound=80,
        ),
        use_cases=(
            ("good",  "Full-precision reference tier for 32 GB+ Apple Silicon"),
            ("good",  "Same cloning and style controls as the 8-bit build"),
            ("weak",  "About 11.01 GB on disk before runtime memory and cache overhead"),
            ("avoid", "8/16 GB Macs and commercial use without a separate Fish license"),
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
# OmniVoice / Spark / Fish S2 Pro load their codecs from inside their own repo
# (no companion).
FAMILY_COMPANIONS: dict[str, tuple[dict, ...]] = {
    "bark": (
        {
            "repo": "mlx-community/encodec-24khz-float32",
            "allow_patterns": None,
            "label": "Encodec 24 kHz audio codec",
        },
        {
            # Bark imports this historical repo id directly. Cache only the
            # tokenizer assets; the multi-gigabyte BERT weights are not used.
            "repo": "bert-base-multilingual-cased",
            "allow_patterns": (
                "tokenizer.json",
                "tokenizer_config.json",
                "vocab.txt",
            ),
            "label": "Multilingual text tokenizer",
        },
    ),
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
    # Naming-compat with the sibling Studio frontends: "apple_optimized"
    # identifies MLX-native families for runtime labels and the opt-in filter.
    # Keep this set in sync with generation.MLX_AUDIO_FAMILIES
    # (catalog.py can't import generation.py without a circular import, hence
    # the explicit enumeration). The "-mlx" suffix catches voxcpm-mlx /
    # kokoro-mlx / chatterbox-mlx / spark-tts-mlx; the rest are named.
    _MLX_AUDIO_FAMILIES = (
        "qwen3-tts", "orpheus", "kittentts", "vibevoice",
        "omnivoice", "fish-audio-mlx", "voxtral-tts", "marvis", "bark",
    )
    apple_optimized = m.family.endswith("-mlx") or m.family in _MLX_AUDIO_FAMILIES
    try:
        from . import model_audits
        audited_input_limits = model_audits.input_limits(m.repo)
    except Exception:
        audited_input_limits = {}
    reference_profile = audited_input_limits.get("reference_audio")
    if not isinstance(reference_profile, dict):
        reference_profile = {}
    family_guidance = FAMILIES[m.family].text_guidance
    audited_text_max = audited_input_limits.get("text_max_characters")
    try:
        audited_text_max = int(audited_text_max) if audited_text_max is not None else None
    except (TypeError, ValueError):
        audited_text_max = None
    language_support = m.language_support or LanguageSupport(codes=m.languages)
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
        "language_support": {
            "input_selection": language_support.input_selection,
            "enumeration_status": language_support.enumeration_status,
            "codes": list(language_support.codes),
            "claimed_count": language_support.claimed_count,
            "claimed_lower_bound": language_support.claimed_lower_bound,
            "runtime_enforced": language_support.runtime_enforced,
        },
        "execution_contract": {
            # Public limits are qualification results, not optimistic guesses
            # from family guidance. An unaudited model remains available for
            # local testing without claiming a sellable 40k contract.
            "text_max_characters": audited_text_max,
            "long_form_strategy": audited_input_limits.get(
                "long_form_strategy"
            ) or "unverified",
            "private_section_max_characters": audited_input_limits.get(
                "private_section_max_characters"
            ),
            "qualification_source": "audit" if audited_input_limits else "unverified",
        },
        "reference_audio": {
            "supported": bool("voice-cloning" in m.capabilities),
            "profile_source": "audit" if reference_profile else "unverified",
            **reference_profile,
        },
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
