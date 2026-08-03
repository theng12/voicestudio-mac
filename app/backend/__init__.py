"""Voice Studio backend package initialization.

Hugging Face Hub reads its transport flags while its constants module is
imported.  Configure this before any backend module can import
``huggingface_hub`` so every download worker, including spawned processes,
uses the same safe default.
"""
from __future__ import annotations

import os


# Xet has stalled while retaining the Hugging Face cache lock on some Studio
# machines.  The classic HTTP transport resumes the same ``.incomplete``
# cache files, so make it the default.  Xet remains deliberately available for
# a diagnosed environment through an explicit Voice Studio opt-in.
if os.environ.get("VOICESTUDIO_ENABLE_XET") == "1":
    os.environ["HF_HUB_DISABLE_XET"] = "0"
else:
    os.environ["HF_HUB_DISABLE_XET"] = "1"
