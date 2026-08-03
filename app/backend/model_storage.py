"""Managed, dependency-aware view of Voice Studio's Hugging Face cache.

Hugging Face owns the physical ``models--owner--repo`` layout.  Voice Studio
does not move or rename those folders; this module adds the logical model-
family and dependency layer that the raw cache intentionally lacks.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import cache, catalog
from .transcription import WHISPER_MODELS, _PROCESSOR_BASE


NOTICE_NAME = "README-VOICE-STUDIO-CACHE.md"


# Repositories from older catalogue/runtime revisions that are no longer a
# selectable Voice Studio model.  Keeping this explicit makes cleanup reviewable
# instead of guessing from a folder name or its modification date.
LEGACY_REPOS: dict[str, dict[str, str]] = {
    "mlx-community/Kokoro-82M-4bit": {
        "family": "kokoro-mlx",
        "label": "Kokoro 82M 4-bit (older alternative)",
        "reason": "Superseded by the smaller full-quality Kokoro bf16 package.",
    },
    "prince-canuma/Kokoro-82M": {
        "family": "kokoro-mlx",
        "label": "Kokoro upstream voicepack cache",
        "reason": "Older adapters fetched voicepacks here; the current audited package contains all 54 voices.",
    },
    "mlx-community/OmniVoice-4bit": {
        "family": "omnivoice",
        "label": "OmniVoice 4-bit (unsupported conversion)",
        "reason": "Its row-wise quantization layout is incompatible with the pinned MLX engine.",
    },
    "mlx-community/OmniVoice-fp32": {
        "family": "omnivoice",
        "label": "OmniVoice fp32 (older alternative)",
        "reason": "Superseded by the compatible bfloat16 package and commonly left incomplete.",
    },
    "mlx-community/whisper-large-v3-turbo-asr-fp16": {
        "family": "whisper-stt",
        "label": "Whisper Large v3 Turbo ASR fp16 (older alternative)",
        "reason": "Not referenced by Voice Studio's current transcription catalogue.",
    },
    "mlx-community/VoxCPM2-8bit": {
        "family": "voxcpm-mlx",
        "label": "VoxCPM2 8-bit (older alternative)",
        "reason": "Not referenced by Voice Studio's current 4-bit and bf16 catalogue options.",
    },
    "mlx-community/whisper-tiny": {
        "family": "whisper-stt",
        "label": "Whisper Tiny (retired)",
        "reason": "Retired after fleet qualification found materially incomplete transcripts; Whisper Large v3 Turbo is the only GenStudio-qualified transcription model.",
    },
    "openai/whisper-tiny": {
        "family": "whisper-stt",
        "label": "Whisper Tiny tokenizer (retired dependency)",
        "reason": "No longer required because its Whisper Tiny parent model is retired.",
    },
}


class StorageConflict(RuntimeError):
    """Raised when removing a cache package would break an installed model."""


def _repo_from_cache_dir(path: Path) -> str | None:
    if not path.is_dir() or not path.name.startswith("models--"):
        return None
    parts = path.name.removeprefix("models--").split("--")
    if not parts or any(not part for part in parts):
        return None
    return "/".join(parts)


def _all_cached_repos() -> list[str]:
    try:
        paths = list(cache.hub_dir().iterdir())
    except (FileNotFoundError, PermissionError, OSError):
        return []
    repos = [_repo_from_cache_dir(path) for path in paths]
    return sorted(repo for repo in repos if repo)


def _tts_models() -> dict[str, object]:
    return {model.repo: model for model in catalog.CATALOG}


def _stt_models() -> dict[str, object]:
    return {model.repo: model for model in WHISPER_MODELS}


def _dependency_map() -> dict[str, dict]:
    """Return companion repo -> metadata + exact parent model repos."""
    result: dict[str, dict] = {}
    for model in catalog.CATALOG:
        for companion in catalog.companions_for(model.repo):
            item = result.setdefault(
                companion["repo"],
                {
                    "label": companion.get("label") or companion["repo"].split("/")[-1],
                    "family": model.family,
                    "used_by": [],
                },
            )
            item["used_by"].append(model.repo)
    for model in WHISPER_MODELS:
        processor = _PROCESSOR_BASE.get(model.repo)
        if not processor:
            continue
        item = result.setdefault(
            processor,
            {
                "label": "Whisper tokenizer and processor",
                "family": "whisper-stt",
                "used_by": [],
            },
        )
        item["used_by"].append(model.repo)
    for item in result.values():
        item["used_by"] = sorted(set(item["used_by"]))
    return result


def _family_metadata(family: str) -> tuple[str, str]:
    if family == "whisper-stt":
        return "Whisper transcription", "Speech-to-text models and their tokenizer assets."
    known = catalog.FAMILIES.get(family)
    if known:
        return known.label, known.summary
    return "Other cached assets", "Cache packages not recognised by the current Voice Studio catalogue."


def _installed(repo: str) -> bool:
    return cache.repo_cache_dir(repo).is_dir()


def _package_state(repo: str, *, dependency: bool) -> dict:
    snapshot = cache.status_snapshot(repo)
    # Tokenizer/config companions do not necessarily contain model weight
    # extensions.  A real snapshot with no unresolved transfer is complete for
    # dependency purposes even though cache.cache_state() correctly requires
    # weights for independently executable models.
    if dependency and snapshot["state"] == "partial":
        if (
            snapshot.get("snapshot_revision")
            and cache.has_any_snapshot(repo)
            and not cache.has_incomplete(repo)
        ):
            snapshot["state"] = "cached"
    snapshot["bytes_total"] = (
        int(snapshot.get("bytes_complete") or 0)
        + int(snapshot.get("bytes_incomplete") or 0)
    )
    return snapshot


def ensure_cache_notice() -> Path:
    """Place a human-readable warning beside the raw HF repository folders."""
    root = cache.ensure_hub_dir()
    path = root / NOTICE_NAME
    content = """# Voice Studio managed model cache

This directory is managed by Voice Studio and Hugging Face.

Folders named `models--owner--repository` may be executable models, alternate
precision versions, or required tokenizers/codecs used by another model. The
`blobs`, `refs`, and `snapshots` contents are part of Hugging Face's resumable
cache format. Do not rename, move, or remove individual files here.

Use Voice Studio → Models → Storage & dependencies to see which package owns
each folder and to remove only packages that are safe to delete.
"""
    try:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    except (PermissionError, OSError):
        # Inventory remains useful on a read-only cache mount.
        pass
    return path


def inventory() -> dict:
    """Build a live family/dependency tree over the existing cache in place."""
    notice = ensure_cache_notice()
    tts_models = _tts_models()
    stt_models = _stt_models()
    dependencies = _dependency_map()
    cached_repos = _all_cached_repos()
    installed_set = set(cached_repos)
    # Include a missing dependency as a visible child when one of its parent
    # models is installed. This makes a genuinely partial model package
    # explain itself instead of hiding the absent companion from the tree.
    visible_repos = set(cached_repos)
    for dependency_repo, dependency in dependencies.items():
        if any(parent in installed_set for parent in dependency["used_by"]):
            visible_repos.add(dependency_repo)
    items: list[dict] = []

    for repo in sorted(visible_repos):
        dependency = dependencies.get(repo)
        legacy = LEGACY_REPOS.get(repo)
        tts = tts_models.get(repo)
        stt = stt_models.get(repo)

        if legacy:
            family = legacy["family"]
            label = legacy["label"]
            item_type = "legacy"
            role = "Legacy / superseded"
            detail = legacy["reason"]
        elif dependency:
            family = dependency["family"]
            label = dependency["label"]
            item_type = "dependency"
            role = "Required dependency"
            detail = "Loaded automatically by its parent model; it is not a separate voice model."
        elif tts:
            family = tts.family
            label = tts.label
            item_type = "model"
            role = "Supported model option"
            detail = tts.best_for
        elif stt:
            family = "whisper-stt"
            label = stt.label
            item_type = "model"
            role = "Supported transcription model"
            detail = stt.note
        else:
            family = "other"
            label = repo.split("/")[-1]
            item_type = "unknown"
            role = "Unrecognised cache package"
            detail = "Not referenced by Voice Studio's current model or dependency catalogue."

        used_by = []
        if dependency:
            used_by = [parent for parent in dependency["used_by"] if parent in installed_set]
        removal_allowed = not used_by
        blocked_reason = ""
        if used_by:
            blocked_reason = "Required by installed model package" + ("s" if len(used_by) != 1 else "") + "."
        state = _package_state(repo, dependency=bool(dependency))
        items.append({
            "repo": repo,
            "label": label,
            "family": family,
            "type": item_type,
            "role": role,
            "detail": detail,
            "used_by": used_by,
            "present": repo in installed_set,
            "cache": state,
            "removal": {
                "allowed": removal_allowed,
                "blocked_reason": blocked_reason,
            },
        })

    type_rank = {"model": 0, "dependency": 1, "legacy": 2, "unknown": 3}
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["family"], []).append(item)
    groups = []
    for family, family_items in grouped.items():
        label, summary = _family_metadata(family)
        family_items.sort(key=lambda item: (type_rank.get(item["type"], 9), item["label"].lower()))
        groups.append({
            "id": family,
            "label": label,
            "summary": summary,
            "items": family_items,
            "bytes_total": sum(item["cache"]["bytes_total"] for item in family_items),
        })
    groups.sort(key=lambda group: (group["id"] == "other", group["label"].lower()))

    return {
        "schema_version": 1,
        "cache_root": str(cache.hub_dir()),
        "notice_path": str(notice),
        "summary": {
            "families": len(groups),
            "packages": len(items),
            "models": sum(item["type"] == "model" for item in items),
            "dependencies": sum(item["type"] == "dependency" for item in items),
            "legacy": sum(item["type"] == "legacy" for item in items),
            "unknown": sum(item["type"] == "unknown" for item in items),
            "bytes_total": sum(item["cache"]["bytes_total"] for item in items),
        },
        "groups": groups,
    }


def find_item(repo: str) -> dict | None:
    for group in inventory()["groups"]:
        for item in group["items"]:
            if item["repo"] == repo:
                return item
    return None


def remove_repo(repo: str) -> dict:
    """Remove one complete HF repository directory after dependency checks."""
    item = find_item(repo)
    if item is None:
        raise FileNotFoundError(repo)
    if not item["present"]:
        raise FileNotFoundError(repo)
    if not item["removal"]["allowed"]:
        raise StorageConflict(item["removal"]["blocked_reason"])
    target = cache.repo_cache_dir(repo)
    root = cache.hub_dir().resolve()
    try:
        resolved = target.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(repo) from exc
    if resolved.parent != root or not resolved.name.startswith("models--"):
        raise StorageConflict("Refusing to remove a path outside the managed Hugging Face cache.")
    freed = int(item["cache"]["bytes_total"])
    shutil.rmtree(resolved)
    return {"repo": repo, "removed": True, "freed_bytes": freed}
