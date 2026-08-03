"""
HF cache inspection.

Pure-ish functions that look at the on-disk Hugging Face cache and answer:
- where is HF_HOME for this server?
- is repo X fully cached, partially cached, or absent?
- what's the on-disk size of repo X?
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


_IMMUTABLE_REVISION = re.compile(r"^[0-9a-fA-F]{40,64}$")


def hf_home() -> Path:
    """
    Resolve HF_HOME the same way huggingface_hub does, but as an absolute path.
    Defaults match the library's defaults so we agree with `hf download`.
    """
    raw = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if raw:
        return Path(raw).expanduser().resolve()
    # huggingface_hub default
    return (Path.home() / ".cache" / "huggingface").resolve()


def hub_dir() -> Path:
    return hf_home() / "hub"


def repo_cache_dir(repo: str) -> Path:
    """HF cache folder name for a repo, e.g. 'org/name' -> 'models--org--name'."""
    safe = "models--" + repo.replace("/", "--")
    return hub_dir() / safe


def snapshot_revision(repo: str) -> str | None:
    """Return the immutable revision of the locally selected HF snapshot."""
    repo_dir = repo_cache_dir(repo)
    main_ref = repo_dir / "refs" / "main"
    try:
        revision = main_ref.read_text().strip()
    except (FileNotFoundError, OSError):
        revision = ""
    if (
        _IMMUTABLE_REVISION.fullmatch(revision)
        and (repo_dir / "snapshots" / revision).is_dir()
    ):
        return revision.lower()
    snapshots = repo_dir / "snapshots"
    try:
        candidates = sorted(
            path.name for path in snapshots.iterdir()
            if path.is_dir() and _IMMUTABLE_REVISION.fullmatch(path.name)
        )
    except (FileNotFoundError, OSError):
        return None
    return candidates[0] if len(candidates) == 1 else None


def _unresolved_incomplete_entries(repo: str) -> list[Path]:
    """Return partial blobs that do not already have a completed sibling.

    Hugging Face resumes downloads as ``<blob>.incomplete``. If an interrupted
    downloader leaves that file behind after another attempt completes the
    same ``<blob>``, the partial is stale and must not make a usable snapshot
    look incomplete.
    """
    blobs = repo_cache_dir(repo) / "blobs"
    if not blobs.exists():
        return []
    unresolved: list[Path] = []
    try:
        for entry in blobs.iterdir():
            if not entry.name.endswith(".incomplete"):
                continue
            # A cancelled child downloader can leave a zero-byte placeholder
            # with a transport-specific suffix. It contains no resumable
            # state; keeping it would make an otherwise usable snapshot look
            # partial forever and cause every reconciliation to queue a
            # duplicate download. Only non-empty partial blobs are meaningful.
            try:
                if entry.stat().st_size == 0:
                    continue
            except (FileNotFoundError, PermissionError):
                continue
            completed = entry.with_name(entry.name.removesuffix(".incomplete"))
            if not completed.exists():
                unresolved.append(entry)
    except FileNotFoundError:
        return []
    return unresolved


def has_incomplete(repo: str) -> bool:
    return bool(_unresolved_incomplete_entries(repo))


def has_any_snapshot(repo: str) -> bool:
    snaps = repo_cache_dir(repo) / "snapshots"
    if not snaps.exists():
        return False
    try:
        return any(snaps.iterdir())
    except FileNotFoundError:
        return False


# Recognized model-weight extensions. A snapshot that contains only README /
# LICENSE / .gitattributes is NOT actually usable, so cache_state() now
# requires at least one file with one of these extensions before reporting
# "cached". This catches the silent-partial-download failure mode for gated
# repos where the user hasn't accepted the license / provided a token: HF
# downloads the public LICENSE.md + README.md (which create a snapshot dir
# and make has_any_snapshot() return True) but skips the actual weights.
_WEIGHT_EXTENSIONS = (
    ".safetensors", ".bin", ".ckpt", ".gguf",
    ".pt", ".pth", ".npz", ".mlpackage",
)


def has_weight_files(repo: str, *, revision: str | None = None) -> bool:
    """True when the requested snapshot contains at least one weight file.

    With no ``revision`` this retains the storage-inventory behavior of
    inspecting every snapshot. Runtime cache checks pass the selected immutable
    revision so a stray ``snapshots/main`` folder cannot make an unrelated or
    metadata-only immutable snapshot look executable.
    """
    snaps = repo_cache_dir(repo) / "snapshots"
    if not snaps.exists():
        return False
    if revision is not None:
        if not _IMMUTABLE_REVISION.fullmatch(revision):
            return False
        candidates = (snaps / revision,)
    else:
        try:
            candidates = tuple(snaps.iterdir())
        except (FileNotFoundError, PermissionError):
            return False
    try:
        for snap in candidates:
            if not snap.is_dir():
                continue
            for path in snap.rglob("*"):
                name = path.name
                if name.endswith(".incomplete"):
                    continue
                lower = name.lower()
                if any(lower.endswith(ext) for ext in _WEIGHT_EXTENSIONS):
                    return True
    except (FileNotFoundError, PermissionError):
        return False
    return False


def _cache_state_for_revision(repo: str, revision: str | None) -> str:
    """Evaluate a cache against one already-resolved immutable revision."""
    if not repo_cache_dir(repo).exists():
        return "absent"
    if has_incomplete(repo):
        return "partial"
    if not has_any_snapshot(repo):
        return "partial"
    # A mutable/synthetic layout can still contain all model bytes, but it
    # cannot prove which checkpoint produced them. Keep every byte in place and
    # let snapshot_download reconcile it into an official immutable snapshot.
    if revision is None:
        return "partial"
    return "cached" if has_weight_files(repo, revision=revision) else "partial"


def cache_state(repo: str) -> str:
    """Returns one of: 'absent', 'partial', 'cached'.

    'partial' means there are .incomplete blobs, a started but unfinished
    snapshot, or a snapshot that has no actual weight files (the gated-repo
    partial-download failure mode — see has_weight_files()).
    A model is cached only when its selected snapshot has both an immutable
    revision and real weight files. Mutable names such as ``main`` remain
    resumable partial state rather than routable runtime evidence.
    """
    return _cache_state_for_revision(repo, snapshot_revision(repo))


def disk_bytes(repo: str) -> int:
    """Total bytes this repo occupies on disk (excludes .incomplete).

    Counts blob storage *and* snapshot files that are real files rather than
    links into ``blobs/``. A cache populated by direct file download instead of
    ``snapshot_download`` leaves ``blobs/`` empty and keeps real files in the
    snapshot; such a repo previously reported zero bytes while fully cached,
    which understated its footprint to the catalog and to Studio Hub's
    memory governor. Entries are de-duplicated by inode, so a snapshot symlink
    or hardlink pointing at a blob is never counted twice.
    """
    root = repo_cache_dir(repo)
    if not root.exists():
        return 0
    total = 0
    seen: set[tuple[int, int]] = set()
    for base in (root / "blobs", root / "snapshots"):
        if not base.exists():
            continue
        try:
            for entry in base.rglob("*"):
                if entry.name.endswith(".incomplete"):
                    continue
                try:
                    if not entry.is_file():
                        continue
                    info = entry.stat()
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                key = (info.st_dev, info.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                total += info.st_size
        except (FileNotFoundError, PermissionError, OSError):
            continue
    return total


def incomplete_bytes(repo: str) -> int:
    """Total bytes still needed by unresolved partial blobs."""
    total = 0
    for entry in _unresolved_incomplete_entries(repo):
        try:
            total += entry.stat().st_size
        except (FileNotFoundError, PermissionError):
            continue
    return total


def prune_stale_incomplete(
    repo: str, *, complete_snapshot_verified: bool = False
) -> dict[str, int]:
    """Delete stale partial blobs without discarding resumable downloads.

    Exact completed siblings are always safe to remove. Other partials are
    removed only after the caller independently verifies that the completed
    blob bytes equal the repository's current official manifest.
    """
    blobs = repo_cache_dir(repo) / "blobs"
    removed_files = 0
    removed_bytes = 0
    if not blobs.exists():
        return {"removed_files": 0, "removed_bytes": 0}
    try:
        entries = list(blobs.iterdir())
    except FileNotFoundError:
        return {"removed_files": 0, "removed_bytes": 0}
    for entry in entries:
        if not entry.name.endswith(".incomplete"):
            continue
        completed = entry.with_name(entry.name.removesuffix(".incomplete"))
        if not completed.exists() and not complete_snapshot_verified:
            try:
                # Empty placeholders are safe to remove: unlike a non-empty
                # HF partial they cannot contribute resumable bytes.
                if entry.stat().st_size != 0:
                    continue
            except (FileNotFoundError, PermissionError):
                continue
        try:
            size = entry.stat().st_size
            entry.unlink()
        except (FileNotFoundError, PermissionError):
            continue
        removed_files += 1
        removed_bytes += size
    return {"removed_files": removed_files, "removed_bytes": removed_bytes}


def status_snapshot(repo: str) -> dict:
    revision = snapshot_revision(repo)
    state = _cache_state_for_revision(repo, revision)
    return {
        "repo": repo,
        "state": state,
        # Advertise the exact cached Hugging Face snapshot before dispatch so
        # Studio Hub can match a GenStudio-pinned request to the right worker.
        # Mutable refs such as ``main`` are never returned here.
        "snapshot_revision": revision,
        "path": str(repo_cache_dir(repo)) if state != "absent" else None,
        "bytes_complete": disk_bytes(repo),
        "bytes_incomplete": incomplete_bytes(repo),
    }


def ensure_hub_dir() -> Path:
    d = hub_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d
