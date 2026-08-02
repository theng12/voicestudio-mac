"""Model-owned preparation of private voice-cloning references.

GenStudio owns the customer asset and Studio Hub owns temporary transport.
Voice Studio owns the model-specific execution copy: decoding, silence-aware
selection, format normalization, transcript alignment, and immutable evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from . import model_audits


ROOT = Path(__file__).resolve().parents[1] / "reference_cache"
PREPARATION_REVISION = "voicestudio.reference-audio.v1"
MAX_BYTES = 25_000_000
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".webm"}


class ReferenceAudioError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _profile(model_id: str) -> dict[str, Any]:
    limits = model_audits.input_limits(model_id)
    value = limits.get("reference_audio")
    return dict(value) if isinstance(value, dict) else {}


def _number(value: object, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 0 else default


def _decode(path: Path, target_rate: int):
    import numpy as np
    import soundfile as sf

    try:
        audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ReferenceAudioError(
                "REFERENCE_AUDIO_DECODE_UNAVAILABLE",
                "This reference format needs FFmpeg, but FFmpeg is not available on this Voice Studio.",
            )
        decoded = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.decoded.wav")
        try:
            process = subprocess.run(
                [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(path),
                 "-ac", "1", "-ar", str(target_rate), "-c:a", "pcm_s16le", str(decoded)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if process.returncode != 0 or not decoded.is_file():
                raise ReferenceAudioError(
                    "REFERENCE_AUDIO_DECODE_FAILED",
                    "The uploaded reference audio could not be decoded.",
                )
            audio, sample_rate = sf.read(str(decoded), dtype="float32", always_2d=True)
        finally:
            decoded.unlink(missing_ok=True)

    if audio.size == 0 or sample_rate <= 0:
        raise ReferenceAudioError("REFERENCE_AUDIO_EMPTY", "The uploaded reference contains no audio.")
    if not np.isfinite(audio).all():
        raise ReferenceAudioError("REFERENCE_AUDIO_INVALID", "The reference contains invalid audio samples.")
    mono = audio.mean(axis=1, dtype=np.float32)
    if sample_rate != target_rate:
        old = np.arange(len(mono), dtype=np.float64) / float(sample_rate)
        new_length = max(1, round(len(mono) * target_rate / float(sample_rate)))
        new = np.arange(new_length, dtype=np.float64) / float(target_rate)
        mono = np.interp(new, old, mono).astype(np.float32)
        sample_rate = target_rate
    return mono, sample_rate


def _speech_bounds(audio, sample_rate: int) -> tuple[int, int]:
    """Return silence-trimmed bounds with a short, non-destructive pad."""
    import numpy as np

    frame = max(1, round(sample_rate * 0.02))
    usable = len(audio) - (len(audio) % frame)
    if usable <= 0:
        return 0, len(audio)
    framed = audio[:usable].reshape(-1, frame)
    rms = np.sqrt(np.mean(np.square(framed), axis=1))
    peak = float(rms.max(initial=0.0))
    if peak < 0.001:
        raise ReferenceAudioError(
            "REFERENCE_AUDIO_NO_SPEECH",
            "No usable speech was detected in the uploaded reference.",
        )
    threshold = max(0.0025, peak * 0.08)
    voiced = np.flatnonzero(rms >= threshold)
    if not len(voiced):
        raise ReferenceAudioError(
            "REFERENCE_AUDIO_NO_SPEECH",
            "No usable speech was detected in the uploaded reference.",
        )
    pad = round(sample_rate * 0.15)
    return max(0, int(voiced[0]) * frame - pad), min(
        len(audio), (int(voiced[-1]) + 1) * frame + pad
    )


def _validated_segments(value: object, duration_s: float) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ReferenceAudioError(
            "REFERENCE_TRANSCRIPT_SEGMENTS_INVALID",
            "Reference transcript segments must be an ordered list.",
        )
    result = []
    previous_end = 0.0
    for raw in value:
        if not isinstance(raw, dict):
            raise ReferenceAudioError("REFERENCE_TRANSCRIPT_SEGMENTS_INVALID", "A transcript segment is invalid.")
        start = _number(raw.get("start_seconds", raw.get("start")))
        end = _number(raw.get("end_seconds", raw.get("end")))
        text = str(raw.get("text") or "").strip()
        if start is None or end is None or start < previous_end or end <= start or end > duration_s + 0.05:
            raise ReferenceAudioError(
                "REFERENCE_TRANSCRIPT_SEGMENTS_INVALID",
                "Transcript timestamps must be ordered and remain inside the reference audio.",
            )
        if text:
            result.append({"start": start, "end": end, "text": text})
        previous_end = end
    return result


def _best_segment_window(segments: list[dict[str, Any]], max_seconds: float) -> tuple[float, float, str]:
    best: tuple[float, float, str] | None = None
    best_score = -1
    for start_index, first in enumerate(segments):
        selected = []
        for segment in segments[start_index:]:
            if segment["end"] - first["start"] > max_seconds:
                break
            selected.append(segment)
        if not selected:
            continue
        text = " ".join(segment["text"] for segment in selected).strip()
        score = len(text)
        if score > best_score:
            best_score = score
            best = (first["start"], selected[-1]["end"], text)
    if best is None:
        raise ReferenceAudioError(
            "REFERENCE_AUDIO_DURATION_UNSUPPORTED",
            "No transcript-aligned reference segment fits this model's duration limit.",
        )
    return best


def _best_energy_window(audio, sample_rate: int, seconds: float) -> tuple[int, int]:
    import numpy as np

    width = min(len(audio), max(1, round(seconds * sample_rate)))
    if width >= len(audio):
        return 0, len(audio)
    step = max(1, round(sample_rate * 0.25))
    squared = np.square(audio.astype(np.float64))
    cumulative = np.concatenate(([0.0], np.cumsum(squared)))
    best_start = 0
    best_energy = -1.0
    for start in range(0, len(audio) - width + 1, step):
        energy = cumulative[start + width] - cumulative[start]
        if energy > best_energy:
            best_energy = energy
            best_start = start
    return best_start, best_start + width


def cleanup_expired(now: float | None = None) -> int:
    current = time.time() if now is None else now
    removed = 0
    if not ROOT.is_dir():
        return 0
    for child in ROOT.iterdir():
        if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
            continue
        try:
            metadata = json.loads((child / "metadata.json").read_text(encoding="utf-8"))
            expires_at = float(metadata.get("expires_at") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            expires_at = 0
        if expires_at and expires_at <= current:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def prepare(
    *, audio_bytes: bytes, filename: str, model_id: str, transcript: str = "",
    transcript_segments: object = None, expires_at: float | None = None,
) -> dict[str, Any]:
    """Create or reuse one deterministic, model-compatible execution copy."""
    import numpy as np
    import soundfile as sf

    if not audio_bytes:
        raise ReferenceAudioError("REFERENCE_AUDIO_EMPTY", "The uploaded reference is empty.")
    if len(audio_bytes) > MAX_BYTES:
        raise ReferenceAudioError("REFERENCE_AUDIO_TOO_LARGE", "Reference audio exceeds the 25 MB limit.")
    extension = Path(filename or "reference.wav").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ReferenceAudioError("REFERENCE_AUDIO_TYPE_UNSUPPORTED", "The reference audio type is unsupported.")

    profile = _profile(model_id)
    target_rate = int(_number(profile.get("sample_rate_hz"), 24000) or 24000)
    target_rate = max(8000, min(target_rate, 96000))
    source_sha = hashlib.sha256(audio_bytes).hexdigest()
    profile_hash = hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    segment_hash = hashlib.sha256(
        json.dumps(transcript_segments or [], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    key = hashlib.sha256(
        f"{PREPARATION_REVISION}\n{source_sha}\n{model_id}\n{profile_hash}\n{segment_hash}\n{transcript}".encode()
    ).hexdigest()
    target = ROOT / key
    metadata_path = target / "metadata.json"
    wav_path = target / "reference.wav"
    if metadata_path.is_file() and wav_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if expires_at and float(metadata.get("expires_at") or 0) < expires_at:
            metadata["expires_at"] = expires_at
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {**metadata, "path": str(wav_path)}

    ROOT.mkdir(parents=True, exist_ok=True)
    cleanup_expired()
    source = ROOT / f".{uuid.uuid4().hex}{extension}"
    source.write_bytes(audio_bytes)
    try:
        audio, sample_rate = _decode(source, target_rate)
    finally:
        source.unlink(missing_ok=True)
    original_duration = len(audio) / float(sample_rate)
    segments = _validated_segments(transcript_segments, original_duration)
    speech_start, speech_end = _speech_bounds(audio, sample_rate)
    audio = audio[speech_start:speech_end]
    window_start_s = speech_start / float(sample_rate)
    window_end_s = speech_end / float(sample_rate)

    maximum = _number(profile.get("maximum_duration_seconds"))
    minimum = _number(profile.get("minimum_duration_seconds"), 0.5) or 0.5
    requirement = str(profile.get("transcript") or "optional").lower()
    derived_transcript = transcript.strip()
    if maximum and len(audio) / sample_rate > maximum:
        if segments:
            start_s, end_s, derived_transcript = _best_segment_window(segments, maximum)
            start = max(0, round(start_s * sample_rate))
            end = min(len(audio) + speech_start, round(end_s * sample_rate))
            audio = _decode_array_slice(audio, start - speech_start, end - speech_start)
            window_start_s, window_end_s = start_s, end_s
        else:
            if requirement == "required" and derived_transcript:
                raise ReferenceAudioError(
                    "REFERENCE_TRANSCRIPT_ALIGNMENT_REQUIRED",
                    "This model needs a transcript matching the selected reference segment. Supply timestamped transcript segments.",
                )
            start, end = _best_energy_window(audio, sample_rate, maximum)
            audio = audio[start:end]
            window_start_s += start / float(sample_rate)
            window_end_s = window_start_s + len(audio) / float(sample_rate)
            derived_transcript = ""
    if len(audio) / sample_rate < minimum:
        raise ReferenceAudioError(
            "REFERENCE_AUDIO_TOO_SHORT",
            f"This model needs at least {minimum:g} seconds of usable speech.",
        )
    if requirement == "required" and not derived_transcript:
        raise ReferenceAudioError(
            "REFERENCE_TRANSCRIPT_REQUIRED",
            "This model requires a transcript matching the reference audio.",
        )

    rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
    peak = float(np.max(np.abs(audio), initial=0.0))
    if rms <= 1e-5 or peak <= 1e-4:
        raise ReferenceAudioError("REFERENCE_AUDIO_NO_SPEECH", "No usable speech remains after preparation.")
    gain = min(0.95 / peak, 0.1 / rms)
    audio = np.clip(audio * gain, -0.95, 0.95).astype(np.float32)

    temporary = ROOT / f".{key}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir(mode=0o700)
    try:
        output = temporary / "reference.wav"
        sf.write(str(output), audio, sample_rate, format="WAV", subtype="PCM_16")
        derived_sha = hashlib.sha256(output.read_bytes()).hexdigest()
        metadata = {
            "cache_key": key,
            "preparation_revision": PREPARATION_REVISION,
            "model_id": model_id,
            "source_sha256": source_sha,
            "derived_sha256": derived_sha,
            "duration_seconds": round(len(audio) / float(sample_rate), 3),
            "source_duration_seconds": round(original_duration, 3),
            "sample_rate_hz": sample_rate,
            "channels": 1,
            "window_start_seconds": round(window_start_s, 3),
            "window_end_seconds": round(window_end_s, 3),
            "transcript": derived_transcript,
            "profile": profile,
            "expires_at": expires_at,
            "created_at": time.time(),
        }
        (temporary / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            os.replace(temporary, target)
        except OSError:
            if not target.is_dir():
                raise
        return {**metadata, "path": str(wav_path)}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _decode_array_slice(audio, start: int, end: int):
    start = max(0, start)
    end = min(len(audio), end)
    return audio[start:end]
