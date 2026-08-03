from __future__ import annotations

from pathlib import Path

import pytest

from backend import catalog, generation, long_form_policy, model_audits


@pytest.mark.parametrize(
    ("family", "repo", "section_chars", "join_ms"),
    [
        ("qwen3-tts", "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit", 288, 180),
        ("qwen3-tts", "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit", 360, 120),
        ("qwen3-tts", "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit", 360, 120),
        ("chatterbox-mlx", "mlx-community/chatterbox-8bit", 500, 120),
        ("chatterbox-mlx", "mlx-community/chatterbox-turbo-4bit", 400, 120),
        ("voxcpm-mlx", "mlx-community/VoxCPM2-4bit", 400, 120),
        ("kokoro-mlx", "mlx-community/Kokoro-82M-bf16", 3000, 120),
        ("vibevoice", "mlx-community/VibeVoice-Realtime-0.5B-4bit", 3000, 120),
        ("omnivoice", "mlx-community/OmniVoice-bfloat16", 288, 120),
        ("fish-audio-mlx", "mlx-community/fish-audio-s2-pro-8bit", 300, 120),
    ],
)
def test_catalog_and_runtime_share_exact_long_form_policy(
    family: str, repo: str, section_chars: int, join_ms: int
) -> None:
    entry = catalog.get_model(repo)
    assert entry is not None
    published = catalog.serialize_model(entry)["long_form_delivery"]

    assert published["section_max_characters"] == section_chars
    assert published["join_pause_milliseconds"] == join_ms
    assert published["split_method"] == "sentence_safe"
    assert published["customer_submits_complete_script"] is True
    assert published["note"]
    assert generation._long_form_join_pause_s(family, repo) == pytest.approx(
        join_ms / 1000
    )

    text = "Sentence-safe narration remains complete. " * 400
    chunks = generation._internal_mlx_text_chunks(family, repo, text)
    assert chunks
    assert all(len(chunk) <= section_chars for chunk in chunks)
    assert " ".join(chunks) == " ".join(text.split())


def test_exact_model_audit_override_is_published_and_executed(monkeypatch) -> None:
    repo = "mlx-community/chatterbox-8bit"
    monkeypatch.setattr(
        model_audits,
        "input_limits",
        lambda _repo: {"private_section_max_characters": 444},
    )
    entry = catalog.get_model(repo)
    assert entry is not None
    published = catalog.serialize_model(entry)["long_form_delivery"]

    assert published["section_max_characters"] == 444
    assert published["source"] == "model_audit"
    chunks = generation._internal_mlx_text_chunks(
        "chatterbox-mlx", repo, "Audited sentence delivery. " * 100
    )
    assert all(len(chunk) <= 444 for chunk in chunks)


def test_unmanaged_family_does_not_claim_voice_studio_policy() -> None:
    assert long_form_policy.policy_for("bark", "mlx-community/bark") is None
    entry = catalog.get_model("mlx-community/bark")
    assert entry is not None
    assert catalog.serialize_model(entry)["long_form_delivery"] is None


def test_models_page_renders_policy_from_catalog_without_frontend_limits() -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    markup = (frontend / "index.html").read_text(encoding="utf-8")
    script = (frontend / "app.js").read_text(encoding="utf-8")

    assert "m.long_form_delivery.section_max_characters" in markup
    assert "m.long_form_delivery.join_pause_milliseconds" in markup
    assert "m.long_form_delivery.note" in markup
    assert "customer submits one complete script" in markup
    assert "section_max_characters:" not in script
    assert "join_pause_milliseconds:" not in script
