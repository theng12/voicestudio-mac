#!/usr/bin/env python3
"""Build a browsable by-family VIEW of the Hugging Face cache, using symlinks.

Why a view instead of moving folders:
  huggingface_hub resolves a model by looking for `<HF_HOME>/hub/models--<org>--<name>`
  with its `blobs/ snapshots/ refs/` layout. That path is a hard convention — move
  or rename those folders into `<family>/<model>/` and mlx-audio stops finding
  anything. So the real cache is left exactly where it is, and this script builds
  a parallel tree of symlinks you can browse in Finder:

      cache/HF_HOME/by-family/
        Echo-TTS (MLX)/
          echo-tts-base            -> ../../hub/models--mlx-community--echo-tts-base
          [codec] fish-s1-dac-min  -> ../../hub/models--jordand--fish-s1-dac-min
        Chatterbox (MLX)/
          chatterbox-4bit          -> ...

Costs no disk (symlinks), breaks nothing, and can be regenerated any time —
it is derived state, safe to delete.

Family/companion mapping is read from the RUNNING server's /api/catalog rather
than hardcoded, so it can never drift from catalog.py the way a copied table does.

Usage:
    python tools/family_view.py                 # build/refresh the view
    python tools/family_view.py --clean         # remove the view only
    python tools/family_view.py --host 1.2.3.4  # point at another Studio
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HUB = REPO_ROOT / "cache" / "HF_HOME" / "hub"
VIEW = REPO_ROOT / "cache" / "HF_HOME" / "by-family"

# Speech-to-text models have no catalog "family"; group them under one heading
# so they stop looking like stray TTS entries.
STT_FAMILY = "Whisper (speech-to-text)"


def api(host: str, path: str) -> dict:
    with urllib.request.urlopen(f"http://{host}{path}", timeout=15) as r:
        return json.loads(r.read())


def dirname_to_repo(dirname: str) -> str | None:
    if not dirname.startswith("models--"):
        return None
    parts = dirname.removeprefix("models--").split("--")
    # Org names can't contain "--"; the remainder is the model name, which can.
    return f"{parts[0]}/{'--'.join(parts[1:])}" if len(parts) >= 2 else None


def build_mapping(host: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """repo -> (family label, display name). Companions inherit their family."""
    mapping: dict[str, tuple[str, str]] = {}
    notes: list[str] = []

    catalog = api(host, "/api/catalog")
    families = catalog.get("families", {})
    fam_by_id = {}
    saw_companion_field = False
    for m in catalog.get("models", []):
        fam_label = families.get(m["family"], {}).get("label") or m["family"]
        fam_by_id[m["family"]] = fam_label
        mapping[m["repo"]] = (fam_label, m["repo"].split("/")[-1])
        # Codec / tokenizer repos the engine loads with this model.
        comps = (m.get("cache") or {}).get("companions")
        if comps is not None:
            saw_companion_field = True
        for c in comps or []:
            mapping.setdefault(
                c["repo"], (fam_label, f"[dep] {c['repo'].split('/')[-1]}")
            )

    if not saw_companion_field:
        # The running server predates the companions field (added 1.29.2), so
        # fall back to reading the family->companion table straight out of the
        # local checkout. Keeps the view correct on a server that hasn't been
        # Updated yet, instead of dumping every codec into "_not in catalog".
        try:
            import sys
            sys.path.insert(0, str(REPO_ROOT / "app"))
            from backend import catalog as local_catalog  # type: ignore
            for fam_id, comps in local_catalog.FAMILY_COMPANIONS.items():
                fam_label = fam_by_id.get(fam_id) or fam_id
                for c in comps:
                    mapping.setdefault(
                        c["repo"], (fam_label, f"[dep] {c['repo'].split('/')[-1]}")
                    )
            notes.append(
                "server predates the /api/catalog companions field — dependency "
                "mapping read from the local catalog.py instead (click Update to "
                "bring the server forward)"
            )
        except Exception as e:
            notes.append(f"could not read local companions ({type(e).__name__})")

    try:
        stt = api(host, "/api/transcribe/availability")
        for m in stt.get("models", []):
            mapping.setdefault(m["repo"], (STT_FAMILY, m["repo"].split("/")[-1]))
    except Exception as e:  # STT is optional; never fail the whole view for it
        notes.append(f"could not read STT models ({type(e).__name__}) — skipped")

    return mapping, notes


def clean() -> None:
    if VIEW.exists():
        shutil.rmtree(VIEW)
        print(f"removed {VIEW}")
    else:
        print("nothing to clean")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:47870")
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    if args.clean:
        clean()
        return

    if not HUB.is_dir():
        raise SystemExit(f"HF cache not found at {HUB}")

    mapping, notes = build_mapping(args.host)

    # Rebuild from scratch so renames/removals never leave dangling entries.
    if VIEW.exists():
        shutil.rmtree(VIEW)
    VIEW.mkdir(parents=True)

    linked, unmapped, by_family = 0, [], {}
    for src in sorted(HUB.iterdir()):
        if not src.is_dir() or src.name.startswith(".") or src.name == "_trash":
            continue
        repo = dirname_to_repo(src.name)
        if repo is None:
            continue
        if repo not in mapping:
            # Whisper helper repos (the upstream processor source, and the ASR
            # build mlx-audio auto-fetches when a reference clip has no
            # transcript) aren't catalog rows, but they clearly belong with STT.
            if "whisper" in repo.lower():
                mapping[repo] = (STT_FAMILY, f"[dep] {repo.split('/')[-1]}")
            else:
                unmapped.append(repo)
                continue

        fam_label, display = mapping[repo]
        fam_dir = VIEW / fam_label.replace("/", "-")
        fam_dir.mkdir(parents=True, exist_ok=True)
        link = fam_dir / display.replace("/", "-")
        # Relative target keeps the view valid if the whole tree is moved.
        link.symlink_to(os.path.relpath(src, fam_dir))
        by_family.setdefault(fam_label, []).append(display)
        linked += 1

    if unmapped:
        # Not an error: models downloaded outside the catalog, or ones that were
        # evaluated and rejected. Park them somewhere visible rather than hiding
        # them, so it's obvious they are candidates for reclaiming disk.
        other = VIEW / "_not in catalog"
        other.mkdir(parents=True, exist_ok=True)
        for repo in unmapped:
            src = HUB / ("models--" + repo.replace("/", "--"))
            (other / repo.split("/")[-1]).symlink_to(os.path.relpath(src, other))

    print(f"Family view: {VIEW}\n")
    for fam in sorted(by_family):
        print(f"  {fam}")
        for name in sorted(by_family[fam]):
            print(f"      {name}")
    if unmapped:
        print("\n  _not in catalog  (downloaded but not a catalog model)")
        for repo in sorted(unmapped):
            print(f"      {repo}")
    for n in notes:
        print(f"\nnote: {n}")
    print(f"\n{linked} linked, {len(unmapped)} unmapped. Real cache untouched.")


if __name__ == "__main__":
    main()
