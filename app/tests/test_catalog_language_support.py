from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import catalog, generation, main


PLACEHOLDER = re.compile(r"^\+\d+\s+more$")


class _VoiceLibrary:
    def __init__(self, reference: Path) -> None:
        self.reference = reference

    def get(self, voice_id: str):
        return {"id": voice_id} if voice_id == "voice-1" else None

    def reference_path(self, voice_id: str) -> Path:
        return self.reference

    def transcript(self, voice_id: str) -> str:
        return ""


def _model(repo: str) -> dict:
    entry = catalog.get_model(repo)
    assert entry is not None
    return catalog.serialize_model(entry)


def test_language_enumerations_are_exact_unique_codes_without_placeholders() -> None:
    for entry in catalog.CATALOG:
        assert not any(PLACEHOLDER.fullmatch(code) for code in entry.languages)
        payload = catalog.serialize_model(entry)
        support = payload["language_support"]
        assert not any(PLACEHOLDER.fullmatch(code) for code in support["codes"])
        if support["enumeration_status"] == "exact":
            assert support["codes"] == payload["languages"]
            assert len(support["codes"]) == len(set(support["codes"]))
            assert all(re.fullmatch(r"[a-z]{2,3}", code) for code in support["codes"])


def test_group_b_language_support_truth_is_structured_and_non_selectable_when_claimed() -> None:
    vox = _model("mlx-community/VoxCPM2-4bit")["language_support"]
    assert vox == {
        "input_selection": "none",
        "enumeration_status": "exact",
        "codes": list(catalog.VOXCPM2_LANGUAGE_CODES),
        "claimed_count": None,
        "claimed_lower_bound": None,
        "runtime_enforced": False,
    }

    chatterbox_contracts = {
        "mlx-community/chatterbox-4bit": list(catalog.CHATTERBOX_LANGUAGE_CODES),
        "mlx-community/chatterbox-8bit": list(catalog.CHATTERBOX_LANGUAGE_CODES),
        "mlx-community/chatterbox-turbo-4bit": ["en"],
    }
    for repo, expected_codes in chatterbox_contracts.items():
        chatterbox = _model(repo)["language_support"]
        assert chatterbox["input_selection"] == "required"
        assert chatterbox["runtime_enforced"] is True
        assert chatterbox["codes"] == expected_codes

    omni = _model("mlx-community/OmniVoice-bfloat16")
    assert omni["languages"] == []
    assert omni["language_support"] == {
        "input_selection": "none",
        "enumeration_status": "claimed_count",
        "codes": [],
        "claimed_count": 646,
        "claimed_lower_bound": None,
        "runtime_enforced": False,
    }

    fish = _model("mlx-community/fish-audio-s2-pro-8bit")
    assert fish["languages"] == []
    assert fish["language_support"]["input_selection"] == "none"
    assert fish["language_support"]["enumeration_status"] == "claimed_lower_bound"
    assert fish["language_support"]["claimed_lower_bound"] == 80
    assert fish["language_support"]["codes"] == []


def test_chatterbox_requires_and_forwards_an_allowlisted_language(tmp_path: Path) -> None:
    manager = object.__new__(generation.GenerationManager)
    voices = SimpleNamespace(library=_VoiceLibrary(tmp_path / "voice.wav"))
    (tmp_path / "voice.wav").touch()
    entry = catalog.get_model("mlx-community/chatterbox-4bit")
    assert entry is not None

    kwargs: dict = {}
    manager._mlx_kwargs_clone_with_intensity(
        entry, {"voice_library_id": "voice-1", "language": "PT"}, kwargs, voices
    )
    assert kwargs["lang_code"] == "pt"

    with pytest.raises(ValueError, match="needs a language code"):
        manager._mlx_kwargs_clone_with_intensity(
            entry, {"voice_library_id": "voice-1"}, {}, voices
        )
    with pytest.raises(ValueError, match="Unsupported Chatterbox language code"):
        manager._mlx_kwargs_clone_with_intensity(
            entry, {"voice_library_id": "voice-1", "language": "xx"}, {}, voices
        )

    turbo = catalog.get_model("mlx-community/chatterbox-turbo-4bit")
    assert turbo is not None
    with pytest.raises(ValueError, match="Unsupported Chatterbox language code"):
        manager._mlx_kwargs_clone_with_intensity(
            turbo, {"voice_library_id": "voice-1", "language": "pt"}, {}, voices
        )


def test_catalog_api_models_include_language_support_shape(monkeypatch) -> None:
    monkeypatch.setattr(main, "_cache_with_companions", lambda _repo: {"state": "absent"})
    monkeypatch.setattr(main.manager, "active_for_repo", lambda _repo: None)
    monkeypatch.setattr(main.gen_manager, "model_runtime_status", lambda _model: {"runtime_ready": False})
    monkeypatch.setattr(main, "candidate_summary", lambda _repo: None)

    models = {item["repo"]: item for item in main.get_catalog()["models"]}
    support = models["mlx-community/chatterbox-4bit"]["language_support"]
    assert set(support) == {
        "input_selection", "enumeration_status", "codes", "claimed_count",
        "claimed_lower_bound", "runtime_enforced",
    }
    assert support["input_selection"] == "required"


def test_omnivoice_nonverbal_tags_match_the_installed_model_exactly() -> None:
    """The catalog advertised "[cough]", which mlx-audio's OmniVoice does not
    recognise: unknown tags fall through to ordinary tokenization and render as
    noise. Owner listening on 2026-08-07 confirmed it. Pin the advertised list to
    the model's own pattern so documentation cannot drift from the engine."""
    from mlx_audio.tts.models.omnivoice import omnivoice as ov

    raw = ov._NONVERBAL_PATTERN.pattern
    inner = raw[raw.index("(") + 1:raw.rindex(")")]
    actual = {t.strip() for t in inner.split("|") if t.strip()}
    assert set(catalog.OMNIVOICE_NONVERBAL_TAGS) == actual, (
        "catalog tag list has drifted from mlx-audio's _NONVERBAL_PATTERN"
    )
    assert "cough" not in catalog.OMNIVOICE_NONVERBAL_TAGS

    family = catalog.FAMILIES["omnivoice"]
    assert "[cough]" not in family.summary
    # The guidance must still WARN about cough rather than silently omit it.
    assert "[cough]" in family.how_to_use
    assert "[laughter]" in family.how_to_use
