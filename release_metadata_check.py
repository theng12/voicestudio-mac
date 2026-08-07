#!/usr/bin/env python3
"""Verify Voice Studio release metadata before a change is shipped.

Run this while editing to ensure a product change has a matching VERSION bump
and a clear, current changelog entry that the in-app What's New view can show:

    python3 release_metadata_check.py

CI or a post-commit verification can validate a specific commit instead:

    python3 release_metadata_check.py --range HEAD~1..HEAD
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
RELEASE_RE = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] — \d{4}-\d{2}-\d{2}$", re.MULTILINE)
RELEASE_SECTION_RE = re.compile(r"^### (?:Added|Changed|Fixed|Removed|Deprecated|Security)\b", re.MULTILINE)


class ReleaseMetadataError(RuntimeError):
    """Raised when a change cannot produce truthful release notes."""


def current_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise ReleaseMetadataError(f"VERSION must be semantic version X.Y.Z, got {version!r}.")
    return version


def version_key(version: str) -> tuple[int, int, int]:
    """Return a SemVer core suitable for the project's numeric release policy."""
    if not VERSION_RE.fullmatch(version):
        raise ReleaseMetadataError(f"Version must be semantic version X.Y.Z, got {version!r}.")
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def version_at_revision(revision: str) -> str:
    try:
        version = subprocess.check_output(
            ["git", "show", f"{revision}:VERSION"], cwd=ROOT, text=True, stderr=subprocess.PIPE
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseMetadataError(f"Could not read VERSION at {revision}: {exc}") from exc
    version_key(version)
    return version


def current_release_section(version: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = list(RELEASE_RE.finditer(changelog))
    if not releases:
        raise ReleaseMetadataError("CHANGELOG.md has no versioned release headings.")
    if releases[0].group("version") != version:
        raise ReleaseMetadataError(
            f"VERSION is {version}, but the first CHANGELOG.md release is "
            f"{releases[0].group('version')}. Add the current release at the top."
        )
    start = releases[0].end()
    end = releases[1].start() if len(releases) > 1 else len(changelog)
    return changelog[start:end]


def validate_current_release() -> None:
    """Ensure the installed What's New view describes the installed version."""
    section = current_release_section(current_version())
    if not RELEASE_SECTION_RE.search(section):
        raise ReleaseMetadataError(
            "The current CHANGELOG.md entry needs an Added, Changed, Fixed, "
            "Removed, Deprecated, or Security heading."
        )
    if not any(line.startswith("- ") for line in section.splitlines()):
        raise ReleaseMetadataError("The current CHANGELOG.md entry needs at least one clear bullet.")


def changed_paths(revision_range: str | None = None) -> set[str]:
    command = ["git", "diff", "--name-only"]
    if revision_range:
        command.append(revision_range)
    else:
        command.append("HEAD")
    try:
        output = subprocess.check_output(command, cwd=ROOT, text=True, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseMetadataError(f"Could not inspect changed files: {exc}") from exc
    return {line.strip() for line in output.splitlines() if line.strip()}


def is_shipped_path(path: str) -> bool:
    """Return whether a path changes the installed app rather than tests/docs."""
    if path in {"VERSION", "CHANGELOG.md", "README.md", "AGENTS.md"}:
        return False
    if path.startswith("app/tests/"):
        return False
    if path.startswith("app/"):
        return True
    if path in {
        "release_metadata_check.py",
        "audit_truth.py",
        "audit_contract_runtime.py",
    }:
        return True
    if path.startswith(("service/", "requirements")):
        return True
    return path in {
        "install.js",
        "install_generation.js",
        "pinokio.js",
        "reset.js",
        "start.js",
        "update.js",
        "update_and_restart.js",
        "voicestudio-watchdog.sh",
        "whats_new.js",
    }


def validate_change_set(
    paths: set[str], *, baseline_version: str | None = None, release_version: str | None = None
) -> None:
    """Require release files whenever changed paths alter the shipped product."""
    shipped = sorted(path for path in paths if is_shipped_path(path))
    if not shipped:
        return
    missing = {"VERSION", "CHANGELOG.md"} - paths
    if missing:
        raise ReleaseMetadataError(
            "Shipped changes require a VERSION bump and a clear CHANGELOG.md entry; "
            f"missing: {', '.join(sorted(missing))}. Changed product files: {', '.join(shipped)}"
        )
    if baseline_version is not None and release_version is not None:
        if version_key(release_version) <= version_key(baseline_version):
            raise ReleaseMetadataError(
                f"Shipped changes require VERSION to increase: {baseline_version} → {release_version}."
            )


def range_endpoints(revision_range: str | None) -> tuple[str, str]:
    """Return the before/after revisions for a simple A..B comparison."""
    if not revision_range:
        return ("HEAD", "WORKTREE")
    if ".." not in revision_range:
        raise ReleaseMetadataError("--range must be a simple A..B range, for example HEAD~1..HEAD.")
    before, after = revision_range.split("..", 1)
    if not before or not after or ".." in after:
        raise ReleaseMetadataError("--range must be a simple A..B range, for example HEAD~1..HEAD.")
    return before, after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", metavar="REVISION_RANGE", help="Git range to validate, for example HEAD~1..HEAD")
    args = parser.parse_args()
    try:
        validate_current_release()
        paths = changed_paths(args.range)
        before, after = range_endpoints(args.range)
        baseline = version_at_revision(before)
        release = current_version() if after == "WORKTREE" else version_at_revision(after)
        validate_change_set(paths, baseline_version=baseline, release_version=release)
    except ReleaseMetadataError as exc:
        print(f"release metadata check failed: {exc}", file=sys.stderr)
        return 1
    scope = args.range or "working tree"
    print(f"release metadata check passed ({scope}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
