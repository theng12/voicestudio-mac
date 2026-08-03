"""Regression coverage for Voice Studio's Hugging Face transport policy."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"


def _fake_huggingface_hub(tmp_path: Path) -> Path:
    """Create an import probe without needing the heavy generation environment."""
    package = tmp_path / "huggingface_hub"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import os\n"
        "IMPORTED_WITH_DISABLE_XET = os.environ.get('HF_HUB_DISABLE_XET')\n"
        "class HfApi: pass\n"
        "def snapshot_download(**_kwargs): pass\n",
        encoding="utf-8",
    )
    (package / "utils.py").write_text(
        "class HfHubHTTPError(Exception): pass\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize(
    ("extra_env", "expected"),
    [
        ({}, "1"),
        ({"HF_HUB_DISABLE_XET": "0"}, "1"),
        ({"VOICESTUDIO_ENABLE_XET": "1"}, "0"),
        ({"VOICESTUDIO_ENABLE_XET": "1", "HF_HUB_DISABLE_XET": "1"}, "0"),
    ],
)
def test_huggingface_transport_is_configured_before_hub_import(
    tmp_path: Path, extra_env: dict[str, str], expected: str
) -> None:
    fake_root = _fake_huggingface_hub(tmp_path)
    env = dict(os.environ)
    # Keep every case independent of the developer's or CI runner's ambient
    # transport policy, then explicitly provide the state under test.
    env.pop("VOICESTUDIO_ENABLE_XET", None)
    env.pop("HF_HUB_DISABLE_XET", None)
    env.update(extra_env)
    env["PYTHONPATH"] = os.pathsep.join((str(fake_root), str(APP_DIR)))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import backend.downloads as downloads; "
            "import huggingface_hub; "
            "print(huggingface_hub.IMPORTED_WITH_DISABLE_XET)",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip() == expected
