"""Voice Studio's fixed, non-user-editable updater identity."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .auto_update import AutoUpdater


ROOT = Path(__file__).resolve().parents[2]
SPEC = {
    "root": str(ROOT),
    "title": "Voice Studio KH",
    "slug": "voicestudio",
    "expected_remote": "https://github.com/theng12/voicestudio-mac.git",
    "branch": "main",
    "port": 47870,
    "server_label": "com.kh.voicestudio.server",
    "watchdog_label": "com.kh.voicestudio.watchdog",
    "default_hour": 2,
    "default_weekday": 6,
    "generation_marker": "diffusers",
    "verify_module": "backend.main",
}


def create_updater(readiness: Optional[Callable[[], list[str]]] = None, **kwargs) -> AutoUpdater:
    return AutoUpdater(SPEC, readiness=readiness, **kwargs)
