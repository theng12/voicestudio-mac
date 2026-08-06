#!/usr/bin/env python3
"""Stage the Voice Studio model cache onto an external SSD, grouped by family,
and restore it onto another Mac.

    python tools/organize_models.py --plan       # show what would be copied
    python tools/organize_models.py              # copy to the SSD
    python tools/organize_models.py --restore    # rebuild a cache FROM the SSD

Two things this gets right that a naive copy does not:

1. **Symlinks are preserved.** The Hugging Face cache stores each real file once
   under `blobs/` and points at it from `snapshots/` with a symlink. A plain
   `shutil.copytree(src, dst)` dereferences those links and writes every file
   twice — measured on this cache, 52 GB became 98 GB. `symlinks=True` keeps the
   layout intact and the copy roughly half the size. (Only safe because the
   target is APFS; exFAT/FAT32 cannot store symlinks at all, and this script
   refuses to run there rather than silently doubling.)

2. **The HF folder name is preserved inside the family folder.** huggingface_hub
   resolves a model by the literal path `<HF_HOME>/hub/models--<org>--<name>`.
   Renaming to a friendly model name would make the copy unrestorable without a
   lookup table, so the layout is:

       voicestudio-models/
         Echo-TTS (MLX)/
           models--mlx-community--echo-tts-base/
           models--jordand--fish-s1-dac-min/        <- its codec, same folder
         Chatterbox (MLX)/
           models--mlx-community--chatterbox-4bit/
         MANIFEST.json

   Restoring is then just "move every models--* folder up into hub/".

Family and dependency grouping is read from the running server's /api/catalog,
so it cannot drift from catalog.py the way a hand-copied table does.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HUB = REPO_ROOT / "cache" / "HF_HOME" / "hub"
DEFAULT_DST = Path("/Volumes/UGREEN-1TB/voicestudio-models")
STT_FAMILY = "Whisper (speech-to-text)"
SKIP_DIRS = {"_trash", "CACHEDIR.TAG", "README-VOICE-STUDIO-CACHE.md"}


def api(host: str, path: str) -> dict:
    with urllib.request.urlopen(f"http://{host}{path}", timeout=15) as r:
        return json.loads(r.read())


def dirname_to_repo(dirname: str) -> str | None:
    if not dirname.startswith("models--"):
        return None
    parts = dirname.removeprefix("models--").split("--")
    return f"{parts[0]}/{'--'.join(parts[1:])}" if len(parts) >= 2 else None


def supports_symlinks(path: Path) -> bool:
    """Refuse to run on a filesystem that cannot store symlinks — copying there
    would silently double the size instead of failing loudly."""
    probe, target = path / ".symlink_probe", path / ".symlink_target"
    try:
        target.write_text("x")
        if probe.exists() or probe.is_symlink():
            probe.unlink()
        probe.symlink_to(target)
        return probe.is_symlink()
    except (OSError, NotImplementedError):
        return False
    finally:
        for p in (probe, target):
            try:
                p.unlink()
            except OSError:
                pass


def build_mapping(host: str) -> tuple[dict[str, str], set[str], list[str]]:
    """repo -> family label, plus the set of repos the app says are removable
    (legacy / unrecognised), which are skipped so junk isn't shipped to the fleet."""
    mapping: dict[str, str] = {}
    notes: list[str] = []

    catalog = api(host, "/api/catalog")
    families = catalog.get("families", {})
    for m in catalog.get("models", []):
        if m.get("kind") == "cloud":
            continue
        fam = families.get(m["family"], {}).get("label") or m["family"]
        mapping[m["repo"]] = fam
        for c in (m.get("cache") or {}).get("companions") or []:
            mapping.setdefault(c["repo"], fam)

    try:
        for m in api(host, "/api/transcribe/availability").get("models", []):
            mapping.setdefault(m["repo"], STT_FAMILY)
    except Exception as e:
        notes.append(f"STT list unavailable ({type(e).__name__})")

    skip: set[str] = set()
    try:
        for g in api(host, "/api/model-storage").get("groups", []):
            for it in g.get("items", []):
                if it.get("type") in {"legacy", "unknown"}:
                    skip.add(it["repo"])
    except Exception as e:
        notes.append(f"storage list unavailable ({type(e).__name__}) — nothing skipped")

    return mapping, skip, notes


def dir_bytes(p: Path) -> int:
    """Apparent size WITHOUT following symlinks — what will actually be written."""
    out = subprocess.run(["du", "-sk", str(p)], capture_output=True, text=True)
    return int(out.stdout.split()[0]) * 1024 if out.returncode == 0 else 0


def do_copy(dst_root: Path, host: str, plan_only: bool) -> None:
    mapping, skip, notes = build_mapping(host)

    jobs, skipped, unmapped = [], [], []
    for src in sorted(HUB.iterdir()):
        if not src.is_dir() or src.name in SKIP_DIRS or src.name.startswith("."):
            continue
        repo = dirname_to_repo(src.name)
        if repo is None:
            continue
        if repo in skip:
            skipped.append(repo)
            continue
        fam = mapping.get(repo)
        if fam is None:
            if "whisper" in repo.lower():
                fam = STT_FAMILY
            else:
                unmapped.append(repo)
                continue
        jobs.append((src, fam.replace("/", "-"), dir_bytes(src)))

    total = sum(b for _, _, b in jobs)
    print(f"source : {HUB}")
    print(f"target : {dst_root}")
    print(f"copying: {len(jobs)} packages, {total / 1e9:.1f} GB (symlinks preserved)\n")
    by_fam: dict[str, list[tuple[str, int]]] = {}
    for src, fam, b in jobs:
        by_fam.setdefault(fam, []).append((src.name, b))
    for fam in sorted(by_fam):
        fam_bytes = sum(b for _, b in by_fam[fam])
        print(f"  {fam}  ({fam_bytes / 1e9:.2f} GB)")
        for name, b in sorted(by_fam[fam]):
            print(f"      {name}  {b / 1e9:.2f} GB")
    if skipped:
        print(f"\n  skipped (legacy/unrecognised — not worth shipping): {', '.join(sorted(skipped))}")
    if unmapped:
        print(f"  skipped (unmapped): {', '.join(sorted(unmapped))}")
    for n in notes:
        print(f"  note: {n}")

    if plan_only:
        print("\n--plan only, nothing written.")
        return

    dst_root.mkdir(parents=True, exist_ok=True)
    if not supports_symlinks(dst_root):
        sys.exit(
            f"\nABORT: {dst_root} is on a filesystem that cannot store symlinks "
            "(exFAT/FAT32?). Copying there would dereference the HF cache and "
            "roughly double its size. Reformat as APFS, or transport with:\n"
            f"    tar -C {HUB} -cf <ssd>/models.tar models--…"
        )

    manifest = {"schema_version": 2, "layout": "<family>/models--org--name", "families": {}, "packages": []}
    for i, (src, fam, _) in enumerate(jobs, 1):
        fam_dir = dst_root / fam
        fam_dir.mkdir(parents=True, exist_ok=True)
        dst = fam_dir / src.name
        if dst.exists():
            shutil.rmtree(dst)
        print(f"[{i}/{len(jobs)}] {fam}/{src.name}")
        # symlinks=True is the whole point — see module docstring.
        shutil.copytree(src, dst, symlinks=True)
        b = dir_bytes(dst)
        manifest["packages"].append(
            {"repo": dirname_to_repo(src.name), "dir": src.name, "family": fam, "bytes": b}
        )
        manifest["families"].setdefault(fam, {"packages": [], "bytes": 0})
        manifest["families"][fam]["packages"].append(src.name)
        manifest["families"][fam]["bytes"] += b

    (dst_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    written = sum(p["bytes"] for p in manifest["packages"])
    print(f"\nDone: {len(manifest['packages'])} packages, {written / 1e9:.1f} GB written.")
    print(f"Manifest: {dst_root / 'MANIFEST.json'}")
    print("\nOn the target Mac:")
    print("    python tools/organize_models.py --restore --src <ssd>/voicestudio-models")


def do_restore(src_root: Path, restore_all: bool = False) -> None:
    """Flatten <family>/models--*/ back into this machine's HF cache, restoring
    only the models this Mac has the memory to run (unless restore_all)."""
    if not src_root.is_dir():
        sys.exit(f"not found: {src_root}")
    HUB.mkdir(parents=True, exist_ok=True)

    pkgs = [p for fam in sorted(src_root.iterdir()) if fam.is_dir()
            for p in sorted(fam.iterdir()) if p.name.startswith("models--")]
    if not pkgs:
        sys.exit(f"no models--* packages under {src_root}")

    machine_gb = round(int(subprocess.run(
        ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True
    ).stdout.strip() or 0) / 1e9, 1)

    keep, skip = pkgs, []
    if not restore_all:
        # Only restore what this Mac can actually run. The memory floor is read
        # from this machine's own catalog.py (every fleet Mac has the repo), so
        # the SSD manifest doesn't need to carry it and stays valid as floors
        # are corrected — Audio8's went 8 -> 16 GB after being measured.
        wanted, floors = set(), {}
        try:
            sys.path.insert(0, str(REPO_ROOT / "app"))
            from backend import catalog as cat  # type: ignore
            for m in cat.CATALOG:
                floor = m.min_unified_memory_gb
                floors[m.repo] = floor
                # floor None = "not yet qualified"; include it and let the run decide.
                if floor is None or floor <= machine_gb:
                    wanted.add(m.repo)
                    for c in cat.FAMILY_COMPANIONS.get(m.family, ()):
                        wanted.add(c["repo"])  # a model without its codec is useless
            # Whisper is needed by the benchmark's transcribe-back check.
            wanted.update(r for r in
                          (dirname_to_repo(p.name) for p in pkgs)
                          if r and "whisper" in r.lower())
        except Exception as e:
            print(f"could not read catalog ({type(e).__name__}) — restoring everything")
            wanted = None

        if wanted is not None:
            keep, skip = [], []
            for p in pkgs:
                repo = dirname_to_repo(p.name)
                (keep if repo in wanted else skip).append((p, repo, floors.get(repo)))
            keep = [p for p, _, _ in keep]

    print(f"machine: {machine_gb} GB unified memory")
    print(f"restoring {len(keep)} of {len(pkgs)} packages into {HUB}\n")

    for i, src in enumerate(keep, 1):
        dst = HUB / src.name
        if dst.exists():
            print(f"[{i}/{len(keep)}] {src.name} — already present, skipped")
            continue
        print(f"[{i}/{len(keep)}] {src.name}")
        shutil.copytree(src, dst, symlinks=True)

    if skip:
        print("\nskipped — needs more memory than this Mac has:")
        for _, repo, floor in skip:
            need = f"needs {floor} GB" if floor else "not in this catalogue"
            print(f"    {repo}  ({need})")
        print("  (--all restores them anyway, e.g. to stage a machine you'll upgrade)")
    print("\nDone. Restart Voice Studio (or click Update) so it rescans the cache.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dst", type=Path, default=DEFAULT_DST)
    ap.add_argument("--src", type=Path, default=DEFAULT_DST, help="restore source")
    ap.add_argument("--host", default="127.0.0.1:47870")
    ap.add_argument("--plan", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="restore every package, ignoring this Mac's memory tier")
    args = ap.parse_args()

    if args.restore:
        do_restore(args.src, args.all)
    else:
        if not HUB.is_dir():
            sys.exit(f"HF cache not found at {HUB}")
        do_copy(args.dst, args.host, args.plan)


if __name__ == "__main__":
    main()
