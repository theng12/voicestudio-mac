from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_metadata_check", ROOT / "release_metadata_check.py")
assert SPEC and SPEC.loader
release_metadata_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_metadata_check)


def test_installed_version_has_a_truthful_whats_new_entry() -> None:
    release_metadata_check.validate_current_release()


def test_worktree_product_changes_require_release_metadata() -> None:
    release_metadata_check.validate_change_set(release_metadata_check.changed_paths())


def test_release_guard_distinguishes_product_changes_from_tests_and_docs() -> None:
    assert release_metadata_check.is_shipped_path("app/backend/generation.py") is True
    assert release_metadata_check.is_shipped_path("update.js") is True
    assert release_metadata_check.is_shipped_path("app/tests/test_generation.py") is False
    assert release_metadata_check.is_shipped_path("README.md") is False


def test_release_guard_requires_a_numeric_version_increase() -> None:
    paths = {"app/backend/generation.py", "VERSION", "CHANGELOG.md"}
    release_metadata_check.validate_change_set(
        paths, baseline_version="1.21.3", release_version="1.21.4"
    )
    with pytest.raises(release_metadata_check.ReleaseMetadataError, match="VERSION to increase"):
        release_metadata_check.validate_change_set(
            paths, baseline_version="1.21.4", release_version="1.21.4"
        )
