"""Stable VoiceStudio-owned evidence for the GenStudio TTS boundary.

This module deliberately contains only facts VoiceStudio can prove about its
own completed final audio artifact. Studio Hub remains authoritative for worker
assignment and fleet routing; GenStudio remains authoritative for job ownership,
customers, billing, and durable publication.

Add future worker-owned result fields here, with a regression test, instead of
letting the VoiceStudio → Studio Hub → GenStudio contract drift across callers.
"""

from __future__ import annotations

from typing import Any


INTEGRATION_NAME = "voicestudio_genstudio_integration"
INTEGRATION_VERSION = "1.1"

# Worker-owned fields that Studio Hub may relay and GenStudio may independently
# verify. ``worker_id`` is intentionally absent: Studio Hub supplies it from
# the worker it actually assigned.
FINAL_TTS_RESULT_FIELDS = (
    "integration_name",
    "integration_version",
    "internal_model_id",
    "model_revision",
    "runtime_revision",
    "voice_library_id",
    "voice_revision",
    "reference_audio_sha256",
    "reference_source_sha256",
    "reference_preparation_revision",
    "reference_duration_s",
    "long_form_strategy",
    "chunk_total",
    "runtime_s",
    "media_type",
    "format",
    "bytes",
    "sha256",
    "audio_duration_s",
    "audio_duration_ms",
    "sample_rate_hz",
    "channels",
)


def final_tts_result(
    *,
    internal_model_id: str | None,
    model_revision: str | None,
    voice_library_id: str | None,
    voice_revision: str | None,
    runtime_s: float | None,
    media_type: str | None,
    format: str | None,
    byte_size: int | None,
    sha256: str | None,
    audio_duration_s: float | None,
    audio_duration_ms: int | None,
    sample_rate_hz: int | None,
    channels: int | None,
    reference_audio_sha256: str | None = None,
    reference_source_sha256: str | None = None,
    reference_preparation_revision: str | None = None,
    reference_duration_s: float | None = None,
    long_form_strategy: str | None = None,
    chunk_total: int | None = None,
) -> dict[str, Any]:
    """Return the versioned, worker-owned final TTS evidence envelope."""
    return {
        "integration_name": INTEGRATION_NAME,
        "integration_version": INTEGRATION_VERSION,
        "internal_model_id": internal_model_id,
        # ``runtime_revision`` is the explicit GenStudio name for the same
        # immutable cached model snapshot kept under the historic field below.
        "model_revision": model_revision,
        "runtime_revision": model_revision,
        "voice_library_id": voice_library_id,
        "voice_revision": voice_revision,
        "reference_audio_sha256": reference_audio_sha256,
        "reference_source_sha256": reference_source_sha256,
        "reference_preparation_revision": reference_preparation_revision,
        "reference_duration_s": reference_duration_s,
        "long_form_strategy": long_form_strategy,
        "chunk_total": chunk_total,
        "runtime_s": runtime_s,
        "media_type": media_type,
        "format": format,
        "bytes": byte_size,
        "sha256": sha256,
        "audio_duration_s": audio_duration_s,
        "audio_duration_ms": audio_duration_ms,
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
    }
