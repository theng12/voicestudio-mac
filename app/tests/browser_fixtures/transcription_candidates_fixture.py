"""Loopback-only Voice Studio fixture for rendered transcription-candidate QA."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
MOONSHINE = "moonshine-ai/moonshine-base"
NEMOTRON = "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"


def _cache(repo: str) -> dict:
    return {"repo": repo, "state": "cached", "path": f"/fixture/{repo}"}


TRANSCRIPTION = {
    "available": True,
    "default_model": MOONSHINE,
    "models": [
        {
            "repo": MOONSHINE,
            "label": "Moonshine Base",
            "size_gb": 0.25,
            "note": "Internal pilot. Lightweight English short-form transcription for 8 GB Macs.",
            "engine": "moonshine",
            "min_unified_memory_gb": 8,
            "languages": "English",
            "supports_segment_timestamps": False,
            "supports_word_timestamps": False,
            "supports_long_form": False,
            "internal_candidate": True,
            "recommended": False,
            "cached": True,
            "cache": _cache(MOONSHINE),
        },
        {
            "repo": NEMOTRON,
            "label": "Nemotron 3.5 ASR Streaming 0.6B (8-bit)",
            "size_gb": 0.76,
            "note": "Internal pilot. Multilingual chunked transcription candidate for 8 GB Macs.",
            "engine": "nemotron",
            "min_unified_memory_gb": 8,
            "languages": "Multilingual",
            "supports_segment_timestamps": True,
            "supports_word_timestamps": True,
            "supports_long_form": True,
            "internal_candidate": True,
            "recommended": False,
            "cached": True,
            "cache": _cache(NEMOTRON),
        },
    ],
    "media": {},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            target = FRONTEND / "index.html"
            mime = "text/html; charset=utf-8"
        elif path.startswith("/assets/"):
            target = FRONTEND / Path(path).name
            mime = "text/javascript" if path.endswith(".js") else "text/css"
        else:
            target = None
            mime = ""
        if target:
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/transcribe/availability":
            self._send_json(TRANSCRIPTION)
        elif path == "/api/health":
            self._send_json({"ok": True})
        elif path == "/api/system":
            self._send_json({"chip": "Apple M1", "unified_memory_gb": 8})
        elif path == "/api/release-notes":
            self._send_json({"current_version": "2.4.0", "releases": []})
        elif path == "/api/catalog":
            self._send_json({"families": {}, "models": []})
        elif path == "/api/model-storage":
            self._send_json({"groups": [], "summary": {"families": 0, "packages": 0, "models": 0, "dependencies": 0, "legacy": 0, "unknown": 0, "bytes_total": 0}})
        elif path == "/api/voices":
            self._send_json([])
        elif path in {"/api/generate/stream", "/api/downloads/stream"}:
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json({})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
