#!/bin/bash
#
# Voice Studio KH — headless server entrypoint used by the macOS launchd
# startup service (installed via the "Install as Startup Service" menu button,
# see install_service.sh + README "Run as an always-on server").
#
# Self-locating: every path is derived from THIS file's own folder, so the same
# file works on any Mac and any username with no edits. launchd runs it with
# KeepAlive, so if the server ever exits it is relaunched automatically.
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"   # launcher root (this file's folder)
PINOKIO_HOME="$(cd "$HERE/../.." && pwd)"

# Pin the model cache to the same place Pinokio uses, or the app won't find the
# models you already downloaded. The backend selects the safe Hugging Face
# transport before importing the Hub client.
export HF_HOME="$HERE/cache/HF_HOME"
export PATH="$PINOKIO_HOME/bin/miniforge/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
export PYTHONUNBUFFERED=1

cd "$HERE/app"
exec "$HERE/conda_env/bin/python" -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 47870
