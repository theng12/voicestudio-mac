from backend import transcription


MOONSHINE_REPO = "moonshine-ai/moonshine-base"
NEMOTRON_REPO = "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"


def _models_by_repo(payload: dict) -> dict[str, dict]:
    return {row["repo"]: row for row in payload["models"]}


def test_internal_asr_registry_preserves_whisper_default() -> None:
    assert transcription.recommended_model() == (
        "mlx-community/whisper-large-v3-turbo"
    )
    assert transcription.model_for_repo(MOONSHINE_REPO).engine == "moonshine"
    assert transcription.model_for_repo(NEMOTRON_REPO).engine == "nemotron"
    assert {model.engine for model in transcription.WHISPER_MODELS} == {"whisper"}


def test_internal_asr_registry_records_exact_candidate_truth() -> None:
    moonshine = transcription.model_for_repo(MOONSHINE_REPO)
    nemotron = transcription.model_for_repo(NEMOTRON_REPO)

    assert (moonshine.size_gb, moonshine.languages) == (0.25, "English")
    assert (nemotron.size_gb, nemotron.languages) == (0.76, "Multilingual")
    assert moonshine.internal_candidate is True
    assert nemotron.internal_candidate is True


def test_internal_candidates_publish_truth_without_genstudio_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(transcription, "_have_mlx_audio_stt", lambda: True)
    monkeypatch.setattr(transcription, "candidate_summary", lambda _repo: None)
    monkeypatch.setattr(
        transcription.cache,
        "status_snapshot",
        lambda repo: {
            "repo": repo,
            "state": "cached",
            "snapshot_revision": "test-revision",
        },
    )
    monkeypatch.setattr(transcription.generation_manager, "has_active_jobs", lambda: False)
    monkeypatch.setattr(transcription.manager, "is_active", lambda: False)

    models = _models_by_repo(transcription.availability())
    moonshine = models[MOONSHINE_REPO]
    nemotron = models[NEMOTRON_REPO]

    assert moonshine["engine"] == "moonshine"
    assert moonshine["min_unified_memory_gb"] == 8
    assert moonshine["internal_candidate"] is True
    assert moonshine["supports_segment_timestamps"] is False
    assert moonshine["supports_word_timestamps"] is False
    assert moonshine["supports_long_form"] is False
    assert nemotron["supports_segment_timestamps"] is True
    assert nemotron["supports_word_timestamps"] is True
    assert nemotron["supports_long_form"] is True
    assert "genstudio_candidate" not in moonshine
    assert "genstudio_candidate" not in nemotron
