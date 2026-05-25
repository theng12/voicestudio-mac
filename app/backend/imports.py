"""
Import existing HF-cache-style model folders into our HF_HOME.

Two transfer modes:

- **link** (default): create a symlink under HF_HOME/hub pointing at the
  source. Instant, zero copy — but breaks if the source is later deleted.
  Best when you want to keep the source launcher installed alongside.

- **move**: physically relocate the folder into HF_HOME/hub via
  `shutil.move`. Same filesystem = instant inode rename, cross-filesystem =
  copy+delete. After a successful move the source is gone, so the
  destination is independent and you can safely uninstall the source app.
  Best for the "I'm migrating off the old launcher" case.

Two source-folder formats are accepted:

- **HF cache layout**: `models--<owner>--<repo>/{blobs,snapshots,refs}/...`
  — the format huggingface_hub produces by default. Detected by folder name
  pattern + presence of blobs/ or snapshots/.

- **Flat layout**: a folder whose direct children include `config.json`
  AND at least one `*.safetensors` file. Produced by
  `snapshot_download(local_dir=...)` which bypasses HF cache entirely.
  Common in older launchers (eg. the Qwen3-TTS launcher). We reconstruct
  an HF-cache snapshot pointing at the flat-folder files via symlinks.

The "Scan candidates" flow looks at folders listed in
VOICESTUDIO_EXTRA_MODEL_DIRS (colon-separated). For each entry we walk one
or two levels deep looking for both folder formats.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import cache, catalog


@dataclass
class ImportCandidate:
    source_path: str
    repo: str
    in_catalog: bool
    layout: str = "hf-cache"     # "hf-cache" | "flat"

    def serialize(self) -> dict:
        return {
            "source_path": self.source_path,
            "repo": self.repo,
            "in_catalog": self.in_catalog,
            "layout": self.layout,
        }


def _parse_hf_folder_name(name: str) -> Optional[str]:
    """'models--black-forest-labs--FLUX.1-schnell' -> 'black-forest-labs/FLUX.1-schnell'."""
    if not name.startswith("models--"):
        return None
    rest = name[len("models--"):]
    # Repo names can contain '-' but the path separator is '--', which we
    # need to split on conservatively. HF uses the first '--' as the org
    # boundary; the rest is the repo path (which itself may contain '--').
    parts = rest.split("--", 1)
    if len(parts) != 2:
        return None
    org, repo = parts
    if not org or not repo:
        return None
    return f"{org}/{repo}"


def _is_valid_hf_folder(path: Path) -> bool:
    """A folder counts as HF-cache-formatted if it has either blobs/ or snapshots/."""
    return path.is_dir() and ((path / "blobs").exists() or (path / "snapshots").exists())


def _is_flat_model_folder(path: Path) -> bool:
    """A folder is 'flat-format' if it directly contains a config.json plus
    at least one .safetensors (or sharded model-*.safetensors) file. Produced
    by huggingface_hub.snapshot_download(local_dir=...) which copies files
    directly without the blobs/snapshots/refs HF cache layout."""
    if not path.is_dir():
        return False
    if not (path / "config.json").exists():
        return False
    for child in path.iterdir():
        n = child.name.lower()
        if n.endswith(".safetensors") or n.endswith(".bin") or n.endswith(".pth") or n.endswith(".pt"):
            return True
    return False


def _guess_repo_for_flat(folder_name: str) -> Optional[str]:
    """Given a flat folder name like 'Qwen3-TTS-12Hz-0.6B-Base-8bit', try to
    match it against a catalog entry. We require the catalog entry's repo to
    end with the folder name to avoid false positives (e.g. matching every
    'Base' model that's ever existed)."""
    suffix = folder_name.lower()
    matches = [m.repo for m in catalog.CATALOG if m.repo.rsplit("/", 1)[-1].lower() == suffix]
    if len(matches) == 1:
        return matches[0]
    return None


def extra_dirs() -> list[Path]:
    raw = os.environ.get("VOICESTUDIO_EXTRA_MODEL_DIRS", "").strip()
    if not raw:
        return []
    out: list[Path] = []
    for token in raw.split(":"):
        token = token.strip()
        if not token:
            continue
        p = Path(token).expanduser()
        if p.exists():
            out.append(p.resolve())
    return out


def scan_for_candidates() -> list[ImportCandidate]:
    """
    Walk the configured extra dirs looking for both:
      1. HF-cache-style 'models--<owner>--<repo>/' folders (with blobs/snapshots)
      2. Flat-layout folders (config.json + .safetensors directly inside)

    For each extra dir we check:
      - <root>/                            ← look for either format
      - <root>/hub/                        ← HF cache, common pattern
      - <root>/../../app/models/           ← flat layout, common in launchers
        that download via snapshot_download(local_dir=...)
    """
    our_hub = cache.hub_dir().resolve()
    seen: set[str] = set()
    out: list[ImportCandidate] = []
    for root in extra_dirs():
        # Build the list of folders we should inspect.
        candidates: list[Path] = []
        try:
            for child in root.iterdir():
                candidates.append(child)
                # Walk into the 'hub' subfolder (HF cache convention).
                if child.is_dir() and child.name == "hub":
                    try:
                        candidates.extend(child.iterdir())
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            continue
        # Also look for sibling app/models/ directories (where launchers using
        # snapshot_download(local_dir=...) put their weights). The path layout is:
        #   <launcher_root>/cache/HF_HOME/hub   ← root
        #   <launcher_root>/app/models          ← sibling we want
        # Three .parents back from `hub` lands at <launcher_root>.
        for app_models_path in (
            root.parent.parent.parent / "app" / "models",   # <launcher>/cache/HF_HOME/hub → <launcher>/app/models
            root.parent.parent / "app" / "models",          # fallback: <launcher>/HF_HOME/hub layout
            root.parent / "models",                          # fallback: weights right under hub's parent
        ):
            if app_models_path.is_dir():
                try:
                    candidates.extend(app_models_path.iterdir())
                except FileNotFoundError:
                    pass
                break   # first hit wins

        for c in candidates:
            if not c.is_dir():
                continue

            # --- Format 1: HF cache layout ---
            repo_hf = _parse_hf_folder_name(c.name)
            if repo_hf is not None and _is_valid_hf_folder(c):
                if c.resolve() == (our_hub / c.name).resolve():
                    continue   # already at home
                if repo_hf in seen:
                    continue
                seen.add(repo_hf)
                out.append(ImportCandidate(
                    source_path=str(c.resolve()),
                    repo=repo_hf,
                    in_catalog=catalog.get_model(repo_hf) is not None,
                    layout="hf-cache",
                ))
                continue

            # --- Format 2: Flat layout ---
            if _is_flat_model_folder(c):
                repo_flat = _guess_repo_for_flat(c.name)
                if repo_flat is None:
                    # We can't auto-detect the HF repo this maps to. Skip
                    # silently; the user can use the manual import path field
                    # if they know the repo.
                    continue
                if repo_flat in seen:
                    continue
                seen.add(repo_flat)
                out.append(ImportCandidate(
                    source_path=str(c.resolve()),
                    repo=repo_flat,
                    in_catalog=catalog.get_model(repo_flat) is not None,
                    layout="flat",
                ))
    return out


def import_path(source_path: str, repo: Optional[str] = None, mode: str = "link") -> dict:
    """
    Bring an existing HF cache folder into our HF_HOME/hub.

    `mode`:
      - "link": symlink (the original stays put, our hub references it)
      - "move": physically relocate the folder into our hub

    Returns a dict describing what happened.
    """
    if mode not in ("link", "move"):
        return {"ok": False, "error": f"Unknown mode: {mode}"}

    src = Path(source_path).expanduser().resolve()
    if not src.exists():
        return {"ok": False, "error": f"Path does not exist: {src}"}

    # Detect which layout we're dealing with — HF cache vs flat.
    is_hf = _is_valid_hf_folder(src)
    is_flat = _is_flat_model_folder(src) if not is_hf else False
    if not is_hf and not is_flat:
        return {
            "ok": False,
            "error": (
                f"Not a recognized model folder: {src}. Expected either an HF cache "
                "layout (blobs/ + snapshots/) or a flat layout (config.json + .safetensors)."
            ),
        }

    if repo is None:
        if is_hf:
            repo = _parse_hf_folder_name(src.name)
        else:
            repo = _guess_repo_for_flat(src.name)
        if repo is None:
            return {
                "ok": False,
                "error": (
                    f"Could not infer repo from folder name '{src.name}'. "
                    "Pass the repo explicitly (e.g. 'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit')."
                ),
            }

    cache.ensure_hub_dir()
    target = cache.repo_cache_dir(repo)

    # Flat layout → reconstruct HF cache structure pointing at the flat files.
    if is_flat:
        return _import_flat_folder(src, target, repo, mode)

    # If a symlink to this very source already exists, treat as a no-op for link
    # mode, or fall through to upgrade-to-move (unlink + move) for move mode.
    if target.exists():
        if target.is_symlink() and target.resolve() == src:
            if mode == "link":
                return {"ok": True, "mode": "link", "already": True, "repo": repo,
                        "target": str(target)}
            # mode == "move" and target is a symlink pointing at our source:
            # unlink the symlink, then proceed to physically move the source
            # into the freed target path below.
            try:
                target.unlink()
            except OSError as e:
                return {"ok": False, "error": f"could not remove stale symlink: {e}",
                        "repo": repo}
        else:
            return {
                "ok": False,
                "error": (
                    f"Target already exists at {target}. Remove it first if you want to "
                    f"re-{mode}."
                ),
                "repo": repo,
            }

    if mode == "link":
        try:
            target.symlink_to(src, target_is_directory=True)
        except OSError as e:
            return {"ok": False, "error": f"symlink failed: {e}", "repo": repo}
        return {"ok": True, "mode": "link", "repo": repo,
                "target": str(target), "source": str(src)}

    # mode == "move": shutil.move handles both same-fs rename (instant) and
    # cross-fs copy+delete fallback transparently.
    try:
        shutil.move(str(src), str(target))
    except OSError as e:
        return {"ok": False, "error": f"move failed: {e}", "repo": repo}
    return {"ok": True, "mode": "move", "repo": repo,
            "target": str(target), "source_was": str(src)}


# Sentinel revision for synthesized snapshots — chosen so it's obviously not a
# real git SHA. transformers' from_pretrained() tolerates this since it just
# resolves snapshots/<rev>/<file> and reads what's there.
_SYNTH_REV = "main"


def _import_flat_folder(src: Path, target: Path, repo: str, mode: str) -> dict:
    """
    Reconstruct an HF cache layout pointing at a flat-format model folder.

    HF cache structure created:
        target/
          refs/main                 ← text file containing the revision
          snapshots/main/           ← directory of per-file links to src/
            config.json -> src/config.json
            model.safetensors -> src/model.safetensors
            ...
          blobs/                    ← empty (we skip the blob hash layer; the
                                      snapshots/ entries point straight at the
                                      flat-folder files via symlinks)

    `mode`:
      - "link": each file in the snapshot is a symlink back to the flat folder.
        Fast, zero copy. Breaks if the flat folder is deleted.
      - "move": the flat folder is moved into snapshots/main/ as a real
        directory. Source folder is gone after.
    """
    if target.exists():
        return {
            "ok": False,
            "error": (
                f"Target already exists at {target}. Remove it first if you want to re-import."
            ),
            "repo": repo,
        }

    try:
        snapshot_dir = target / "snapshots" / _SYNTH_REV
        refs_dir = target / "refs"
        blobs_dir = target / "blobs"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        refs_dir.mkdir(parents=True, exist_ok=True)
        blobs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "main").write_text(_SYNTH_REV)

        if mode == "link":
            # Symlink each visible file from the flat folder into the snapshot.
            for child in src.iterdir():
                if child.name.startswith("."):
                    continue
                # Skip subdirectories that are model-internal caches (e.g. '.cache').
                # The MLX folders we've seen are flat (no real subdirs), but be safe.
                dst = snapshot_dir / child.name
                if child.is_dir():
                    dst.symlink_to(child.resolve(), target_is_directory=True)
                else:
                    dst.symlink_to(child.resolve())
            return {
                "ok": True,
                "mode": "link",
                "layout": "flat",
                "repo": repo,
                "target": str(target),
                "source": str(src),
            }
        elif mode == "move":
            # Move the files inside src into the snapshot. We move file-by-file
            # rather than `mv src snapshots/main` because some flat folders sit
            # alongside other data we shouldn't drag in.
            for child in src.iterdir():
                if child.name.startswith("."):
                    continue
                dst = snapshot_dir / child.name
                shutil.move(str(child), str(dst))
            # If the src folder is now empty, remove it as a courtesy.
            try:
                src.rmdir()
            except OSError:
                pass
            return {
                "ok": True,
                "mode": "move",
                "layout": "flat",
                "repo": repo,
                "target": str(target),
                "source_was": str(src),
            }
        else:
            return {"ok": False, "error": f"Unknown mode for flat import: {mode}"}
    except OSError as e:
        # Roll back the half-built target if anything failed.
        try:
            shutil.rmtree(target)
        except OSError:
            pass
        return {"ok": False, "error": f"flat import failed: {e}", "repo": repo}
