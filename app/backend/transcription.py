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

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import cache
# Reuse the TTS side's device detection, MLX cache release, and the GLOBAL
# generation lock. Sharing the lock is the key safety property: a transcription
# can't start while a TTS job holds the GPU, and vice versa. No circular import
# risk — generation.py does not import this module.
from .generation import _GEN_LOCK, _detect_device, _release_device_memory


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
    models = []
    for m in WHISPER_MODELS:
        models.append({
            "repo": m.repo,
            "label": m.label,
            "size_gb": m.size_gb,
            "note": m.note,
            "recommended": m.recommended,
            "cached": cache.cache_state(m.repo) == "cached",
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


# ───────────── transcription manager ─────────────

@dataclass
class TranscriptionManager:
    _model: object = field(default=None, repr=False)
    _model_repo: Optional[str] = None

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
        self._model = model
        self._model_repo = repo
        return model

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

        started = time.time()
        # Hold the SAME lock TTS generation uses — one GPU job at a time.
        with _GEN_LOCK:
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
            # Release per-transcription activation buffers (v1.2.7 pattern) so
            # a following TTS/STT job starts from a clean Metal baseline.
            _release_device_memory("mps")

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

        # Normalize segments to a stable, JSON-friendly shape.
        segments: list[dict] = []
        for i, seg in enumerate(raw_segments):
            entry = {
                "id": i,
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": (seg.get("text") or "").strip(),
            }
            if word_timestamps and seg.get("words"):
                entry["words"] = [
                    {
                        "word": (w.get("word") or "").strip(),
                        "start": float(w.get("start", 0.0)),
                        "end": float(w.get("end", 0.0)),
                    }
                    for w in seg["words"]
                ]
            segments.append(entry)

        duration = segments[-1]["end"] if segments else 0.0

        return {
            "text": text,
            "language": detected_lang or lang or "en",
            "duration": round(float(duration), 3),
            "model": repo,
            "segments": segments,
            "srt": segments_to_srt(segments),
            "vtt": segments_to_vtt(segments),
            "elapsed_seconds": round(time.time() - started, 2),
        }


manager = TranscriptionManager()
