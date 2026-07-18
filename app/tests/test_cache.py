from pathlib import Path

from backend import cache


REPO = "example/model"


def _repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    root = cache.repo_cache_dir(REPO)
    (root / "blobs").mkdir(parents=True)
    snapshot = root / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"weights")
    return root


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
