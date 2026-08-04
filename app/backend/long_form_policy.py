"""Authoritative private long-form delivery policy for local TTS models.

Callers submit one complete script.  Voice Studio uses these model-specific
budgets to render sentence-safe sections, validate them, and return one joined
artifact.  The catalog publishes this same data so the Models UI cannot drift
from the generation runtime.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


DEFAULT_JOIN_PAUSE_SECONDS = 0.12
QWEN_CLONE_JOIN_PAUSE_SECONDS = 0.18
QWEN_CLONE_SECTION_MAX_CHARACTERS = 288
QWEN_PRESET_SECTION_MAX_CHARACTERS = 360
CHATTERBOX_STANDARD_SECTION_MAX_CHARACTERS = 500
CHATTERBOX_TURBO_SECTION_MAX_CHARACTERS = 400
VOXCPM_SECTION_MAX_CHARACTERS = 400
KOKORO_SECTION_MAX_CHARACTERS = 3000
VIBEVOICE_SECTION_MAX_CHARACTERS = 3000
OMNIVOICE_SECTION_MAX_CHARACTERS = 288
FISH_AUDIO_SECTION_MAX_CHARACTERS = 300
# Audio8's native cap is 512 frames (~2048 samples/frame @ 44.1 kHz ≈ 23.8 sec)
# per call, no internal chunking. 280 chars leaves headroom under that budget
# at typical narration pacing (~15 chars/sec).
AUDIO8_SECTION_MAX_CHARACTERS = 280
# MOSS-TTS-Nano already auto-splits internally (~75 text-tokens/chunk) inside
# one generate() call, but Voice Studio still owns the outer boundary for
# progress reporting and mid-script cancellation. 300 chars keeps each owned
# section close to the model's own internal chunk size.
MOSS_TTS_NANO_SECTION_MAX_CHARACTERS = 300


@dataclass(frozen=True)
class LongFormPolicy:
    section_max_characters: int
    join_pause_seconds: float
    note: str
    split_method: str = "sentence_safe"
    customer_submits_complete_script: bool = True

    def serialize(self, *, source: str = "runtime_default") -> dict:
        payload = asdict(self)
        payload["join_pause_milliseconds"] = round(
            self.join_pause_seconds * 1000
        )
        payload["source"] = source
        return payload


def _qwen_mode(repo: str) -> str:
    name = repo.rsplit("/", 1)[-1].lower()
    if "base" in name:
        return "clone"
    if "voicedesign" in name:
        return "design"
    return "preset"


def _runtime_default(family: str, repo: str) -> Optional[LongFormPolicy]:
    name = repo.rsplit("/", 1)[-1].lower()
    if family == "qwen3-tts":
        if _qwen_mode(repo) == "clone":
            return LongFormPolicy(
                section_max_characters=QWEN_CLONE_SECTION_MAX_CHARACTERS,
                join_pause_seconds=QWEN_CLONE_JOIN_PAUSE_SECONDS,
                note=(
                    "Owner-verified clone continuity setting. Every section "
                    "reuses the same reference voice and transcript evidence."
                ),
            )
        return LongFormPolicy(
            section_max_characters=QWEN_PRESET_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Preset and voice-design delivery setting; these paths do not "
                "use reference-audio cloning."
            ),
        )
    if family == "chatterbox-mlx":
        turbo = "turbo" in name
        return LongFormPolicy(
            section_max_characters=(
                CHATTERBOX_TURBO_SECTION_MAX_CHARACTERS
                if turbo
                else CHATTERBOX_STANDARD_SECTION_MAX_CHARACTERS
            ),
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Conservative Turbo delivery setting. The same reference voice "
                "and expression controls are reused for every section."
                if turbo
                else "Standard Chatterbox delivery setting. The same reference "
                "voice and expression controls are reused for every section."
            ),
        )
    if family == "voxcpm-mlx":
        return LongFormPolicy(
            section_max_characters=VOXCPM_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Keeps each synthesis pass inside the practical voice-fidelity "
                "window while preserving the selected clone controls."
            ),
        )
    if family == "kokoro-mlx":
        return LongFormPolicy(
            section_max_characters=KOKORO_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Voice Studio sections provide progress and cancellation; "
                "Kokoro still applies its own phoneme-safe splitting inside them."
            ),
        )
    if family == "vibevoice":
        return LongFormPolicy(
            section_max_characters=VIBEVOICE_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Keeps narration comfortably below the model's long acoustic "
                "window before final validation and joining."
            ),
        )
    if family == "omnivoice":
        return LongFormPolicy(
            section_max_characters=OMNIVOICE_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Conservative cloning setting using the same reference for every "
                "section; retained pending the remaining long-form listening gate."
            ),
        )
    if family == "fish-audio-mlx":
        return LongFormPolicy(
            section_max_characters=FISH_AUDIO_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Voice Studio owns the outer delivery boundary so clone and style "
                "controls remain identical across the final joined artifact."
            ),
        )
    if family == "arktts":
        return LongFormPolicy(
            section_max_characters=AUDIO8_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Keeps each synthesis pass safely under Audio8's ~24-second-per-call "
                "budget while preserving the selected clone or zero-shot setting."
            ),
        )
    if family == "moss-tts-nano":
        return LongFormPolicy(
            section_max_characters=MOSS_TTS_NANO_SECTION_MAX_CHARACTERS,
            join_pause_seconds=DEFAULT_JOIN_PAUSE_SECONDS,
            note=(
                "Voice Studio owns the outer delivery boundary for progress and "
                "cancellation, on top of the model's own internal sentence splitting."
            ),
        )
    return None


def policy_for(
    family: str,
    repo: str,
    *,
    audited_section_max_characters: object = None,
) -> Optional[dict]:
    """Return the effective runtime policy, including a valid audit override."""
    policy = _runtime_default(family, repo)
    if policy is None:
        return None

    source = "runtime_default"
    try:
        audited_limit = int(audited_section_max_characters)
    except (TypeError, ValueError):
        audited_limit = 0
    if 40 <= audited_limit <= 20_000:
        policy = LongFormPolicy(
            section_max_characters=audited_limit,
            join_pause_seconds=policy.join_pause_seconds,
            note=(
                "The exact model audit overrides the family default. "
                + policy.note
            ),
        )
        source = "model_audit"
    return policy.serialize(source=source)
