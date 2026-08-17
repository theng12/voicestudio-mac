from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import transcription


WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"
MOONSHINE_REPO = "moonshine-ai/moonshine-base"
NEMOTRON_REPO = "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"


class _Sampler:
    def __init__(self, publish):
        self.publish = publish

    def start(self):
        return self

    def finish(self, **kwargs):
        return {"schema": "voicestudio.resource-telemetry", "outcome": kwargs}


class _RecordingModel:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def _manager(monkeypatch, tmp_path: Path, result, *, duration: float = 3.0):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    model = _RecordingModel(result)
    manager = transcription.TranscriptionManager()
    monkeypatch.setattr(transcription.cache, "cache_state", lambda _repo: "cached")
    monkeypatch.setattr(transcription, "_audio_duration_seconds", lambda _path: duration)
    monkeypatch.setattr(manager, "_get_model", lambda _repo: model)
    monkeypatch.setattr(manager, "_evict_loaded_model", lambda _reason: {})
    monkeypatch.setattr(transcription, "_release_device_memory", lambda _device: None)
    monkeypatch.setattr(transcription.resource_telemetry, "JobResourceSampler", _Sampler)
    return manager, model, audio


def test_whisper_alone_receives_the_approved_decode_policy(monkeypatch, tmp_path) -> None:
    result = SimpleNamespace(
        text="The knight slept.",
        language="en",
        segments=[{"start": 0.0, "end": 3.0, "text": "The knight slept."}],
    )
    manager, model, audio = _manager(monkeypatch, tmp_path, result)

    manager.transcribe(str(audio), model_repo=WHISPER_REPO, language="en")

    assert model.calls[0][1] == {
        "language": "en",
        "word_timestamps": False,
        "return_timestamps": True,
        "condition_on_previous_text": False,
    }


def test_moonshine_rejects_word_timestamps_before_inference(monkeypatch, tmp_path) -> None:
    manager, model, audio = _manager(
        monkeypatch,
        tmp_path,
        SimpleNamespace(text="Short transcript."),
    )

    with pytest.raises(ValueError, match="does not support word timestamps"):
        manager.transcribe(
            str(audio), model_repo=MOONSHINE_REPO, word_timestamps=True
        )

    assert model.calls == []


def test_nemotron_receives_language_and_bounded_chunking(monkeypatch, tmp_path) -> None:
    manager, model, audio = _manager(
        monkeypatch,
        tmp_path,
        SimpleNamespace(text="Hello.", sentences=[]),
    )

    manager.transcribe(
        str(audio),
        model_repo=NEMOTRON_REPO,
        language="en",
        word_timestamps=True,
    )

    assert model.calls[0][1] == {"language": "en", "chunk_duration": 30.0}


def test_only_whisper_loading_attaches_a_processor(monkeypatch, tmp_path) -> None:
    from mlx_audio.stt import utils

    manager = transcription.TranscriptionManager()
    attached = []
    monkeypatch.setattr(manager, "_snapshot_path", lambda _repo: tmp_path)
    monkeypatch.setattr(utils, "load_model", lambda _path: SimpleNamespace(_processor=None))
    monkeypatch.setattr(manager, "_attach_processor", lambda _model, repo: attached.append(repo))
    monkeypatch.setattr(transcription, "_release_device_memory", lambda _device: None)

    manager._get_model(MOONSHINE_REPO)
    manager._get_model(NEMOTRON_REPO)
    manager._get_model(WHISPER_REPO)

    assert attached == [WHISPER_REPO]


@pytest.mark.parametrize("repo", [WHISPER_REPO, MOONSHINE_REPO, NEMOTRON_REPO])
def test_loaded_model_key_uses_generic_transcription_family(repo: str) -> None:
    manager = transcription.TranscriptionManager(_model=object(), _model_repo=repo)

    assert manager.loaded_model_key() == (repo, "transcription-stt")


def test_moonshine_text_becomes_one_full_duration_segment(monkeypatch, tmp_path) -> None:
    manager, _model, audio = _manager(
        monkeypatch,
        tmp_path,
        SimpleNamespace(text="  Short transcript.  "),
        duration=4.25,
    )

    result = manager.transcribe(str(audio), model_repo=MOONSHINE_REPO)

    assert result["text"] == "Short transcript."
    assert result["segments"] == [
        {"id": 0, "start": 0.0, "end": 4.25, "text": "Short transcript."}
    ]
    assert "00:00:00,000 --> 00:00:04,250" in result["srt"]


def test_empty_moonshine_text_has_no_subtitle_cues(monkeypatch, tmp_path) -> None:
    manager, _model, audio = _manager(
        monkeypatch,
        tmp_path,
        SimpleNamespace(text="  "),
    )

    result = manager.transcribe(str(audio), model_repo=MOONSHINE_REPO)

    assert result["segments"] == []
    assert result["srt"] == ""
    assert result["vtt"] == "WEBVTT\n"


def test_nemotron_sentences_and_requested_words_are_preserved(monkeypatch, tmp_path) -> None:
    result = SimpleNamespace(
        text="Hello world.",
        sentences=[
            SimpleNamespace(
                text="Hello world.",
                start=0.1,
                end=1.4,
                tokens=[
                    SimpleNamespace(text="Hello", start=0.1, end=0.5),
                    SimpleNamespace(text=" world.", start=0.55, end=1.4),
                ],
            )
        ],
    )
    manager, _model, audio = _manager(monkeypatch, tmp_path, result)

    payload = manager.transcribe(
        str(audio), model_repo=NEMOTRON_REPO, word_timestamps=True
    )

    assert payload["segments"] == [
        {
            "id": 0,
            "start": 0.1,
            "end": 1.4,
            "text": "Hello world.",
            "words": [
                {"word": "Hello", "start": 0.1, "end": 0.5},
                {"word": "world.", "start": 0.55, "end": 1.4},
            ],
        }
    ]


def test_nemotron_omits_words_when_not_requested(monkeypatch, tmp_path) -> None:
    sentence = SimpleNamespace(
        text="Hello.",
        start=0.1,
        end=0.9,
        tokens=[SimpleNamespace(text="Hello.", start=0.1, end=0.9)],
    )
    manager, _model, audio = _manager(
        monkeypatch,
        tmp_path,
        SimpleNamespace(text="Hello.", sentences=[sentence]),
    )

    payload = manager.transcribe(str(audio), model_repo=NEMOTRON_REPO)

    assert "words" not in payload["segments"][0]
