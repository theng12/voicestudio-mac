"""
HF cache inspection.

Pure-ish functions that look at the on-disk Hugging Face cache and answer:
- where is HF_HOME for this server?
- is repo X fully cached, partially cached, or absent?
- what's the on-disk size of repo X?
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


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


def has_weight_files(repo: str) -> bool:
    """True if any snapshot under this repo contains at least one file with
    a recognized weight extension. Walks subdirectories because diffusers
    repos keep weights inside component dirs (transformer/, vae/, etc.) and
    huge models shard weights across multiple files."""
    snaps = repo_cache_dir(repo) / "snapshots"
    if not snaps.exists():
        return False
    try:
        for snap in snaps.iterdir():
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


def cache_state(repo: str) -> str:
    """
    Returns one of: 'absent', 'partial', 'cached'.
    'partial' means there are .incomplete blobs, a started but unfinished
    snapshot, or a snapshot that has no actual weight files (the gated-repo
    partial-download failure mode — see has_weight_files()).
    """
    if not repo_cache_dir(repo).exists():
        return "absent"
    if has_incomplete(repo):
        return "partial"
    if has_any_snapshot(repo):
        # A snapshot exists, but it must contain real model weights — not
        # just LICENSE.md / README.md / .gitattributes — to count as cached.
        return "cached" if has_weight_files(repo) else "partial"
    return "partial"


def disk_bytes(repo: str) -> int:
    """Total bytes used by all real blobs of this repo (excludes .incomplete)."""
    blobs = repo_cache_dir(repo) / "blobs"
    if not blobs.exists():
        return 0
    total = 0
    try:
        for entry in blobs.iterdir():
            if entry.name.endswith(".incomplete"):
                continue
            try:
                total += entry.stat().st_size
            except (FileNotFoundError, PermissionError):
                continue
    except FileNotFoundError:
        return 0
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
    state = cache_state(repo)
    return {
        "repo": repo,
        "state": state,
        "path": str(repo_cache_dir(repo)) if state != "absent" else None,
        "bytes_complete": disk_bytes(repo),
        "bytes_incomplete": incomplete_bytes(repo),
    }


def ensure_hub_dir() -> Path:
    d = hub_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d
