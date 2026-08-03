import os
from pathlib import Path

import pytest

from backend import cache


REPO = "example/model"


def _repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    root = cache.repo_cache_dir(REPO)
    (root / "blobs").mkdir(parents=True)
    snapshot = root / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"weights")
    return root


def test_status_snapshot_advertises_only_the_immutable_cached_revision(
    tmp_path: Path, monkeypatch
) -> None:
    _repo(tmp_path, monkeypatch)

    status = cache.status_snapshot(REPO)

    assert status["state"] == "cached"
    assert status["snapshot_revision"] == "a" * 40


def test_snapshot_revision_ignores_a_mutable_main_snapshot_folder(
    tmp_path: Path, monkeypatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "refs").mkdir()
    (root / "refs" / "main").write_text("main")
    (root / "snapshots" / "main").mkdir()

    assert cache.snapshot_revision(REPO) == "a" * 40


def test_unversioned_weight_snapshot_is_preserved_but_not_advertised_cached(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    root = cache.repo_cache_dir(REPO)
    snapshot = root / "snapshots" / "main"
    snapshot.mkdir(parents=True)
    (root / "refs").mkdir()
    (root / "refs" / "main").write_text("main")
    weights = snapshot / "model.safetensors"
    weights.write_bytes(b"existing-valid-bytes")

    status = cache.status_snapshot(REPO)

    assert status["state"] == "partial"
    assert status["snapshot_revision"] is None
    assert status["bytes_complete"] == len(b"existing-valid-bytes")
    assert weights.read_bytes() == b"existing-valid-bytes"


def test_selected_immutable_snapshot_must_itself_contain_weights(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    root = cache.repo_cache_dir(REPO)
    immutable = root / "snapshots" / ("a" * 40)
    immutable.mkdir(parents=True)
    (immutable / "README.md").write_text("metadata only")
    mutable = root / "snapshots" / "main"
    mutable.mkdir()
    (mutable / "model.safetensors").write_bytes(b"unversioned weights")
    (root / "refs").mkdir()
    (root / "refs" / "main").write_text("a" * 40)

    status = cache.status_snapshot(REPO)

    assert status["snapshot_revision"] == "a" * 40
    assert status["state"] == "partial"


def test_disk_bytes_counts_real_snapshot_files_without_blobs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    snapshot = cache.repo_cache_dir(REPO) / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"snapshot-only")

    assert cache.disk_bytes(REPO) == len(b"snapshot-only")


def test_disk_bytes_counts_blob_storage_without_a_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    blobs = cache.repo_cache_dir(REPO) / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "blob-hash").write_bytes(b"blob-only")

    assert cache.disk_bytes(REPO) == len(b"blob-only")


def test_disk_bytes_deduplicates_snapshot_symlink_to_blob(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path, monkeypatch)
    blob = root / "blobs" / "blob-hash"
    blob.write_bytes(b"shared-data")
    snapshot_file = root / "snapshots" / ("a" * 40) / "shared.safetensors"
    try:
        snapshot_file.symlink_to(blob)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert cache.disk_bytes(REPO) == len(b"weights") + len(b"shared-data")


def test_disk_bytes_deduplicates_snapshot_hardlink_to_blob(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path, monkeypatch)
    blob = root / "blobs" / "blob-hash"
    blob.write_bytes(b"shared-data")
    snapshot_file = root / "snapshots" / ("a" * 40) / "shared.safetensors"
    os.link(blob, snapshot_file)

    assert cache.disk_bytes(REPO) == len(b"weights") + len(b"shared-data")


def test_disk_bytes_excludes_incomplete_entries(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "blobs" / "blob-hash").write_bytes(b"complete")
    (root / "blobs" / "blob-hash.incomplete").write_bytes(b"partial")
    snapshot_partial = root / "snapshots" / ("a" * 40) / "other.incomplete"
    snapshot_partial.write_bytes(b"also-partial")

    assert cache.disk_bytes(REPO) == len(b"weights") + len(b"complete")


def test_snapshot_disk_bytes_counts_only_the_exact_immutable_snapshot(
    tmp_path, monkeypatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "snapshots" / "main").mkdir()
    (root / "snapshots" / "main" / "model.safetensors").write_bytes(
        b"unversioned-standalone"
    )
    other = root / "snapshots" / ("b" * 40)
    other.mkdir()
    (other / "model.safetensors").write_bytes(b"other-revision")

    assert cache.snapshot_disk_bytes(REPO, "a" * 40) == len(b"weights")
    assert cache.snapshot_disk_bytes(REPO, "b" * 40) == len(b"other-revision")
    assert cache.snapshot_disk_bytes(REPO, "main") == 0
    assert cache.snapshot_disk_bytes(REPO, None) == 0


def test_stale_duplicate_incomplete_does_not_block_cached_model(
    tmp_path: Path, monkeypatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "blobs" / "blob-hash").write_bytes(b"complete")
    (root / "blobs" / "blob-hash.incomplete").write_bytes(b"stale partial")

    assert cache.cache_state(REPO) == "cached"
    assert cache.incomplete_bytes(REPO) == 0

    removed = cache.prune_stale_incomplete(REPO)

    assert removed == {"removed_files": 1, "removed_bytes": 13}
    assert not (root / "blobs" / "blob-hash.incomplete").exists()
    assert (root / "blobs" / "blob-hash").read_bytes() == b"complete"


def test_unresolved_incomplete_remains_partial_and_is_not_pruned(
    tmp_path: Path, monkeypatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    partial = root / "blobs" / "missing-blob.incomplete"
    partial.write_bytes(b"needed")

    assert cache.cache_state(REPO) == "partial"
    assert cache.incomplete_bytes(REPO) == 6
    assert cache.prune_stale_incomplete(REPO) == {
        "removed_files": 0,
        "removed_bytes": 0,
    }
    assert partial.read_bytes() == b"needed"


def test_zero_byte_incomplete_placeholder_is_safe_to_prune(
    tmp_path: Path, monkeypatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    placeholder = root / "blobs" / "cancelled-at-start.incomplete"
    placeholder.write_bytes(b"")

    assert cache.cache_state(REPO) == "cached"
    assert cache.incomplete_bytes(REPO) == 0
    assert cache.prune_stale_incomplete(REPO) == {
        "removed_files": 1,
        "removed_bytes": 0,
    }
    assert not placeholder.exists()


def test_orphan_incomplete_is_pruned_only_after_complete_snapshot_verification(
    tmp_path: Path, monkeypatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    orphan = root / "blobs" / "old-revision.incomplete"
    orphan.write_bytes(b"obsolete")

    assert cache.prune_stale_incomplete(REPO) == {
        "removed_files": 0,
        "removed_bytes": 0,
    }
    assert orphan.exists()

    assert cache.prune_stale_incomplete(
        REPO, complete_snapshot_verified=True
    ) == {"removed_files": 1, "removed_bytes": 8}
    assert not orphan.exists()
