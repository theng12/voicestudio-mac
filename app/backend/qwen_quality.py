"""Model-owned safety checks for Qwen3-TTS Base voice cloning.

Qwen Base can occasionally fail to emit EOS and fill its entire acoustic-token
budget with repeated or unrelated speech.  These helpers keep that failure
inside Voice Studio: references are aligned before inference, every section
gets a bounded acoustic-token budget, and generated speech is accepted only
after Whisper Large agrees that it matches the requested text.

No customer transcript or filesystem path is stored in quality evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


VALIDATOR_REVISION = "voicestudio.qwen-clone-quality.v1"
WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"
RETRY_SECTION_MAX_CHARACTERS = 230
RETRYABLE_OUTPUT_CODES = frozenset({
    "QWEN_OUTPUT_DURATION_EXCEEDED",
    "QWEN_OUTPUT_TEXT_MISMATCH",
    "QWEN_OUTPUT_REPETITION_DETECTED",
})
_CACHE_DIR = Path(__file__).resolve().parent.parent / "reference_cache" / "qwen_quality"


@dataclass
class QwenQualityError(RuntimeError):
    code: str
    detail: str
    evidence: dict

    def __str__(self) -> str:
        return self.detail


def is_qwen_base_clone(repo: str, params: dict | None = None) -> bool:
    normalized = (repo or "").strip().lower()
    if "qwen3-tts" not in normalized or "base" not in normalized:
        return False
    if params is None:
        return True
    return bool(
        params.get("voice_library_id")
        or params.get("_reference_audio_path")
    )


def reference_cache_key(audio_path: str | Path, transcript: str) -> str:
    digest = hashlib.sha256()
    with Path(audio_path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    digest.update(b"\0")
    digest.update(transcript.encode("utf-8"))
    digest.update(b"\0")
    digest.update(VALIDATOR_REVISION.encode("ascii"))
    return digest.hexdigest()


def cached_reference_evidence(cache_key: str) -> dict | None:
    path = _CACHE_DIR / f"{cache_key}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        value.get("validator_revision") != VALIDATOR_REVISION
        or value.get("accepted") is not True
    ):
        return None
    return value


def save_reference_evidence(cache_key: str, evidence: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = _CACHE_DIR / f"{cache_key}.json"
    temporary = _CACHE_DIR / f".{cache_key}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _tokens(value: str) -> list[str]:
    normalized = _normalized_text(value)
    words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized)
    cjk = re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", normalized)
    return words + cjk


def _distance(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, item in enumerate(left, start=1):
        current = [row]
        for column, other in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (item != other),
            ))
        previous = current
    return previous[-1]


def _error_rate(expected: list[str], observed: list[str], *, ngram_size: int) -> tuple[float, str]:
    """Exact edit distance for short clips; bounded linear evidence for long form."""
    if max(len(expected), len(observed)) <= 2_048:
        return _distance(expected, observed) / max(1, len(expected)), "edit-distance"
    width = min(ngram_size, max(1, len(expected)))
    expected_ngrams = Counter(
        tuple(expected[index:index + width])
        for index in range(max(1, len(expected) - width + 1))
    )
    observed_ngrams = Counter(
        tuple(observed[index:index + width])
        for index in range(max(1, len(observed) - width + 1))
    )
    overlap = sum((expected_ngrams & observed_ngrams).values())
    missing_rate = 1.0 - overlap / max(1, sum(expected_ngrams.values()))
    length_penalty = max(0, len(observed) - len(expected)) / max(1, len(expected))
    return min(2.0, missing_rate + length_penalty), f"{width}-gram-multiset"


def _similarity(expected: str, observed: str) -> dict:
    expected_tokens = _tokens(expected)
    observed_tokens = _tokens(observed)
    expected_chars = list(_normalized_text(expected).replace(" ", ""))
    observed_chars = list(_normalized_text(observed).replace(" ", ""))
    token_error, token_method = _error_rate(expected_tokens, observed_tokens, ngram_size=2)
    character_error, character_method = _error_rate(expected_chars, observed_chars, ngram_size=4)
    return {
        "token_error_rate": round(token_error, 4),
        "character_error_rate": round(character_error, 4),
        "comparison_method": {
            "tokens": token_method,
            "characters": character_method,
        },
        "expected_tokens": len(expected_tokens),
        "observed_tokens": len(observed_tokens),
    }


def _word_timestamp_count(result: dict) -> int:
    return sum(
        len(segment.get("words") or [])
        for segment in (result.get("segments") or [])
    )


def _evidence(kind: str, expected: str, observed: str, result: dict) -> dict:
    metrics = _similarity(expected, observed)
    return {
        "validator_revision": VALIDATOR_REVISION,
        "kind": kind,
        "whisper_model": result.get("model") or WHISPER_REPO,
        "expected_sha256": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        "observed_sha256": hashlib.sha256(observed.encode("utf-8")).hexdigest(),
        "duration_seconds": round(float(result.get("duration") or 0.0), 3),
        "word_timestamp_count": _word_timestamp_count(result),
        **metrics,
    }


def validate_reference(expected: str, result: dict) -> dict:
    observed = str(result.get("text") or "").strip()
    evidence = _evidence("reference", expected, observed, result)
    if not expected.strip():
        raise QwenQualityError(
            "QWEN_REFERENCE_TRANSCRIPT_REQUIRED",
            "Qwen3-TTS Base needs the exact transcript for its reference audio.",
            evidence,
        )
    if evidence["word_timestamp_count"] <= 0:
        raise QwenQualityError(
            "QWEN_REFERENCE_ALIGNMENT_UNAVAILABLE",
            "Whisper Large could not produce word-aligned reference evidence.",
            evidence,
        )
    if not observed or (
        evidence["token_error_rate"] > 0.35
        and evidence["character_error_rate"] > 0.22
    ):
        raise QwenQualityError(
            "QWEN_REFERENCE_TRANSCRIPT_MISMATCH",
            "The supplied reference transcript does not match the selected speech closely enough.",
            evidence,
        )
    evidence["accepted"] = True
    return evidence


def automatic_duration_limit(text: str, speed: float = 1.0) -> float:
    """Return a generous final-audio ceiling while preventing 96 s EOS failures.

    The estimate intentionally favors false acceptance: normal narration can be
    much slower than average and still pass.  A 250-300 character English
    section receives roughly 35-50 seconds, safely above healthy Qwen output
    while remaining far below its 96-second 1,200-token exhaustion point.
    """
    normalized = _normalized_text(text)
    latin_words = len(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized))
    cjk_chars = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", normalized))
    nonspace_chars = len(normalized.replace(" ", ""))
    natural_seconds = max(
        latin_words / 1.65,
        cjk_chars / 3.2,
        nonspace_chars / 10.0,
        1.0,
    )
    safe_speed = max(0.5, min(float(speed or 1.0), 2.0))
    return round(min(70.0, max(8.0, natural_seconds * 1.65 + 4.0)) / safe_speed, 3)


def max_tokens_for_text(text: str, speed: float = 1.0) -> int:
    native_seconds = automatic_duration_limit(text, speed) * max(0.5, min(speed, 2.0))
    return max(1, min(1199, math.floor(native_seconds * 12.5)))


def validate_output(expected: str, result: dict, *, max_duration_s: float) -> dict:
    observed = str(result.get("text") or "").strip()
    evidence = _evidence("output", expected, observed, result)
    evidence["max_duration_seconds"] = round(float(max_duration_s), 3)
    duration = float(result.get("duration") or 0.0)
    if duration > max_duration_s + 0.05:
        raise QwenQualityError(
            "QWEN_OUTPUT_DURATION_EXCEEDED",
            "Qwen3-TTS produced an implausibly long result and it was rejected.",
            evidence,
        )
    if not observed or (
        evidence["token_error_rate"] > 0.40
        and evidence["character_error_rate"] > 0.25
    ):
        raise QwenQualityError(
            "QWEN_OUTPUT_TEXT_MISMATCH",
            "Whisper validation found missing, repeated, or unrelated generated speech.",
            evidence,
        )
    if evidence["observed_tokens"] > max(12, evidence["expected_tokens"] * 1.65):
        raise QwenQualityError(
            "QWEN_OUTPUT_REPETITION_DETECTED",
            "Whisper validation found excessive repeated generated speech.",
            evidence,
        )
    evidence["accepted"] = True
    return evidence
