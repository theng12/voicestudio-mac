"""
Speech-to-text / subtitle generation through mlx-audio.

This is the STT counterpart to generation.py's TTS workers. The primary
consumer is a remote app (Story Studio) that generates narration audio via
our TTS endpoints, then wants timestamped subtitles (SRT/VTT) for it.

WHY THIS LIVES IN VOICE STUDIO (not a separate app):
- `mlx-audio` (already a dependency for the MLX TTS engines) ships a complete
  STT subsystem with Whisper and other local ASR model families.
  Adding subtitles is wiring, not a new install.
- Same machine, same FastAPI server, same Tailscale endpoint, same HF cache,
  same download manager, same diagnostics. One thing to keep alive.
- TTS audio is pristine (no noise, clean articulation) → Whisper transcription
  of our own output is near-perfect, so re-transcription "just works".

STANDARDS THIS FOLLOWS (see generation.py's module docstring):
- Explicit-path model loading (v1.3.5): pass the local snapshot Path, never a
  repo ID, so we're immune to cache-layout drift between huggingface_hub and
  other backends.
- Shared `_GEN_LOCK` (from generation.py): STT and TTS never run concurrently,
  so two MLX models can't both spike Metal memory and OOM the server.
- MLX cache release on model switch (v1.2.7): `_release_device_memory`.
- No silent downloads: if the requested transcription model isn't cached, raise a
  clean error pointing at the Models tab / /api/downloads — never trigger an
  out-of-band download mid-request.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import cache, media_tools, resource_telemetry
# Reuse the TTS side's device detection, MLX cache release, and the GLOBAL
# generation lock. Sharing the lock is the key safety property: a transcription
# can't start while a TTS job holds the GPU, and vice versa. No circular import
# risk — generation.py does not import this module.
from .generation import (
    _GEN_LOCK,
    _detect_device,
    _is_memory_failure,
    _release_device_memory,
    manager as generation_manager,
)
from .model_audits import candidate_summary


# ───────────── Transcription model registry ─────────────
# All repos verified live on huggingface.co. Sizes are approximate on-disk
# (post-download). `recommended` marks the default the API uses when no model
# is specified. Adding a new ASR model is a one-line append here — the download
# flow (generic /api/downloads) and the worker below need no other changes.

@dataclass(frozen=True)
class TranscriptionModel:
    repo: str
    label: str
    size_gb: float
    note: str
    engine: str = "whisper"
    min_unified_memory_gb: int = 8
    languages: str = "Multilingual"
    supports_segment_timestamps: bool = True
    supports_word_timestamps: bool = True
    supports_long_form: bool = True
    internal_candidate: bool = False
    recommended: bool = False


TRANSCRIPTION_MODELS: tuple[TranscriptionModel, ...] = (
    TranscriptionModel(
        repo="mlx-community/whisper-large-v3-turbo",
        label="Whisper large-v3 turbo",
        size_gb=1.6,
        note="Recommended. Near-large accuracy at ~8× the speed. Best default for subtitles.",
        recommended=True,
    ),
    TranscriptionModel(
        repo="mlx-community/whisper-large-v3-turbo-q4",
        label="Whisper large-v3 turbo (4-bit)",
        size_gb=0.5,
        note="Quantized turbo — turbo accuracy at a third of the disk/memory. Great on 8 GB Macs.",
    ),
    TranscriptionModel(
        repo="mlx-community/whisper-large-v3-mlx",
        label="Whisper large-v3 (full)",
        size_gb=3.1,
        note="Highest accuracy, slowest. Use for final renders or noisy/accented audio.",
    ),
    TranscriptionModel(
        repo="mlx-community/whisper-small-mlx",
        label="Whisper small",
        size_gb=0.5,
        note="Fast, decent accuracy. Fine for clean TTS audio in English.",
    ),
    TranscriptionModel(
        repo="mlx-community/whisper-base-mlx",
        label="Whisper base",
        size_gb=0.15,
        note="Very fast, lower accuracy. Quick drafts / very clean audio.",
    ),
    TranscriptionModel(
        repo="moonshine-ai/moonshine-base",
        label="Moonshine Base",
        size_gb=0.25,
        note="Internal pilot. Lightweight English short-form transcription for 8 GB Macs.",
        engine="moonshine",
        languages="English",
        supports_segment_timestamps=False,
        supports_word_timestamps=False,
        supports_long_form=False,
        internal_candidate=True,
    ),
    TranscriptionModel(
        repo="mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit",
        label="Nemotron 3.5 ASR Streaming 0.6B (8-bit)",
        size_gb=0.76,
        note="Internal pilot. Multilingual chunked transcription candidate for 8 GB Macs.",
        engine="nemotron",
        languages="Multilingual",
        internal_candidate=True,
    ),
)

WHISPER_MODELS = tuple(
    model for model in TRANSCRIPTION_MODELS if model.engine == "whisper"
)
_BY_REPO = {m.repo: m for m in TRANSCRIPTION_MODELS}


def model_for_repo(repo: str) -> TranscriptionModel:
    return _BY_REPO[repo]

# The mlx-community whisper repos ship ONLY config.json + weights — no HF
# processor files (preprocessor_config.json, tokenizer, vocab). mlx-audio's
# whisper post-load hook does `WhisperProcessor.from_pretrained(<local snapshot>)`,
# which therefore fails → model._processor = None → at transcribe time you get
# "Processor not found. Make sure the model was loaded with a HuggingFace
# processor." This affects all five repos (turbo, turbo-q4, large-v3, small,
# and base) equally — it is NOT specific to the quantized one.
#
# Fix (v1.4.3): mlx-audio computes the mel spectrogram itself from the model's
# own config (`log_mel_spectrogram(audio, n_mels=self.dims.n_mels)`) and uses
# the processor ONLY for its tokenizer. So we attach a tokenizer-providing
# WhisperProcessor from the model's base OpenAI repo (these DO ship the
# processor). It's a ~2 MB one-time fetch, cached in HF_HOME thereafter.
_PROCESSOR_BASE = {
    "mlx-community/whisper-large-v3-turbo":    "openai/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-turbo-q4": "openai/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-mlx":      "openai/whisper-large-v3",
    "mlx-community/whisper-small-mlx":         "openai/whisper-small",
    "mlx-community/whisper-base-mlx":          "openai/whisper-base",
}


# Whisper decodes 30-second windows. By default (`condition_on_previous_text=True`)
# it feeds its own previous output back in as the prompt for the next window. That
# is helpful on clean speech, but it makes hallucination self-reinforcing: one bad
# token becomes the context that makes the next bad token likelier, and the decoder
# runs away into a block of invented text — most visibly foreign-script text, since
# the language token conditions only the START of decoding and never restricts the
# vocabulary. (Real observed output: "马 West outside The gust,".)
#
# Measured on 19 chapters of the owner's own narration spanning sleep stories,
# narrative history and spoken explainers, scored against the ground-truth scripts
# the voice actually read (v2.3.1):
#
#     conditioning ON  (old)   recall 98.64%   758 invented words   434s
#     conditioning OFF (this)  recall 98.55%    46 invented words   235s
#
# 94% fewer invented words, ~1.8x faster (no temperature-fallback retries on
# garbage it emits anyway), and the 7-word recall difference across ~7,700 words
# is entirely word-boundary and homophone variance ("adrift"/"a drift",
# "stair"/"stare") plus one dropped article — no coherent speech is lost.
#
# This is deliberately NOT a per-request option. Voice Studio is English-only by
# product decision, transcripts feed downstream image-prompt generation where an
# invented sentence produces a wrong image, and no caller has ever wanted the
# hallucination cascade back. A flag here would only be a way to turn the bug on.
#
# NOTE for anyone tempted to also add `suppress_tokens` for non-Latin scripts:
# that was measured too, and it is worse. Masking the CJK/Cyrillic/Hebrew logits
# does not stop the runaway — it launders it, so the decoder emits the same length
# of invented text in fluent English instead (758 -> 957 invented words when used
# on its own). Removing the cascade is the fix; hiding its alphabet is not.
_CONDITION_ON_PREVIOUS_TEXT = False


class _TokenizerOnlyProcessor:
    """Minimal stand-in exposing only `.tokenizer` — the single attribute
    mlx-audio's whisper `get_tokenizer()` reads off `model._processor`. Lets us
    satisfy the processor requirement with a *narrow* `WhisperTokenizer` import
    instead of the full `WhisperProcessor` import chain, which on a drifted env
    can explode on an unrelated broken symbol (e.g. `ImportError: cannot import
    name 'ReasoningEffort' from 'transformers'` when transformers / mlx-audio
    versions are mismatched). Verified to produce identical transcription."""
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer


def recommended_model() -> str:
    for m in TRANSCRIPTION_MODELS:
        if m.recommended:
            return m.repo
    return WHISPER_MODELS[0].repo


# ───────────── availability ─────────────

def _have_mlx_audio_stt() -> bool:
    try:
        from mlx_audio.stt.utils import load_model  # noqa: F401
        return True
    except Exception:
        return False


def availability() -> dict:
    """What the frontend / a remote consumer needs to know before transcribing:
    is the STT stack importable, what device, and which transcription models are
    cached + ready right now."""
    stt_ok = _have_mlx_audio_stt()
    worker_busy = generation_manager.has_active_jobs() or manager.is_active()
    models = []
    for m in TRANSCRIPTION_MODELS:
        cache_snapshot = cache.status_snapshot(m.repo)
        candidate = candidate_summary(m.repo)
        runtime_match = bool(
            candidate
            and cache_snapshot.get("snapshot_revision")
            == candidate.get("runtime_revision")
        )
        if candidate:
            candidate["capacity"] = {
                **candidate.get("capacity", {}),
                "available_slots": int(
                    stt_ok
                    and cache_snapshot.get("state") == "cached"
                    and not worker_busy
                ),
            }
        models.append({
            "repo": m.repo,
            "label": m.label,
            "size_gb": m.size_gb,
            "note": m.note,
            "engine": m.engine,
            "min_unified_memory_gb": m.min_unified_memory_gb,
            "languages": m.languages,
            "supports_segment_timestamps": m.supports_segment_timestamps,
            "supports_word_timestamps": m.supports_word_timestamps,
            "supports_long_form": m.supports_long_form,
            "internal_candidate": m.internal_candidate,
            "recommended": m.recommended,
            "cached": cache_snapshot.get("state") == "cached",
            "cache": cache_snapshot,
            **({"genstudio_candidate": candidate} if candidate else {}),
            **(
                {"genstudio_candidate_runtime_match": runtime_match}
                if candidate
                else {}
            ),
        })
    return {
        "available": stt_ok,
        "mlx_audio": stt_ok,
        "device": _detect_device() if stt_ok else None,
        "default_model": recommended_model(),
        "models": models,
        "media": media_tools.availability(),
    }


# ───────────── subtitle formatters ─────────────

def _fmt_ts(seconds: float, *, sep: str) -> str:
    """Format seconds → 'HH:MM:SS<sep>mmm'. sep is ',' for SRT, '.' for VTT."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    """SubRip (.srt). 1-indexed cues, comma millisecond separator."""
    lines: list[str] = []
    idx = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = _fmt_ts(seg.get("start", 0.0), sep=",")
        end = _fmt_ts(seg.get("end", 0.0), sep=",")
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")          # blank line between cues
        idx += 1
    return "\n".join(lines).strip() + ("\n" if lines else "")


def segments_to_vtt(segments: list[dict]) -> str:
    """WebVTT (.vtt). Required header, dot millisecond separator."""
    lines: list[str] = ["WEBVTT", ""]
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = _fmt_ts(seg.get("start", 0.0), sep=".")
        end = _fmt_ts(seg.get("end", 0.0), sep=".")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _audio_duration_seconds(path: Path) -> Optional[float]:
    """Probe true media duration without decoding the whole upload twice."""
    ffprobe = media_tools.find_executable("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    str(ffprobe),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            duration = float(json.loads(result.stdout)["format"]["duration"])
            if duration > 0:
                return duration
        except (OSError, ValueError, KeyError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    try:
        import soundfile as sf

        info = sf.info(str(path))
        if info.frames > 0 and info.samplerate > 0:
            return info.frames / info.samplerate
    except Exception:
        return None
    return None


def _normalize_segments(
    raw_segments: list[dict],
    *,
    word_timestamps: bool,
    audio_duration: Optional[float],
) -> tuple[str, list[dict]]:
    """Normalize MLX Whisper output and discard padded-silence hallucinations.

    Whisper analyzes 30-second windows.  The tiny checkpoint can emit tokens
    in the zero padding after a short clip, producing impossible timestamps and
    junk suffix text.  The media duration is the hard boundary: retain the
    final real segment, clamp it to the file, and never publish text that begins
    at or after the source audio ended.
    """
    segments: list[dict] = []
    for seg in raw_segments or []:
        start = max(0.0, float(seg.get("start", 0.0)))
        end = max(start, float(seg.get("end", start)))
        if audio_duration is not None:
            if start >= audio_duration:
                continue
            end = min(end, audio_duration)
        entry = {
            "id": len(segments),
            "start": start,
            "end": end,
            "text": (seg.get("text") or "").strip(),
        }
        if word_timestamps and seg.get("words"):
            words = []
            for word in seg["words"]:
                try:
                    raw_word_start = float(word["start"])
                    raw_word_end = float(word["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    not math.isfinite(raw_word_start)
                    or not math.isfinite(raw_word_end)
                    or raw_word_end < raw_word_start
                ):
                    continue
                word_start = max(start, raw_word_start)
                word_end = max(word_start, raw_word_end)
                if audio_duration is not None:
                    if word_start >= audio_duration:
                        continue
                    word_end = min(word_end, audio_duration)
                words.append({
                    "word": (word.get("word") or "").strip(),
                    "start": word_start,
                    "end": word_end,
                })
            if words:
                entry["words"] = words
        if entry["end"] > entry["start"] and (entry["text"] or entry.get("words")):
            segments.append(entry)
    return " ".join(seg["text"] for seg in segments if seg["text"]).strip(), segments


def _result_field(value, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _segments_from_nemotron(result, *, word_timestamps: bool) -> list[dict]:
    """Convert mlx-audio's AlignedResult into the existing subtitle shape."""
    segments: list[dict] = []
    for sentence in _result_field(result, "sentences", []) or []:
        entry = {
            "start": _result_field(sentence, "start", 0.0),
            "end": _result_field(sentence, "end", 0.0),
            "text": _result_field(sentence, "text", ""),
        }
        if word_timestamps:
            entry["words"] = [
                {
                    "word": _result_field(token, "text", ""),
                    "start": _result_field(token, "start", 0.0),
                    "end": _result_field(token, "end", 0.0),
                }
                for token in (_result_field(sentence, "tokens", []) or [])
            ]
        segments.append(entry)
    return segments


# ───────────── transcription manager ─────────────

@dataclass
class TranscriptionActivityJob:
    job_id: str
    model: str
    state: str = "queued"
    params: dict = field(default_factory=dict)
    origin: str = "unknown"
    origin_device: Optional[str] = None
    progress: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    output_path: Optional[str] = None
    mode: str = field(default="transcription", init=False)


def _activity_origin(value: object) -> str:
    return value if value in {"hub", "local_ui", "api", "unknown"} else "unknown"


def _activity_device(value: object) -> str | None:
    text = str(value or "").strip()
    return text[:160] or None


def _activity_error_code(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "INPUT_NOT_FOUND"
    if isinstance(exc, ValueError):
        return "INVALID_TRANSCRIPTION_REQUEST"
    if isinstance(exc, RuntimeError):
        return "TRANSCRIPTION_UNAVAILABLE"
    return "TRANSCRIPTION_FAILED"


@dataclass
class TranscriptionManager:
    _model: object = field(default=None, repr=False)
    _model_repo: Optional[str] = None
    _active: bool = field(default=False, repr=False)
    _last_model_activity_at: Optional[float] = field(default=None, repr=False)
    _activity_jobs: dict[str, TranscriptionActivityJob] = field(
        default_factory=dict, repr=False,
    )
    _activity_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False,
    )

    def is_active(self) -> bool:
        return self._active

    def loaded_model_key(self) -> Optional[tuple[str, str]]:
        if self._model is not None and self._model_repo:
            return (self._model_repo, "transcription-stt")
        return None

    def has_loaded_model(self) -> bool:
        """Is a transcription model resident right now? Same definition memory_policy
        releases against — a bare `self._model is not None` disagrees with it
        whenever the repo is unset, and telemetry must not carry its own idea
        of what "loaded" means (see GenerationManager.has_loaded_model)."""
        return self.loaded_model_key() is not None

    def last_activity_at(self) -> Optional[float]:
        return self._last_model_activity_at

    def _start_activity(
        self, activity_id: str | None, model: str, *, origin: str,
        origin_device: str | None, language: str | None = None,
        word_timestamps: bool = False, input_filename: str | None = None,
    ) -> TranscriptionActivityJob:
        job_id = str(activity_id or f"stt-{uuid.uuid4().hex[:12]}").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", job_id):
            raise ValueError("activity_id must contain 1-160 safe characters")
        params = {
            "repo": model,
            "language": str(language or "").strip() or None,
            "word_timestamps": bool(word_timestamps),
            "input_filename": str(input_filename or "").strip()[:240] or None,
        }
        job = TranscriptionActivityJob(
            job_id=job_id, model=model, params=params,
            origin=_activity_origin(origin),
            origin_device=_activity_device(origin_device),
        )
        with self._activity_lock:
            self._activity_jobs[job_id] = job
            if len(self._activity_jobs) > 100:
                terminal = sorted(
                    (item for item in self._activity_jobs.values()
                     if item.state in {"done", "error", "cancelled"}),
                    key=lambda item: item.finished_at or item.created_at,
                )
                for item in terminal[:len(self._activity_jobs) - 100]:
                    self._activity_jobs.pop(item.job_id, None)
        return job

    def _mark_activity_running(self, job: TranscriptionActivityJob) -> None:
        with self._activity_lock:
            job.state = "running"
            job.started_at = time.time()

    def _finish_activity(
        self, job: TranscriptionActivityJob, *, result: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        with self._activity_lock:
            job.finished_at = time.time()
            if error is not None:
                job.state = "error"
                job.params["error_code"] = _activity_error_code(error)
                return
            job.state = "done"
            job.progress = 1.0
            if isinstance(result, dict):
                job.params["text"] = str(result.get("text") or "")
                job.params["language"] = str(result.get("language") or "").strip() or None

    def transcribe_job(
        self, audio_path: str, *, model_repo: Optional[str] = None,
        language: Optional[str] = None, word_timestamps: bool = False,
        activity_id: str | None = None, origin: str = "unknown",
        origin_device: str | None = None, input_filename: str | None = None,
    ) -> dict:
        """Run one user-requested subtitle job with bounded activity evidence."""
        repo = (model_repo or "").strip() or recommended_model()
        job = self._start_activity(
            activity_id, repo, origin=origin, origin_device=origin_device,
            language=language, word_timestamps=word_timestamps,
            input_filename=input_filename,
        )
        try:
            with _GEN_LOCK:
                self._mark_activity_running(job)
                result = self.transcribe(
                    audio_path, model_repo=repo, language=language,
                    word_timestamps=word_timestamps,
                    _lock_already_held=True,
                )
        except Exception as exc:
            self._finish_activity(job, error=exc)
            raise
        self._finish_activity(job, result=result)
        return {**result, "task_id": job.job_id}

    def get_activity(self, job_id: str) -> TranscriptionActivityJob | None:
        with self._activity_lock:
            return self._activity_jobs.get(job_id)

    @staticmethod
    def _activity_projection(
        job: TranscriptionActivityJob, *, observed_at: float,
    ) -> dict:
        result = {
            "id": job.job_id,
            "state": job.state,
            "model": job.model,
            "operation": "transcription",
            "progress": job.progress,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "source": "direct",
            "origin": _activity_origin(job.origin),
            **({"origin_device": _activity_device(job.origin_device)}
               if _activity_device(job.origin_device) else {}),
        }
        if job.state in {"queued", "running"}:
            result["updated_at"] = observed_at
        else:
            result["finished_at"] = job.finished_at
            result["runtime_s"] = (
                max(0.0, job.finished_at - job.started_at)
                if job.started_at is not None and job.finished_at is not None
                else None
            )
            result["error"] = "Transcription failed" if job.state == "error" else None
            result["error_code"] = job.params.get("error_code")
        return result

    def activity_snapshot(self, observed_at: float | None = None) -> dict:
        observed = float(time.time() if observed_at is None else observed_at)
        with self._activity_lock:
            jobs = list(self._activity_jobs.values())
        running = [job for job in jobs if job.state == "running"]
        queued = [job for job in jobs if job.state == "queued"]
        terminal = [job for job in jobs if job.state in {"done", "error", "cancelled"}]
        active = max(running, key=lambda job: job.created_at, default=None)
        if active is None:
            active = max(queued, key=lambda job: job.created_at, default=None)
        latest = max(
            terminal,
            key=lambda job: (job.finished_at or job.created_at, job.created_at),
            default=None,
        )
        return {
            "schema": "kh-studio.activity.v1", "studio": "voice",
            "observed_at": observed,
            "active": self._activity_projection(active, observed_at=observed) if active else None,
            "latest": self._activity_projection(latest, observed_at=observed) if latest else None,
        }

    def _evict_loaded_model(self, reason: str) -> dict:
        key = self.loaded_model_key()
        actions: list[str] = []
        if self._model is not None:
            self._model = None
            actions.append("cleared transcription model")
        self._model_repo = None
        _release_device_memory("mps")
        actions.append("cleared transcription MLX and Metal allocator caches")
        return {
            "released": key is not None,
            "models": [list(key)] if key else [],
            "actions": actions,
            "reason": reason,
        }

    def release_memory_locked(self, reason: str = "manual") -> dict:
        if self._active:
            raise RuntimeError("transcription is running")
        return self._evict_loaded_model(reason)

    def _snapshot_path(self, repo: str) -> Path:
        """Resolve the on-disk snapshot dir for a cached repo. Mirrors
        generation.py's `_mlx_audio_snapshot_path` — returns a Path so the
        loader's name-hint walking finds `models--<org>--<repo>` (the v1.2.8
        str-vs-Path lesson)."""
        repo_dir = cache.repo_cache_dir(repo)
        snapshots = repo_dir / "snapshots"
        if not snapshots.exists():
            raise RuntimeError(
                f"Transcription model {repo} is not downloaded. "
                "Download it first (Models tab, or POST /api/downloads)."
            )
        candidates = [s for s in snapshots.iterdir()
                      if s.is_dir() and not s.name.startswith(".")]
        if not candidates:
            raise RuntimeError(f"No snapshot subfolder under {snapshots} for {repo}.")
        return candidates[0]

    def _get_model(self, repo: str):
        """Lazy-load + cache one transcription model. Evicts on repo switch so
        two ASR models (or an ASR + a TTS model) don't co-reside in unified
        memory. Explicit-path standard: pass the snapshot Path, not the repo."""
        if self._model_repo == repo and self._model is not None:
            return self._model

        if self._model is not None:
            print(f"[stt] evicting cached transcription model ({self._model_repo})", flush=True)
            try:
                del self._model
            except Exception:
                pass
            self._model = None
            self._model_repo = None
            _release_device_memory("mps")

        from mlx_audio.stt.utils import load_model
        snapshot_path = self._snapshot_path(repo)
        print(f"[stt] loading transcription model from {snapshot_path}", flush=True)
        model = load_model(snapshot_path)          # Path object — see v1.2.8

        # The mlx-community repos don't bundle the HF processor, so load_model's
        # post-hook leaves model._processor = None → "Processor not found" at
        # transcribe time. Attach a tokenizer from the matching base OpenAI repo.
        if (
            model_for_repo(repo).engine == "whisper"
            and getattr(model, "_processor", None) is None
        ):
            self._attach_processor(model, repo)

        self._model = model
        self._model_repo = repo
        self._last_model_activity_at = time.time()
        return model

    def _attach_processor(self, model, repo: str) -> None:
        """Give a weights-only MLX whisper model a working tokenizer, sourced
        from its base OpenAI repo (~2 MB, cached in HF_HOME).

        Tries the NARROW `WhisperTokenizer` import first. The full
        `WhisperProcessor.from_pretrained` drags in much more of transformers'
        lazy-import machinery, which on a version-drifted environment can raise
        an unrelated `ImportError` (famously `cannot import name 'ReasoningEffort'
        from 'transformers'` when transformers / mlx-audio versions are
        mismatched). The tokenizer-only path dodges most of that and is all
        mlx-audio actually needs. Falls back to the full processor, then to a
        clear, actionable error that distinguishes a dependency mismatch from a
        network failure."""
        base = _PROCESSOR_BASE.get(repo, "openai/whisper-large-v3-turbo")
        print(f"[stt] {repo} ships no processor — attaching tokenizer from {base}", flush=True)
        attempts: list[str] = []

        # 1) Narrow: WhisperTokenizer only (what get_tokenizer() reads).
        try:
            from transformers import WhisperTokenizer
            tok = WhisperTokenizer.from_pretrained(base)
            model._processor = _TokenizerOnlyProcessor(tok)
            return
        except Exception as e:
            attempts.append(f"WhisperTokenizer → {type(e).__name__}: {e}")

        # 2) Fallback: full WhisperProcessor.
        try:
            from transformers import WhisperProcessor
            model._processor = WhisperProcessor.from_pretrained(base)
            return
        except Exception as e:
            attempts.append(f"WhisperProcessor → {type(e).__name__}: {e}")

        joined = " | ".join(attempts)
        # A "cannot import name" / ImportError means deps drifted, NOT a network
        # problem — point the user at the pinned reinstall instead of a raw trace.
        if "ImportError" in joined or "cannot import name" in joined:
            raise RuntimeError(
                "Whisper transcription is blocked by a Python dependency mismatch "
                "in this server's environment — the tokenizer import from "
                f"{base} failed ({joined}). This happens when transformers / "
                "mlx-audio drift to incompatible versions across machines. "
                "FIX: re-run 'Install Generation' from the Pinokio sidebar (it now "
                "pins a known-good set), then Stop → Start. Manual equivalent: "
                "uv pip install 'transformers==5.9.0' 'tokenizers==0.22.2'."
            )
        raise RuntimeError(
            f"Whisper model {repo} ships no HF processor and the fallback from "
            f"{base} couldn't be loaded ({joined}). If the modal is offline, the "
            "one-time ~2 MB processor fetch can't complete — check network and retry."
        )

    def transcribe(
        self,
        audio_path: str,
        *,
        model_repo: Optional[str] = None,
        language: Optional[str] = None,
        word_timestamps: bool = False,
        _lock_already_held: bool = False,
    ) -> dict:
        """Transcribe an audio file → text + timestamped segments + SRT + VTT.

        Serialized against the global generation lock so an in-flight TTS job
        and a transcription never both hold the GPU (Metal OOM guard).
        """
        repo = (model_repo or "").strip() or recommended_model()
        if repo not in _BY_REPO:
            raise ValueError(
                f"Unknown transcription model {repo!r}. "
                f"Known: {sorted(_BY_REPO)}"
            )
        spec = model_for_repo(repo)
        if word_timestamps and not spec.supports_word_timestamps:
            raise ValueError(f"{spec.label} does not support word timestamps")
        if cache.cache_state(repo) != "cached":
            raise RuntimeError(
                f"Transcription model {repo} is not fully cached. "
                "Download it first (Models tab, or POST /api/downloads with this repo)."
            )

        p = Path(audio_path)
        if not p.exists():
            raise FileNotFoundError(f"audio file not found: {audio_path}")
        audio_duration = _audio_duration_seconds(p)

        started = time.time()
        telemetry: Optional[resource_telemetry.JobResourceSampler] = None
        telemetry_result: Optional[dict] = None
        telemetry_state = "failed"
        memory_failure = False

        def publish_resource_evidence(payload: dict) -> None:
            nonlocal telemetry_result
            telemetry_result = payload

        if _lock_already_held and not _GEN_LOCK.locked():
            raise RuntimeError("transcribe_locked requires the generation lock")
        lock_context = nullcontext() if _lock_already_held else _GEN_LOCK

        # Hold the SAME lock TTS generation uses — one GPU job at a time. The
        # Qwen output validator is already inside that lock and uses the
        # explicit locked entry point below to avoid a non-reentrant deadlock.
        with lock_context:
            self._active = True
            self._last_model_activity_at = time.time()
            try:
                telemetry = resource_telemetry.JobResourceSampler(
                    publish_resource_evidence
                ).start()
                model = self._get_model(repo)
                lang = (language or "").strip() or None
                print(
                    f"[stt] transcribing {p.name} with {repo} "
                    f"(lang={lang or 'auto'}, word_ts={word_timestamps})",
                    flush=True,
                )
                if spec.engine == "whisper":
                    result = model.generate(
                        str(p),
                        language=lang,
                        word_timestamps=word_timestamps,
                        return_timestamps=True,
                        # See _CONDITION_ON_PREVIOUS_TEXT above: kills the
                        # hallucination cascade. Not caller-configurable.
                        condition_on_previous_text=_CONDITION_ON_PREVIOUS_TEXT,
                    )
                elif spec.engine == "moonshine":
                    result = model.generate(str(p))
                else:
                    result = model.generate(
                        str(p), language=lang or "auto", chunk_duration=30.0
                    )
                telemetry_state = "completed"
            except Exception as exc:
                memory_failure = _is_memory_failure(exc)
                self._evict_loaded_model("failed-transcription")
                raise
            finally:
                # Release per-transcription activation buffers while preserving
                # the model in Performance mode for a faster repeat request.
                _release_device_memory("mps")
                self._active = False
                self._last_model_activity_at = time.time()
                if telemetry is not None:
                    telemetry_result = telemetry.finish(
                        state=telemetry_state,
                        memory_failure=memory_failure,
                        restart_scheduled=False,
                        model_retained=(
                            telemetry_state == "completed"
                            and self.has_loaded_model()
                        ),
                    )

        # mlx-audio returns different result shapes by engine. Normalize all of
        # them into Voice Studio's existing transcript + subtitle contract.
        text = _result_field(result, "text")
        detected_lang = _result_field(result, "language")
        if spec.engine == "moonshine":
            clean_text = (text or "").strip()
            raw_segments = (
                [{"start": 0.0, "end": audio_duration or 0.0, "text": clean_text}]
                if clean_text and audio_duration
                else []
            )
        elif spec.engine == "nemotron":
            raw_segments = _segments_from_nemotron(
                result, word_timestamps=word_timestamps
            )
            detected_lang = lang or "auto"
        else:
            raw_segments = _result_field(result, "segments")

        text = (text or "").strip()
        raw_segments = raw_segments or []

        normalized_text, segments = _normalize_segments(
            raw_segments,
            word_timestamps=word_timestamps,
            audio_duration=audio_duration,
        )
        if raw_segments:
            text = normalized_text

        duration = (
            audio_duration
            if audio_duration is not None
            else (segments[-1]["end"] if segments else 0.0)
        )

        return {
            "text": text,
            "language": detected_lang or lang or "en",
            "duration": round(float(duration), 3),
            "model": repo,
            "segments": segments,
            "srt": segments_to_srt(segments),
            "vtt": segments_to_vtt(segments),
            "elapsed_seconds": round(time.time() - started, 2),
            "resource_telemetry": telemetry_result,
        }

    def transcribe_locked(
        self,
        audio_path: str,
        *,
        model_repo: Optional[str] = None,
        language: Optional[str] = None,
        word_timestamps: bool = False,
    ) -> dict:
        """Transcribe while the caller already owns Voice Studio's GPU lock."""
        return self.transcribe(
            audio_path,
            model_repo=model_repo,
            language=language,
            word_timestamps=word_timestamps,
            _lock_already_held=True,
        )


manager = TranscriptionManager()
