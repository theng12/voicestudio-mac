from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import cache, model_storage
from backend import main as backend_main


def _cached_repo(tmp_path: Path, monkeypatch, repo: str, *, weight: bool = True) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    root = cache.repo_cache_dir(repo)
    snapshot = root / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    (root / "refs").mkdir()
    (root / "refs" / "main").write_text("a" * 40)
    name = "model.safetensors" if weight else "tokenizer.json"
    (snapshot / name).write_bytes(b"cache-data")
    return root


def _item(payload: dict, repo: str) -> dict:
    return next(
        item
        for group in payload["groups"]
        for item in group["items"]
        if item["repo"] == repo
    )


def test_existing_cache_is_indexed_in_place_and_notice_is_written(tmp_path, monkeypatch) -> None:
    repo = "mlx-community/Kokoro-82M-bf16"
    root = _cached_repo(tmp_path, monkeypatch, repo)

    payload = model_storage.inventory()
    item = _item(payload, repo)

    assert item["type"] == "model"
    assert item["family"] == "kokoro-mlx"
    assert item["cache"]["path"] == str(root)
    assert root.exists()
    notice = Path(payload["notice_path"])
    assert notice.parent == cache.hub_dir()
    assert "Do not rename, move, or remove individual files" in notice.read_text()


def test_installed_companion_is_grouped_and_protected(tmp_path, monkeypatch) -> None:
    parent = "mlx-community/chatterbox-8bit"
    companion = "mlx-community/S3TokenizerV2"
    _cached_repo(tmp_path, monkeypatch, parent)
    _cached_repo(tmp_path, monkeypatch, companion)

    item = _item(model_storage.inventory(), companion)

    assert item["type"] == "dependency"
    assert item["family"] == "chatterbox-mlx"
    assert item["used_by"] == [parent]
    assert item["removal"]["allowed"] is False
    with pytest.raises(model_storage.StorageConflict, match="Required by installed"):
        model_storage.remove_repo(companion)


def test_missing_companion_stays_visible_beneath_its_installed_parent(tmp_path, monkeypatch) -> None:
    parent = "mlx-community/orpheus-3b-0.1-ft-4bit"
    companion = "mlx-community/snac_24khz"
    _cached_repo(tmp_path, monkeypatch, parent)

    item = _item(model_storage.inventory(), companion)

    assert item["type"] == "dependency"
    assert item["present"] is False
    assert item["cache"]["state"] == "absent"
    assert item["used_by"] == [parent]
    assert item["removal"]["allowed"] is False


def test_whisper_processor_without_weights_is_a_complete_dependency(tmp_path, monkeypatch) -> None:
    parent = "mlx-community/whisper-large-v3-turbo-q4"
    companion = "openai/whisper-large-v3-turbo"
    _cached_repo(tmp_path, monkeypatch, parent)
    _cached_repo(tmp_path, monkeypatch, companion, weight=False)

    item = _item(model_storage.inventory(), companion)

    assert item["type"] == "dependency"
    assert item["cache"]["state"] == "cached"
    assert item["used_by"] == [parent]


def test_internal_asr_candidates_use_the_generic_transcription_family(
    tmp_path, monkeypatch
) -> None:
    moonshine = "moonshine-ai/moonshine-base"
    nemotron = "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"
    _cached_repo(tmp_path, monkeypatch, moonshine)
    _cached_repo(tmp_path, monkeypatch, nemotron)

    payload = model_storage.inventory()
    moonshine_item = _item(payload, moonshine)
    nemotron_item = _item(payload, nemotron)
    group = next(group for group in payload["groups"] if group["id"] == "transcription-stt")

    assert moonshine_item["family"] == "transcription-stt"
    assert nemotron_item["family"] == "transcription-stt"
    assert moonshine_item["type"] == nemotron_item["type"] == "model"
    assert moonshine_item["used_by"] == []
    assert nemotron_item["used_by"] == []
    assert group["label"] == "Transcription"
    assert group["summary"] == (
        "Local speech-to-text models and their required tokenizer assets."
    )


def test_unversioned_dependency_is_visible_as_partial(tmp_path, monkeypatch) -> None:
    parent = "mlx-community/whisper-large-v3-turbo-q4"
    companion = "openai/whisper-large-v3-turbo"
    _cached_repo(tmp_path, monkeypatch, parent)
    root = cache.repo_cache_dir(companion)
    snapshot = root / "snapshots" / "main"
    snapshot.mkdir(parents=True)
    (snapshot / "tokenizer.json").write_bytes(b"existing tokenizer")
    (root / "refs").mkdir()
    (root / "refs" / "main").write_text("main")

    item = _item(model_storage.inventory(), companion)

    assert item["cache"]["state"] == "partial"
    assert item["cache"]["snapshot_revision"] is None


def test_legacy_package_is_explained_and_can_be_removed_as_one_unit(tmp_path, monkeypatch) -> None:
    repo = "mlx-community/OmniVoice-fp32"
    root = _cached_repo(tmp_path, monkeypatch, repo)

    item = _item(model_storage.inventory(), repo)
    assert item["type"] == "legacy"
    assert item["removal"]["allowed"] is True

    result = model_storage.remove_repo(repo)

    assert result["removed"] is True
    assert result["freed_bytes"] == len(b"cache-data")
    assert not root.exists()


def test_retired_whisper_tiny_packages_are_explained_and_removable(tmp_path, monkeypatch) -> None:
    model = "mlx-community/whisper-tiny"
    processor = "openai/whisper-tiny"
    _cached_repo(tmp_path, monkeypatch, model)
    _cached_repo(tmp_path, monkeypatch, processor, weight=False)

    payload = model_storage.inventory()
    model_item = _item(payload, model)
    processor_item = _item(payload, processor)

    assert model_item["type"] == "legacy"
    assert processor_item["type"] == "legacy"
    assert model_item["removal"]["allowed"] is True
    assert processor_item["removal"]["allowed"] is True
    assert "only GenStudio-qualified transcription model" in model_item["detail"]


def test_unknown_cache_is_visible_instead_of_silently_ignored(tmp_path, monkeypatch) -> None:
    repo = "someone/new-voice-model"
    _cached_repo(tmp_path, monkeypatch, repo)

    item = _item(model_storage.inventory(), repo)

    assert item["type"] == "unknown"
    assert item["family"] == "other"
    assert item["removal"]["allowed"] is True


def test_model_storage_api_returns_inventory(monkeypatch) -> None:
    payload = {"schema_version": 1, "groups": [], "summary": {"packages": 0}}
    monkeypatch.setattr(backend_main.model_storage, "inventory", lambda: payload)
    client = TestClient(
        backend_main.app,
        headers={"X-Studio-Token": backend_main.FLEET_TOKEN},
    )

    response = client.get("/api/model-storage")

    assert response.status_code == 200
    assert response.json() == payload


def test_model_storage_api_blocks_cleanup_during_generation(monkeypatch) -> None:
    monkeypatch.setattr(backend_main.manager, "active_for_repo", lambda _repo: None)
    monkeypatch.setattr(backend_main.gen_manager, "has_active_jobs", lambda: True)
    monkeypatch.setattr(backend_main.stt_manager, "is_active", lambda: False)
    client = TestClient(
        backend_main.app,
        headers={"X-Studio-Token": backend_main.FLEET_TOKEN},
    )

    response = client.delete("/api/model-storage/someone/model")

    assert response.status_code == 409
    assert "Wait for voice generation" in response.json()["detail"]
