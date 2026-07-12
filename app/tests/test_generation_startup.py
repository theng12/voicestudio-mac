from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_generation_module_does_not_import_model_stacks_at_startup() -> None:
    app_dir = Path(__file__).resolve().parents[1]
    code = r'''
import builtins

blocked = {
    "diffusers", "f5_tts", "kokoro", "mlx_audio", "omnivoice",
    "torch", "transformers", "voxcpm",
}
attempted = []
real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".", 1)[0] in blocked:
        attempted.append(name)
        raise AssertionError(f"heavy model library imported during startup: {name}")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
from backend import generation
generation.availability()
assert not attempted, attempted
'''
    env = {**os.environ, "PYTHONPATH": str(app_dir)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
