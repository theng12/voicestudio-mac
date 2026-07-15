from __future__ import annotations

from pathlib import Path

from backend import main


class _Voice:
    id = "voice-1"

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "name": "Narrator",
            "has_transcript": True,
        }


class _Library:
    def list(self):
        return [_Voice()]

    def transcript(self, voice_id: str) -> str:
        assert voice_id == "voice-1"
        return "The transcript saved with the reference voice."


def test_voice_listing_includes_saved_transcript(monkeypatch) -> None:
    monkeypatch.setattr(main, "voice_library", _Library())

    result = main.list_voices()

    assert result["voices"] == [{
        "id": "voice-1",
        "name": "Narrator",
        "has_transcript": True,
        "transcript": "The transcript saved with the reference voice.",
    }]


def test_voice_mutation_serialization_includes_saved_transcript(monkeypatch) -> None:
    monkeypatch.setattr(main, "voice_library", _Library())

    result = main._serialize_voice(_Voice())

    assert result["transcript"] == "The transcript saved with the reference voice."


def test_frontend_uses_saved_transcript_and_clears_stale_override() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    source = (frontend / "app.js").read_text()
    markup = (frontend / "index.html").read_text()

    assert "referenceTranscriptForRequest()" in source
    assert "this.selectedStoredTranscript" in source
    assert 'this.gen.ref_transcript = "";' in source
    assert "Saved reference transcript" in markup
    assert '@change="onReferenceVoiceChange()"' in markup
    assert "Loaded automatically from the selected voice and sent to F5-TTS" in markup
