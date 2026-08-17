"""The decode options Voice Studio pins on every Whisper call.

Whisper's default `condition_on_previous_text=True` feeds each 30-second
window's output back as the prompt for the next one, which turns a single
hallucinated token into a self-reinforcing block of invented text. Measured on
19 chapters of real narration, disabling it cut invented words by 94% (758 ->
46) while costing no coherent speech. These tests hold that decision in place:
the flag must actually reach `model.generate`, for every caller, always.

What these tests can and cannot prove: they prove the argument is passed. They
cannot prove the model hallucinates less — that is the model's behaviour, not
this code's, and it lives in the A/B evidence recorded in
model-audits/2026-08-17-whisper-decode-conditioning/.
"""
from pathlib import Path
from types import SimpleNamespace

from backend import transcription


class _Sampler:
    def __init__(self, publish):
        self.publish = publish

    def start(self):
        return self

    def finish(self, **kwargs):
        return {"schema": "voicestudio.resource-telemetry", "outcome": kwargs}


def _manager(monkeypatch, tmp_path: Path, captured: dict):
    audio = tmp_path / "narration.wav"
    audio.write_bytes(b"audio")

    def fake_generate(*args, **kwargs):
        captured.update(kwargs)
        captured["positional"] = args
        return SimpleNamespace(
            text="The knight slept.",
            language="en",
            segments=[{"start": 0.0, "end": 3.0, "text": "The knight slept."}],
        )

    manager = transcription.TranscriptionManager()
    monkeypatch.setattr(transcription.cache, "cache_state", lambda _repo: "cached")
    monkeypatch.setattr(transcription, "_audio_duration_seconds", lambda _path: 3.0)
    monkeypatch.setattr(
        manager, "_get_model", lambda _repo: SimpleNamespace(generate=fake_generate)
    )
    monkeypatch.setattr(manager, "_evict_loaded_model", lambda _reason: {})
    monkeypatch.setattr(transcription, "_release_device_memory", lambda _device: None)
    monkeypatch.setattr(transcription.resource_telemetry, "JobResourceSampler", _Sampler)
    return manager, audio


def test_transcribe_disables_conditioning_on_previous_text(monkeypatch, tmp_path):
    """The hallucination-cascade guard reaches the model on an ordinary call."""
    captured: dict = {}
    manager, audio = _manager(monkeypatch, tmp_path, captured)

    manager.transcribe(str(audio), language="en")

    assert captured["condition_on_previous_text"] is False


def test_word_timestamp_callers_get_the_same_guard(monkeypatch, tmp_path):
    """The Qwen voice canary transcribes with word_timestamps=True to score
    coverage against the script it asked for. It must get the same decode
    options as subtitle callers — a canary scored against a hallucinating
    transcript is measuring the transcriber, not the voice."""
    captured: dict = {}
    manager, audio = _manager(monkeypatch, tmp_path, captured)

    # transcribe_locked asserts the caller already owns the shared GPU lock,
    # exactly as generation.py's canary does.
    with transcription._GEN_LOCK:
        manager.transcribe_locked(str(audio), language="en", word_timestamps=True)

    assert captured["condition_on_previous_text"] is False
    assert captured["word_timestamps"] is True


def test_conditioning_is_not_caller_configurable(monkeypatch, tmp_path):
    """A caller cannot turn the cascade back on. `transcribe` accepts no
    conditioning argument, and passing one is a TypeError rather than a
    silently honoured request."""
    captured: dict = {}
    manager, audio = _manager(monkeypatch, tmp_path, captured)

    try:
        manager.transcribe(
            str(audio), language="en", condition_on_previous_text=True
        )
    except TypeError:
        pass
    else:  # pragma: no cover - only reached if the seam is reopened
        raise AssertionError(
            "transcribe() accepted condition_on_previous_text from a caller; "
            "this flag is deliberately not part of the request contract."
        )


def test_pinned_constant_stays_off():
    """Guards the constant itself, so flipping it back is a visible test change
    rather than a one-character edit nobody reviews."""
    assert transcription._CONDITION_ON_PREVIOUS_TEXT is False
