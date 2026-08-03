"""
Speech-to-text / subtitle generation (Whisper via mlx-audio).

This is the STT counterpart to generation.py's TTS workers. The primary
consumer is a remote app (Story Studio) that generates narration audio via
our TTS endpoints, then wants timestamped subtitles (SRT/VTT) for it.

WHY THIS LIVES IN VOICE STUDIO (not a separate app):
- `mlx-audio` (already a dependency for the MLX TTS engines) ships a complete
  STT subsystem — `mlx_audio.stt` with whisper + a dozen other ASR models.
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
- No silent downloads: if the requested whisper model isn't cached, raise a
  clean error pointing at the Models tab / /api/downloads — never trigger an
  out-of-band download mid-request.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import cache, resource_telemetry
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


# ───────────── Whisper model registry ─────────────
# All repos verified live on huggingface.co. Sizes are approximate on-disk
# (post-download). `recommended` marks the default the API uses when no model
# is specified. Adding a new ASR model is a one-line append here — the download
# flow (generic /api/downloads) and the worker below need no other changes.

@dataclass(frozen=True)
class WhisperModel:
    repo: str
    label: str
    size_gb: float
    note: str
    recommended: bool = False


WHISPER_MODELS: tuple[WhisperModel, ...] = (
    WhisperModel(
        repo="mlx-community/whisper-large-v3-turbo",
        label="Whisper large-v3 turbo",
        size_gb=1.6,
        note="Recommended. Near-large accuracy at ~8× the speed. Best default for subtitles.",
        recommended=True,
    ),
    WhisperModel(
        repo="mlx-community/whisper-large-v3-turbo-q4",
        label="Whisper large-v3 turbo (4-bit)",
        size_gb=0.5,
        note="Quantized turbo — turbo accuracy at a third of the disk/memory. Great on 8 GB Macs.",
    ),
    WhisperModel(
        repo="mlx-community/whisper-large-v3-mlx",
        label="Whisper large-v3 (full)",
        size_gb=3.1,
        note="Highest accuracy, slowest. Use for final renders or noisy/accented audio.",
    ),
    WhisperModel(
        repo="mlx-community/whisper-small-mlx",
        label="Whisper small",
        size_gb=0.5,
        note="Fast, decent accuracy. Fine for clean TTS audio in English.",
    ),
    WhisperModel(
        repo="mlx-community/whisper-base-mlx",
        label="Whisper base",
        size_gb=0.15,
        note="Very fast, lower accuracy. Quick drafts / very clean audio.",
    ),
    WhisperModel(
        repo="mlx-community/whisper-tiny",
        label="Whisper tiny",
        size_gb=0.07,
        note="Smallest. Fastest. Lowest accuracy — testing / latency-critical only.",
    ),
)

_BY_REPO = {m.repo: m for m in WHISPER_MODELS}

# The mlx-community whisper repos ship ONLY config.json + weights — no HF
# processor files (preprocessor_config.json, tokenizer, vocab). mlx-audio's
# whisper post-load hook does `WhisperProcessor.from_pretrained(<local snapshot>)`,
# which therefore fails → model._processor = None → at transcribe time you get
# "Processor not found. Make sure the model was loaded with a HuggingFace
# processor." This affects ALL six repos (turbo, turbo-q4, large-v3, small,
# base, tiny) equally — it is NOT specific to the quantized one.
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
    "mlx-community/whisper-tiny":              "openai/whisper-tiny",
}


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
    for m in WHISPER_MODELS:
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
    is the STT stack importable, what device, and which whisper models are
    cached + ready right now."""
    stt_ok = _have_mlx_audio_stt()
    worker_busy = generation_manager.has_active_jobs() or manager.is_active()
    models = []
    for m in WHISPER_MODELS:
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
    return "\n".join(lines).strip() + "\n"


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
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
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
                word_start = max(start, float(word.get("start", start)))
                word_end = max(word_start, float(word.get("end", word_start)))
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


# ───────────── transcription manager ─────────────

@dataclass
class TranscriptionManager:
    _model: object = field(default=None, repr=False)
    _model_repo: Optional[str] = None
    _active: bool = field(default=False, repr=False)
    _last_model_activity_at: Optional[float] = field(default=None, repr=False)

    def is_active(self) -> bool:
        return self._active

    def loaded_model_key(self) -> Optional[tuple[str, str]]:
        if self._model is not None and self._model_repo:
            return (self._model_repo, "whisper-stt")
        return None

    def last_activity_at(self) -> Optional[float]:
        return self._last_model_activity_at

    def _evict_loaded_model(self, reason: str) -> dict:
        key = self.loaded_model_key()
        actions: list[str] = []
        if self._model is not None:
            self._model = None
            actions.append("cleared whisper transcription model")
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
                f"Whisper model {repo} is not downloaded. "
                "Download it first (Models tab, or POST /api/downloads)."
            )
        candidates = [s for s in snapshots.iterdir()
                      if s.is_dir() and not s.name.startswith(".")]
        if not candidates:
            raise RuntimeError(f"No snapshot subfolder under {snapshots} for {repo}.")
        return candidates[0]

    def _get_model(self, repo: str):
        """Lazy-load + cache one whisper model. Evicts on repo switch so two
        whisper models (or a whisper + a TTS model) don't co-reside in unified
        memory. Explicit-path standard: pass the snapshot Path, not the repo."""
        if self._model_repo == repo and self._model is not None:
            return self._model

        if self._model is not None:
            print(f"[stt] evicting cached whisper model ({self._model_repo})", flush=True)
            try:
                del self._model
            except Exception:
                pass
            self._model = None
            self._model_repo = None
            _release_device_memory("mps")

        from mlx_audio.stt.utils import load_model
        snapshot_path = self._snapshot_path(repo)
        print(f"[stt] loading whisper from {snapshot_path}", flush=True)
        model = load_model(snapshot_path)          # Path object — see v1.2.8

        # The mlx-community repos don't bundle the HF processor, so load_model's
        # post-hook leaves model._processor = None → "Processor not found" at
        # transcribe time. Attach a tokenizer from the matching base OpenAI repo.
        if getattr(model, "_processor", None) is None:
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
    ) -> dict:
        """Transcribe an audio file → text + timestamped segments + SRT + VTT.

        Serialized against the global generation lock so an in-flight TTS job
        and a transcription never both hold the GPU (Metal OOM guard).
        """
        repo = (model_repo or "").strip() or recommended_model()
        if repo not in _BY_REPO:
            raise ValueError(
                f"Unknown whisper model {repo!r}. "
                f"Known: {sorted(_BY_REPO)}"
            )
        if cache.cache_state(repo) != "cached":
            raise RuntimeError(
                f"Whisper model {repo} is not fully cached. "
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

        # Hold the SAME lock TTS generation uses — one GPU job at a time.
        with _GEN_LOCK:
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
                result = model.generate(
                    str(p),
                    language=lang,
                    word_timestamps=word_timestamps,
                    return_timestamps=True,
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
                            and self._model is not None
                        ),
                    )

        # mlx-audio returns an STTOutput dataclass (or dict-ish) with .text,
        # .segments (list of dicts), .language. Be defensive about shape.
        text = getattr(result, "text", None)
        raw_segments = getattr(result, "segments", None)
        detected_lang = getattr(result, "language", None)
        if text is None and isinstance(result, dict):
            text = result.get("text")
            raw_segments = result.get("segments")
            detected_lang = result.get("language")

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


manager = TranscriptionManager()
