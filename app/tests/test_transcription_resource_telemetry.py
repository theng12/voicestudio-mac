from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import transcription


class FakeSampler:
    instances = []

    def __init__(self, publish):
        self.publish = publish
        self.finished = None
        self.__class__.instances.append(self)

    def start(self):
        self.publish({"schema": "voicestudio.resource-telemetry", "phase": "running"})
        return self

    def finish(self, **kwargs):
        self.finished = kwargs
        payload = {
            "schema": "voicestudio.resource-telemetry",
            "schema_version": 1,
            "outcome": kwargs,
        }
        self.publish(payload)
        return payload


@pytest.fixture(autouse=True)
def reset_fake_sampler():
    FakeSampler.instances.clear()


def _manager(monkeypatch, tmp_path: Path, model):
    audio = tmp_path / "control.wav"
    audio.write_bytes(b"audio")
    manager = transcription.TranscriptionManager()
    monkeypatch.setattr(transcription.cache, "cache_state", lambda _repo: "cached")
    monkeypatch.setattr(transcription, "_audio_duration_seconds", lambda _path: 3.0)
    monkeypatch.setattr(manager, "_get_model", lambda _repo: model)
    monkeypatch.setattr(manager, "_evict_loaded_model", lambda _reason: {})
    monkeypatch.setattr(transcription, "_release_device_memory", lambda _device: None)
    monkeypatch.setattr(
        transcription.resource_telemetry,
        "JobResourceSampler",
        FakeSampler,
    )
    return manager, audio


def test_successful_transcription_returns_worker_resource_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    model = SimpleNamespace(
        generate=lambda *_args, **_kwargs: SimpleNamespace(
            text="Control transcript.",
            language="en",
            segments=[{"start": 0.0, "end": 3.0, "text": "Control transcript."}],
        )
    )
    manager, audio = _manager(monkeypatch, tmp_path, model)

    result = manager.transcribe(
        str(audio),
        model_repo="mlx-community/whisper-large-v3-turbo",
        language="en",
        word_timestamps=True,
    )

    assert result["resource_telemetry"] == {
        "schema": "voicestudio.resource-telemetry",
        "schema_version": 1,
        "outcome": {
            "state": "completed",
            "memory_failure": False,
            "restart_scheduled": False,
            "model_retained": False,
        },
    }
    assert FakeSampler.instances[0].finished["state"] == "completed"


def test_failed_transcription_finishes_resource_sampler(
    monkeypatch, tmp_path: Path
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("Metal out of memory")

    manager, audio = _manager(
        monkeypatch,
        tmp_path,
        SimpleNamespace(generate=fail),
    )

    with pytest.raises(RuntimeError, match="Metal out of memory"):
        manager.transcribe(
            str(audio),
            model_repo="mlx-community/whisper-large-v3-turbo",
        )

    assert FakeSampler.instances[0].finished == {
        "state": "failed",
        "memory_failure": True,
        "restart_scheduled": False,
        "model_retained": False,
    }


def test_retired_whisper_tiny_is_rejected_without_fallback(tmp_path: Path) -> None:
    audio = tmp_path / "control.wav"
    audio.write_bytes(b"audio")
    manager = transcription.TranscriptionManager()

    with pytest.raises(ValueError, match="Unknown transcription model"):
        manager.transcribe(
            str(audio),
            model_repo="mlx-community/whisper-tiny",
        )

    assert manager._model_repo is None


def test_normalization_discards_words_at_or_after_eof_from_an_overlapping_segment() -> None:
    text, segments = transcription._normalize_segments(
        [{
            "start": 2.8,
            "end": 4.0,
            "text": "Last real word padded hallucination.",
            "words": [
                {"word": "Last", "start": 2.8, "end": 2.9},
                {"word": "real", "start": 2.9, "end": 3.0},
                {"word": "word", "start": 3.0, "end": 3.1},
                {"word": "padded", "start": 3.1, "end": 3.2},
            ],
        }],
        word_timestamps=True,
        audio_duration=3.0,
    )

    assert text == "Last real word padded hallucination."
    assert [word["word"] for word in segments[0]["words"]] == ["Last", "real"]
