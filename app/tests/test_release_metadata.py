from __future__ import annotations

import importlib.util
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_metadata_check", ROOT / "release_metadata_check.py")
assert SPEC and SPEC.loader
release_metadata_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_metadata_check)


def test_installed_version_has_a_truthful_whats_new_entry() -> None:
    release_metadata_check.validate_current_release()


def test_dependency_convergence_bridge_is_versioned_as_2_4_2() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [2.4.2] — 2026-08-20" in changelog
    assert "installed-generation" in changelog
    assert "No model or live machine changed" in changelog


def test_runtime_state_migration_is_preserved_in_the_current_release() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.4.5"
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [2.4.3] — 2026-08-21" in changelog
    assert "ENVIRONMENT.example" in changelog
    assert "NVIRONMENT" in changelog


def test_worktree_product_changes_require_release_metadata() -> None:
    release_metadata_check.validate_change_set(release_metadata_check.changed_paths())


def test_release_guard_distinguishes_product_changes_from_tests_and_docs() -> None:
    assert release_metadata_check.is_shipped_path("app/backend/generation.py") is True
    assert release_metadata_check.is_shipped_path("update.js") is True
    assert release_metadata_check.is_shipped_path("install_service.sh") is True
    assert release_metadata_check.is_shipped_path("voicestudio-watchdog.sh") is True
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


def test_all_launcher_stops_use_canonical_app_local_uris() -> None:
    for name in ("update.js", "install_generation.js"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert 'uri: "{{path.resolve(cwd, \'start.js\')}}"' in source
        assert not re.search(
            r'method:\s*"script\.stop",\s*params:\s*\{\s*uri:\s*"start\.js"',
            source,
        )
