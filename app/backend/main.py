"""
VoiceStudio (Mac) — backend.

Serves:
- `/`                          → single-page UI
- `/api/health`                → liveness check
- `/api/catalog`               → TTS model catalog + families with cache state
- `/api/cache/{repo}`          → cache state for one repo
- `/api/downloads*`            → list/start/cancel + SSE stream
- `/api/imports*`              → scan / link / move
- `/api/reveal`                → open path in Finder (mac only)
- `/api/settings*`             → HF token + future settings
- `/api/connectivity`          → bind port, local IPs, share-proxy state
- `/api/generate/*`            → generation availability + job submit/stream
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import cache, catalog, providers, settings as app_settings
from .generation import (
    manager as gen_manager,
    availability as gen_availability,
    diagnostics as gen_diagnostics,
    _GEN_LOCK,
)
from .downloads import manager
from .imports import import_path, scan_for_candidates
from .voices import FleetVoiceConflict, library as voice_library
from .fleet_auth import load_token as load_fleet_token, make_middleware as fleet_middleware, manifest
from .transcription import (
    manager as stt_manager,
    availability as stt_availability,
)
from .auto_update import UpdateError
from .auto_update_config import create_updater


# ───────────── App release version ─────────────
# Read once at module load — `VERSION` lives at the project root (a sibling
# of `app/`). Surfaced via `/api/version` for the WebUI footer and the
# (future) update-available check. Independent of FastAPI's `app.version`,
# which is the internal API version.

def _read_app_version() -> str:
    try:
        version_file = Path(__file__).resolve().parent.parent.parent / "VERSION"
        return version_file.read_text().strip()
    except Exception:
        return "unknown"

APP_VERSION = _read_app_version()


# ───────────── FastAPI setup ─────────────

app = FastAPI(title="Voice Studio KH", version="0.1.0")

# Permissive CORS so the main mac can call the mac mini over LAN.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """
    Force the Pinokio webview (and any browser) to always re-fetch the static
    frontend. Pinokio's embedded webview can cache index.html / app.js / style.css
    very aggressively, so we explicitly disable caching for the frontend files
    and any /assets/* path.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/assets") or path.endswith(
            (".html", ".js", ".css")
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheStaticMiddleware)
FLEET_TOKEN = load_fleet_token()
app.middleware("http")(fleet_middleware(FLEET_TOKEN))


# ───────────── request models ─────────────

class StartDownloadBody(BaseModel):
    repo: str
    token: Optional[str] = None


class ImportBody(BaseModel):
    source_path: str
    repo: Optional[str] = None
    mode: str = "link"   # "link" | "move"


class RevealBody(BaseModel):
    path: str


class PruneBody(BaseModel):
    keep_last: int = 0            # keep the newest N outputs, delete the rest
    older_than_days: float = 0.0  # or: delete outputs older than this many days


class SettingsBody(BaseModel):
    hf_token: Optional[str] = None


class AutoUpdateSettingsBody(BaseModel):
    mode: str
    frequency: str
    maintenance_hour: int
    idle_only: bool = True


class AutoUpdateRequestBody(BaseModel):
    after_current: bool = False


class TokenTestBody(BaseModel):
    hf_token: Optional[str] = None


class ProviderKeyBody(BaseModel):
    api_key: Optional[str] = None


class ProviderToggleBody(BaseModel):
    value: bool = False


class ProviderTestBody(BaseModel):
    api_key: Optional[str] = None   # test a not-yet-saved key; falls back to saved


class ProviderAccountCreateBody(BaseModel):
    label: str
    api_key: str


class ProviderAccountUpdateBody(BaseModel):
    label: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None


class VoiceProviderTagBody(BaseModel):
    provider: str
    voice_id: str
    account_id: Optional[str] = None


class UpdateVoiceProvidersBody(BaseModel):
    providers: list[VoiceProviderTagBody] = Field(default_factory=list)


def _validate_voice_provider_tags(tags: list[dict]) -> None:
    unknown = sorted({tag["provider"] for tag in tags} - set(providers.PROVIDERS))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown providers: {', '.join(unknown)}",
        )
    for tag in tags:
        account_id = str(tag.get("account_id") or "").strip()
        if not account_id:
            continue
        if tag["provider"] != "elevenlabs":
            raise HTTPException(
                status_code=400,
                detail="Account-specific voice mappings are supported for ElevenLabs only.",
            )
        if providers.get_elevenlabs_account(account_id) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown ElevenLabs account: {account_id}",
            )


class Txt2SpeechBody(BaseModel):
    repo: str
    text: str
    # Optional caller idempotency key. Studio Hub sends one stable value per
    # batch item so a lost submit response returns the original job.
    client_request_id: Optional[str] = Field(default=None, max_length=200)
    # ── Kokoro fields ──
    voice: Optional[str] = None         # preset voice name (Kokoro)
    # ── language (also implicit for some engines) ──
    language: Optional[str] = None      # explicit language code; null = auto-detect
    speed: float = 1.0
    temperature: float = 0.7
    seed: Optional[int] = None
    # ── Qwen3-TTS CustomVoice (preset speakers + emotion) ──
    preset_speaker: Optional[str] = None    # e.g. "Ryan", "Vivian", "Sohee"
    instruct: Optional[str] = None          # emotion / tone tag, e.g. "Sad and crying, speaking slowly"
    # ── Qwen3-TTS VoiceDesign (natural-language voice description) ──
    voice_design_prompt: Optional[str] = None
    # ── Voice cloning (Qwen3-TTS Base, VoxCPM2, and other engines) ──
    voice_library_id: Optional[str] = None  # id of a voice in app/voices/
    ref_transcript: Optional[str] = None    # enables VoxCPM2 ultimate cloning; required by F5-TTS
    # ── VoxCPM2 MLX controls ──
    cfg_value: float = 2.0
    inference_timesteps: int = 7
    voxcpm_warmup_patches: int = 0
    voxcpm_max_tokens: int = 2000
    normalize_text: bool = False            # retained for old saved-job/API compatibility
    # ── Chatterbox-specific sampling controls ──
    chatterbox_cfg_weight: float = 0.5
    chatterbox_repetition_penalty: float = 1.2
    chatterbox_min_p: float = 0.05
    chatterbox_top_p: float = 1.0
    # ── OmniVoice MLX diffusion controls ──
    omnivoice_num_steps: int = 32
    omnivoice_guidance_scale: float = 2.0
    omnivoice_duration_s: Optional[float] = None
    # ── Bark-specific knobs ──
    bark_voice_preset: Optional[str] = None  # e.g. "v2/en_speaker_6"; None = random
    bark_temperature: float = 0.7
    bark_max_coarse_history: int = 60
    bark_sliding_window_len: int = 60
    bark_allow_early_stop: bool = True


def _automatic_update_blockers() -> list[str]:
    """Return truthful, user-facing reasons this Studio is not idle."""
    reasons: list[str] = []
    generation_states = {str(job.state) for job in gen_manager.list_jobs()}
    if generation_states & {"queued", "running", "loading", "cancelling"}:
        reasons.append("voice generation is queued or running")
    download_states = {str(job.state) for job in manager.list_jobs()}
    if download_states & {"queued", "running", "paused", "cancelling"}:
        reasons.append("a model download is active")
    # Voice generation and transcription share this Metal lock. It remains
    # locked while a model is loading, generating, or transcribing.
    if _GEN_LOCK.locked() and not reasons:
        reasons.append("a model is loading or transcription is active")
    return reasons


auto_updater = create_updater(readiness=_automatic_update_blockers)


# ───────────── API: meta ─────────────

@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "version": app.version,
        "app_version": APP_VERSION,
        "hf_home": str(cache.hf_home()),
        "hub_dir": str(cache.hub_dir()),
    }


@app.get("/api/capabilities")
def capabilities() -> dict:
    return manifest(modality="voice", title=app.title, version=APP_VERSION,
                    operations=["tts", "voice_clone", "speech_to_text"],
                    diagnostics="/api/generate/diagnostics")


# ── Update / generation health (auto-check surfaced by the web-UI banner) ──
# Detect-in-app, apply-via-sidebar: the frontend banner reads this and points
# the user at the single "Update" (or "Install Generation") button in the
# Pinokio sidebar. We never git-pull from here — a sandboxed web page can't
# reliably drive Pinokio's script runner, and the backend restarting itself
# mid-request is fragile.
import importlib.util as _ilu
import threading as _threading
import time as _time
import urllib.request as _urlreq

_UPDATE_REPO = "theng12/voicestudio-mac"
_GEN_MODULE = "diffusers"
_update_state = {"checked_at": 0.0, "latest": None}


def _parse_ver(v):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split(".")[:3])
    except Exception:
        return (0,)


def _refresh_latest_version():
    try:
        url = f"https://raw.githubusercontent.com/{_UPDATE_REPO}/main/VERSION"
        with _urlreq.urlopen(url, timeout=5) as r:
            _update_state["latest"] = r.read().decode("utf-8").strip()
    except Exception:
        pass
    finally:
        _update_state["checked_at"] = _time.time()


@app.get("/api/update-status")
def update_status() -> dict:
    """What the web-UI banner needs: are we behind the published version, and is
    the generation stack actually installed? The remote version is fetched from
    the repo's raw VERSION file at most every ~6h, in a background thread, so a
    slow or unreachable GitHub never blocks the request."""
    if _time.time() - _update_state["checked_at"] > 6 * 3600:
        _threading.Thread(target=_refresh_latest_version, daemon=True).start()
    latest = _update_state["latest"]
    behind = bool(latest and _parse_ver(latest) > _parse_ver(APP_VERSION))
    gen_required = _GEN_MODULE is not None
    gen_ok = (_ilu.find_spec(_GEN_MODULE) is not None) if gen_required else None
    return {
        "app_version": APP_VERSION,
        "latest_version": latest,
        "update_available": behind,
        "generation_required": gen_required,
        "generation_ok": gen_ok,
    }


@app.get("/api/version")
def app_release_version() -> dict:
    """Application release version + title. Read from the VERSION file at the
    project root. Frontend renders this in the footer and (eventually) compares
    against a remote `latest.json` for update-available signaling."""
    return {
        "app_version": APP_VERSION,
        "title": app.title,
    }


@app.get("/api/auto-update/status")
def automatic_update_status() -> dict:
    return auto_updater.public_status()


@app.get("/api/auto-update/readiness")
def automatic_update_readiness() -> dict:
    return auto_updater.readiness_status()


@app.post("/api/auto-update/settings")
def automatic_update_settings(body: AutoUpdateSettingsBody) -> dict:
    try:
        return auto_updater.save_settings(body.model_dump())
    except UpdateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auto-update/check")
def automatic_update_check() -> dict:
    try:
        return auto_updater.trigger_check()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/auto-update/update")
def automatic_update_run(body: AutoUpdateRequestBody) -> dict:
    try:
        return auto_updater.trigger_update(after_current=body.after_current)
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/auto-update/retry")
def automatic_update_retry() -> dict:
    try:
        return auto_updater.retry()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/system")
def system_hardware() -> dict:
    """Apple Silicon chip + unified memory snapshot of the host. Frontend uses
    this for the Models tab per-model fit chip. Mac-only — the underlying
    sysctl probes return None elsewhere."""
    from . import system_info
    return system_info.system_info()


# ───────────── API: catalog ─────────────

def _cache_with_companions(repo: str) -> dict:
    """Cache snapshot for a model, downgraded to 'partial' when its engine's
    companion models (audio codec / tokenizer in a separate repo) aren't cached
    yet. Keeps the Models-tab badge honest: a model only reads 'cached' when it
    can actually generate without a surprise second download."""
    snap = cache.status_snapshot(repo)
    comps = catalog.companions_for(repo)
    if not comps:
        return snap
    pending = [c for c in comps if cache.cache_state(c["repo"]) != "cached"]
    if pending and snap.get("state") == "cached":
        snap = {**snap, "state": "partial"}
    snap["companions_pending"] = [
        {"repo": c["repo"], "label": c.get("label", "")} for c in pending
    ]
    return snap


@app.get("/api/catalog")
def get_catalog() -> dict:
    families = {fid: catalog.serialize_family(f) for fid, f in catalog.FAMILIES.items()}
    models = []
    for m in catalog.CATALOG:
        d = catalog.serialize_model(m)
        d["cache"] = _cache_with_companions(m.repo)
        active = manager.active_for_repo(m.repo)
        d["active_download"] = active.serialize() if active else None
        d["kind"] = "local"
        models.append(d)
    # Cloud provider models (ElevenLabs, ...) — only LIVE ones (key + paid + on).
    # No download/cache; they're "ready" the moment the provider is live, so
    # Story Studio sees one unified list of local + cloud models.
    for cm in providers.cloud_models_for_catalog():
        models.append({**cm, "cache": {"state": "cloud"}, "active_download": None})
    return {"families": families, "models": models}


@app.get("/api/cache/{repo:path}")
def get_cache(repo: str) -> dict:
    return _cache_with_companions(repo)


@app.delete("/api/cache-maintenance/stale-incomplete/{repo:path}")
def prune_stale_cache_files(repo: str) -> dict:
    if catalog.get_model(repo) is None:
        raise HTTPException(status_code=404, detail=f"Unknown repo: {repo}")
    try:
        removed = manager.prune_stale_incomplete(repo)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**removed, "cache": _cache_with_companions(repo)}


# ───────────── API: downloads ─────────────

@app.get("/api/downloads")
def list_downloads() -> dict:
    return {"jobs": [j.serialize() for j in manager.list_jobs()]}


@app.delete("/api/downloads")
def clear_downloads() -> dict:
    return {"cleared": manager.clear_finished()}


@app.post("/api/downloads")
def start_download(body: StartDownloadBody) -> dict:
    if not body.repo or "/" not in body.repo:
        raise HTTPException(status_code=400, detail="repo must be 'owner/name'")
    job = manager.start(body.repo, token=body.token)
    return {"job": job.serialize()}


@app.delete("/api/downloads/{job_id}")
def cancel_download(job_id: str) -> dict:
    ok = manager.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or already finished")
    job = manager.get(job_id)
    return {"job": job.serialize() if job else None}


@app.get("/api/downloads/stream")
async def stream_downloads():
    from sse_starlette.sse import EventSourceResponse
    async def stream():
        try:
            while True:
                payload = {"jobs": [j.serialize() for j in manager.list_jobs()]}
                yield {"event": "snapshot", "data": json.dumps(payload)}
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return
    return EventSourceResponse(stream())


# ───────────── API: imports ─────────────

@app.get("/api/imports/scan")
def imports_scan() -> dict:
    return {"candidates": [c.serialize() for c in scan_for_candidates()]}


@app.post("/api/imports")
def imports_link(body: ImportBody) -> dict:
    result = import_path(body.source_path, repo=body.repo, mode=body.mode)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "import failed"))
    return result


# ───────────── API: reveal in OS file manager ─────────────

_APP_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER_ROOT = _APP_ROOT.parent


def _reveal_allowed_roots() -> list[Path]:
    return [
        cache.hf_home().resolve(),
        (_APP_ROOT / "output").resolve(),
        (_APP_ROOT / "uploads").resolve(),
        _LAUNCHER_ROOT.resolve(),
    ]


def _is_path_allowed(target: Path) -> bool:
    target = target.resolve()
    for root in _reveal_allowed_roots():
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


@app.post("/api/reveal")
def reveal_path(body: RevealBody) -> dict:
    if sys.platform != "darwin":
        raise HTTPException(status_code=501, detail="Reveal is only implemented on macOS.")
    if not body.path:
        raise HTTPException(status_code=400, detail="path is required")
    target = Path(body.path).expanduser()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {target}")
    if not _is_path_allowed(target):
        raise HTTPException(status_code=403,
            detail="path is outside the allowed roots")
    args = ["open", "-R", str(target.resolve())] if target.is_file() else ["open", str(target.resolve())]
    try:
        subprocess.Popen(args)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"reveal failed: {e}")
    return {"ok": True, "opened": str(target.resolve())}


# ───────────── API: settings ─────────────

@app.get("/api/settings")
def get_settings() -> dict:
    return app_settings.serialize_public()


@app.post("/api/settings")
def update_settings(body: SettingsBody) -> dict:
    if body.hf_token is not None:
        app_settings.set_hf_token(body.hf_token)
    return app_settings.serialize_public()


@app.post("/api/settings/test-hf-token")
def test_hf_token(body: TokenTestBody) -> dict:
    token = (body.hf_token or "").strip() or app_settings.get_hf_token()
    if not token:
        raise HTTPException(status_code=400, detail="No token provided and none saved.")
    try:
        from huggingface_hub import HfApi
        info = HfApi().whoami(token=token)
        return {
            "ok": True,
            "name": info.get("name") or info.get("fullname") or info.get("email"),
            "type": info.get("type"),
            "orgs": [o.get("name") for o in (info.get("orgs") or []) if o.get("name")],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token validation failed: {e}")


# ───────────── API: connectivity ─────────────

def _classify_ip(ip: str) -> str:
    if ip.startswith("127."):
        return "loopback"
    try:
        octets = [int(x) for x in ip.split(".")]
        if len(octets) == 4 and octets[0] == 100 and 64 <= octets[1] <= 127:
            return "tailscale"
    except (ValueError, IndexError):
        pass
    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
        return "lan"
    return "other"


def _list_local_ips() -> list[dict]:
    ips: set[str] = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except (socket.error, OSError):
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ips.add(sock.getsockname()[0])
    except OSError:
        pass
    finally:
        sock.close()
    out = [{"ip": ip, "kind": _classify_ip(ip)} for ip in ips if ":" not in ip]
    rank = {"tailscale": 0, "lan": 1, "other": 2, "loopback": 3}
    out.sort(key=lambda d: (rank.get(d["kind"], 9), d["ip"]))
    return out


def _detect_bind_port(default: int = 47870) -> int:
    args = sys.argv
    try:
        i = args.index("--port")
        return int(args[i + 1])
    except (ValueError, IndexError):
        pass
    env_port = os.environ.get("UVICORN_PORT", "").strip()
    if env_port.isdigit():
        return int(env_port)
    return default


def _detect_bind_host(default: str = "0.0.0.0") -> str:
    args = sys.argv
    try:
        i = args.index("--host")
        return args[i + 1]
    except (ValueError, IndexError):
        pass
    return default


_BIND_PORT = _detect_bind_port()
_BIND_HOST = _detect_bind_host()


@app.get("/api/connectivity")
def connectivity(request: Request) -> dict:
    request_port = request.url.port
    if request_port is None:
        request_port = 443 if request.url.scheme == "https" else 80
    return {
        "listen_port": _BIND_PORT,
        "bind_port": _BIND_PORT,
        "bind_host": _BIND_HOST,
        "request_port": request_port,
        "scheme": request.url.scheme,
        "client_url": str(request.base_url).rstrip("/"),
        "addresses": _list_local_ips(),
        "share_local_enabled": (os.environ.get("PINOKIO_SHARE_LOCAL", "").strip().lower() == "true"),
        "share_local_port_fixed": os.environ.get("PINOKIO_SHARE_LOCAL_PORT", "").strip() or None,
        "share_passcode_set": bool(os.environ.get("PINOKIO_SHARE_PASSCODE", "").strip()),
        "pinokio_ui_port": 42000,
    }


# ───────────── API: cloud TTS providers (the audio gateway) ─────────────

@app.get("/api/providers")
def list_providers() -> dict:
    """All cloud audio providers with status + (when live) their model list.
    A model only appears once the provider has a saved key AND the 'paid'
    consent toggle is on — so nothing bills by accident."""
    return {"providers": providers.list_providers_public(include_models=True)}


@app.post("/api/providers/{key}/key")
def set_provider_key(key: str, body: ProviderKeyBody) -> dict:
    if key not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {key}")
    providers.set_key(key, body.api_key)
    return providers.serialize_provider(key)


@app.post("/api/providers/{key}/paid")
def set_provider_paid(key: str, body: ProviderToggleBody) -> dict:
    if key not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {key}")
    providers.set_paid(key, body.value)
    return providers.serialize_provider(key)


@app.post("/api/providers/{key}/enabled")
def set_provider_enabled(key: str, body: ProviderToggleBody) -> dict:
    if key not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {key}")
    providers.set_enabled(key, body.value)
    return providers.serialize_provider(key)


@app.post("/api/providers/{key}/test")
def test_provider(key: str, body: ProviderTestBody) -> dict:
    """Validate a provider's key (the one passed, else the saved one)."""
    prov = providers.PROVIDERS.get(key)
    if prov is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {key}")
    api_key = (body.api_key or "").strip() or providers.get_api_key(key)
    if not api_key:
        return {"ok": False, "message": "No API key set."}
    ok, message = prov.adapter.test(api_key)
    return {"ok": ok, "message": message}


def _require_account_pool(key: str) -> None:
    if key != "elevenlabs":
        raise HTTPException(
            status_code=400,
            detail="Multiple accounts are currently supported for ElevenLabs only.",
        )


@app.get("/api/providers/{key}/accounts")
def provider_accounts(key: str) -> dict:
    _require_account_pool(key)
    return {"accounts": providers.public_elevenlabs_accounts()}


@app.post("/api/providers/{key}/accounts")
def add_provider_account(key: str, body: ProviderAccountCreateBody) -> dict:
    _require_account_pool(key)
    try:
        account = providers.add_elevenlabs_account(body.label, body.api_key)
        providers.refresh_elevenlabs_account(account["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return providers.serialize_provider(key)


@app.post("/api/providers/{key}/accounts/refresh")
def refresh_provider_accounts(key: str) -> dict:
    _require_account_pool(key)
    account_ids = [account["id"] for account in providers.elevenlabs_accounts()]
    if account_ids:
        with ThreadPoolExecutor(max_workers=min(4, len(account_ids))) as pool:
            list(pool.map(providers.refresh_elevenlabs_account, account_ids))
    return providers.serialize_provider(key)


@app.patch("/api/providers/{key}/accounts/{account_id}")
def update_provider_account(
    key: str, account_id: str, body: ProviderAccountUpdateBody,
) -> dict:
    _require_account_pool(key)
    try:
        providers.update_elevenlabs_account(
            account_id,
            label=body.label,
            api_key=body.api_key,
            enabled=body.enabled,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Account not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return providers.serialize_provider(key)


@app.delete("/api/providers/{key}/accounts/{account_id}")
def delete_provider_account(key: str, account_id: str) -> dict:
    _require_account_pool(key)
    try:
        deleted = providers.delete_elevenlabs_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found.")
    # A mapping belongs to this credential/workspace. Remove it with the
    # account so future voice edits never retain an invisible stale account ID.
    for voice in voice_library.list():
        current = voice.providers or []
        cleaned = [
            tag for tag in current
            if not (
                tag.get("provider") == "elevenlabs"
                and tag.get("account_id") == account_id
            )
        ]
        if len(cleaned) != len(current):
            voice_library.update(voice.id, providers=cleaned)
    return providers.serialize_provider(key)


@app.post("/api/providers/{key}/accounts/{account_id}/test")
def test_provider_account(key: str, account_id: str) -> dict:
    _require_account_pool(key)
    if providers.get_elevenlabs_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    providers.refresh_elevenlabs_account(account_id)
    account = next(
        item for item in providers.public_elevenlabs_accounts()
        if item["id"] == account_id
    )
    return {
        "ok": account["status"] in ("ready", "exhausted", "quota_unknown"),
        "account": account,
    }


@app.get("/api/providers/{key}/models/live")
def provider_models_live(key: str) -> dict:
    """Force a fresh live fetch of a provider's models (bypasses the TTL cache) —
    surfaces newly-shipped / deprecated models on demand."""
    if key not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {key}")
    models = providers.models_for_provider(key, force=True)
    return {"models": [{"id": m.id, "label": m.label, "notes": m.notes,
                        "repo": providers.synthetic_id(key, m.id)} for m in models]}


@app.get("/api/providers/{key}/voices/live")
def provider_voices_live(key: str, account_id: Optional[str] = None) -> dict:
    """Provider-native voices for mapping a library voice to its cloud ID."""
    if key not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {key}")
    if account_id and key == "elevenlabs" and providers.get_elevenlabs_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"voices": providers.voices_for_provider(
        key, force=True, account_id=account_id
    )}


# ───────────── API: generation ─────────────

@app.get("/api/generate/availability")
def generation_availability() -> dict:
    return gen_availability()


@app.get("/api/generate/diagnostics")
def generation_diagnostics() -> dict:
    """Per-package + per-engine health check. Surfaced in the Generate tab as a
    checklist so users see what's installed and which engines are ready.
    Includes `app_version` for convenience so the frontend doesn't need an
    extra round-trip."""
    data = gen_diagnostics()
    data["app_version"] = APP_VERSION
    data["memory"] = gen_manager.memory_status()
    return data


@app.get("/api/generate/memory")
def generation_memory() -> dict:
    """Live memory guard and self-healing state for operators and Studio Hub."""
    return gen_manager.memory_status()


# ───────────── API: voice library ─────────────

def _serialize_voice(voice) -> dict:
    item = voice.serialize()
    item["transcript"] = voice_library.transcript(voice.id) or ""
    return item


@app.get("/api/voices")
def list_voices() -> dict:
    return {"voices": [_serialize_voice(voice) for voice in voice_library.list()]}


@app.get("/api/voices/{voice_id}")
def get_voice(voice_id: str) -> dict:
    v = voice_library.get(voice_id)
    if v is None:
        raise HTTPException(status_code=404, detail=f"voice {voice_id} not found")
    return _serialize_voice(v)


@app.get("/api/voices/{voice_id}/audio")
def get_voice_audio(voice_id: str) -> FileResponse:
    v = voice_library.get(voice_id)
    if v is None:
        raise HTTPException(status_code=404, detail=f"voice {voice_id} not found")
    path = voice_library.reference_path(voice_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="reference audio missing on disk")
    # Map our stored extensions to sensible Content-Type values so the browser's
    # <audio> tag streams correctly. Defaults to octet-stream as a fallback.
    mime_by_ext = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
    }
    media_type = mime_by_ext.get(v.audio_extension, "application/octet-stream")
    return FileResponse(str(path), media_type=media_type, filename=path.name)


@app.post("/api/voices")
async def add_voice(
    audio: UploadFile = File(...),
    name: str = Form(...),
    language: str = Form(...),
    gender: str = Form(...),
    license: str = Form(...),
    notes: str = Form(""),
    source_url: str = Form(""),
    transcript: str = Form(""),
    permission_acknowledged: bool = Form(False),
) -> dict:
    """Upload a new voice reference clip. The audio file goes into
    app/voices/<id>/reference.<ext>; the rest becomes metadata.json."""
    try:
        data = await audio.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"failed to read upload: {e}")
    try:
        v = voice_library.add(
            audio_bytes=data,
            original_filename=audio.filename or "reference.wav",
            name=name,
            language=language,
            gender=gender,
            license=license,
            notes=notes,
            source_url=source_url or None,
            transcript=transcript or None,
            permission_acknowledged=permission_acknowledged,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"voice": _serialize_voice(v)}


@app.put("/api/voices/{voice_id}/fleet-sync")
async def sync_fleet_voice(
    voice_id: str,
    audio: UploadFile = File(...),
    audio_sha256: str = Form(...),
    name: str = Form(...),
    language: str = Form(...),
    gender: str = Form(...),
    license: str = Form(...),
    notes: str = Form(""),
    source_url: str = Form(""),
    transcript: str = Form(""),
    permission_acknowledged: bool = Form(False),
) -> dict:
    """Idempotently install one authenticated, Hub-owned shared voice."""
    try:
        data = await audio.read()
        voice, status = voice_library.sync_from_hub(
            voice_id,
            audio_bytes=data,
            original_filename=audio.filename or "reference.wav",
            audio_sha256=audio_sha256,
            name=name,
            language=language,
            gender=gender,
            license=license,
            notes=notes,
            source_url=source_url or None,
            transcript=transcript or None,
            permission_acknowledged=permission_acknowledged,
        )
    except FleetVoiceConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "voice": _serialize_voice(voice),
        "sync": {"status": status, "sha256": voice.audio_sha256},
    }


@app.delete("/api/voices/{voice_id}/fleet-sync")
def delete_fleet_voice(voice_id: str, audio_sha256: str = Query(...)) -> dict:
    """Remove only the exact Hub-managed copy, never an unrelated local voice."""
    try:
        deleted = voice_library.delete_fleet_managed(voice_id, audio_sha256)
    except FleetVoiceConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"managed voice {voice_id} not found")
    return {"deleted": voice_id, "sha256": audio_sha256}


@app.delete("/api/voices/{voice_id}")
def delete_voice(voice_id: str) -> dict:
    ok = voice_library.delete(voice_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"voice {voice_id} not found")
    return {"deleted": voice_id}


class UpdateVoiceBody(BaseModel):
    """All fields optional — only the ones present in the request body get
    updated. Pass an empty string to CLEAR a clearable field (notes /
    source_url / transcript). Audio file is never touched by this endpoint."""
    name: Optional[str] = None
    language: Optional[str] = None
    gender: Optional[str] = None
    license: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    transcript: Optional[str] = None
    providers: Optional[list[VoiceProviderTagBody]] = None


@app.patch("/api/voices/{voice_id}")
def update_voice(voice_id: str, body: UpdateVoiceBody) -> dict:
    """Edit a voice's metadata (most commonly: add a transcript to a clip
    that was uploaded without one — required for F5-TTS compatibility)."""
    provider_tags = None
    if body.providers is not None:
        provider_tags = [tag.model_dump() for tag in body.providers]
        _validate_voice_provider_tags(provider_tags)
    try:
        updated = voice_library.update(
            voice_id,
            name=body.name,
            language=body.language,
            gender=body.gender,
            license=body.license,
            notes=body.notes,
            source_url=body.source_url,
            transcript=body.transcript,
            providers=provider_tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail=f"voice {voice_id} not found")
    return {"voice": _serialize_voice(updated)}


@app.put("/api/voices/{voice_id}/providers")
def update_voice_providers(voice_id: str, body: UpdateVoiceProvidersBody) -> dict:
    """Replace a voice's provider mappings atomically.

    One library voice may map to several cloud providers. ElevenLabs may have
    one mapping per account; other providers have one mapping each.
    Provider-native IDs are opaque and are never treated as paths.
    """
    tags = [tag.model_dump() for tag in body.providers]
    _validate_voice_provider_tags(tags)
    try:
        updated = voice_library.update(voice_id, providers=tags)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail=f"voice {voice_id} not found")
    return {"voice": _serialize_voice(updated)}


# ──── public-domain seed catalog ────

@app.get("/api/voices/seed-catalog")
def get_seed_catalog() -> dict:
    """Curated list of public-domain voice clips users can one-click add."""
    from .voices import seed_catalog
    return {"entries": seed_catalog()}


class AddSeedBody(BaseModel):
    seed_id: str


@app.post("/api/voices/from-seed")
def add_seed_voice(body: AddSeedBody) -> dict:
    """Download a seed-catalog entry's audio + create a library voice from it.
    The seed entry's metadata (name, lang, gender, license, attribution) becomes
    the new library voice's metadata."""
    from .voices import seed_catalog
    entry = next((e for e in seed_catalog() if e["id"] == body.seed_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"seed entry {body.seed_id!r} not found")
    try:
        v = voice_library.add_from_url(
            url=entry["audio_url"],
            name=entry["name"],
            language=entry["language"],
            gender=entry["gender"],
            license=entry["license"],
            notes=entry.get("notes", ""),
            source_url=entry.get("source_url"),
            transcript=entry.get("transcript"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"voice": _serialize_voice(v)}


# The frontend was copied from MusicStudio/ImageStudio and calls /api/loras —
# rather than rewrite that frontend code, mirror the empty-stub here too so
# the log stops filling with 404s.
@app.get("/api/loras")
def list_loras_stub() -> dict:
    return {"loras": []}


@app.post("/api/generate/txt2speech")
def start_txt2speech(body: Txt2SpeechBody) -> dict:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    if providers.parse_id(body.repo):
        # ── Cloud provider model ── the worker validates key/paid/model; here we
        # just require a provider-native voice id (cloud TTS is voice-driven).
        if not (body.voice or "").strip() and not (body.voice_library_id or "").strip():
            raise HTTPException(
                status_code=400,
                detail="A mapped library voice is required for cloud providers.",
            )
    else:
        # ── Local engine model ── needs the generation stack installed + cached.
        if not gen_manager.is_available():
            raise HTTPException(
                status_code=503,
                detail="TTS generation engine not installed. Run 'Install Generation' from the Pinokio sidebar.",
            )
        model = catalog.get_model(body.repo)
        if model is None:
            raise HTTPException(status_code=400, detail=f"Unknown repo: {body.repo}")
        if "tts" not in (model.capabilities or ()):
            raise HTTPException(
                status_code=400,
                detail=f"Model {body.repo} doesn't support text-to-speech.",
            )
        if cache.cache_state(body.repo) != "cached":
            raise HTTPException(
                status_code=409,
                detail=f"Model {body.repo} is not fully cached. Download it from the Models tab first.",
            )

    params = body.model_dump()
    try:
        job = gen_manager.start_txt2speech(params)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"job": job.serialize()}


@app.get("/api/generate/jobs")
def list_generation_jobs() -> dict:
    return {"jobs": [j.serialize() for j in gen_manager.list_jobs()]}


@app.delete("/api/generate/jobs")
def clear_generation_history() -> dict:
    return {"cleared": gen_manager.clear_history()}


@app.get("/api/generate/jobs/{job_id}")
def get_generation_job(job_id: str) -> dict:
    job = gen_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job": job.serialize()}


@app.get("/api/generate/jobs/{job_id}/audio")
def get_generation_audio(job_id: str) -> FileResponse:
    job = gen_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.output_path:
        raise HTTPException(status_code=425, detail="audio not ready yet")
    mt = "audio/mpeg" if str(job.output_path).lower().endswith(".mp3") else "audio/wav"
    return FileResponse(job.output_path, media_type=mt)


@app.delete("/api/generate/jobs/{job_id}")
def cancel_generation_job(job_id: str) -> dict:
    ok = gen_manager.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or already finished")
    job = gen_manager.get(job_id)
    return {"job": job.serialize() if job else None}


@app.delete("/api/generate/history/{job_id}")
def delete_one_generation(job_id: str) -> dict:
    """Delete a single FINISHED generation: remove it from history and delete its
    WAV from disk. (DELETE .../jobs/{id} only cancels active jobs.)"""
    if not gen_manager.delete_job(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": job_id}


@app.get("/api/output/stats")
def output_stats() -> dict:
    """Size + count of generated WAVs on disk, for the disk-usage display."""
    return gen_manager.output_stats()


@app.post("/api/output/prune")
def prune_outputs(body: PruneBody) -> dict:
    """Reclaim disk: keep the newest N (keep_last) OR delete files older than
    older_than_days. History entries for deleted files are trimmed too."""
    return gen_manager.prune_outputs(keep_last=body.keep_last, older_than_days=body.older_than_days)


# ──── Transcription / subtitles (Whisper STT) ────

@app.get("/api/transcribe/availability")
def transcribe_availability() -> dict:
    """STT readiness + which whisper models are cached. A remote consumer
    (e.g. Story Studio) hits this before transcribing to pick a ready model."""
    return stt_availability()


@app.post("/api/transcribe")
async def transcribe(
    file: Optional[UploadFile] = File(None),
    job_id: str = Form(""),
    model: str = Form(""),
    language: str = Form(""),
    word_timestamps: bool = Form(False),
) -> dict:
    """Transcribe audio → text + timestamped segments + ready-to-use SRT/VTT.

    Two ways to supply the audio (exactly one required):
      - multipart `file`: upload any audio clip (universal, decoupled).
      - `job_id`: transcribe a previous TTS output already on this server,
        without re-uploading the bytes (efficient same-machine path).

    Optional:
      - `model`: whisper repo (default = the recommended turbo model).
      - `language`: ISO code (e.g. 'en'); omit for auto-detect.
      - `word_timestamps`: include per-word timings in each segment.
    """
    import tempfile

    tmp_path: Optional[str] = None
    audio_path: Optional[str] = None
    try:
        if job_id.strip():
            # Transcribe an existing TTS job's output — no re-upload.
            job = gen_manager.get(job_id.strip())
            if job is None:
                raise HTTPException(status_code=404, detail=f"job {job_id} not found")
            if not job.output_path:
                raise HTTPException(status_code=425, detail="job audio not ready yet")
            audio_path = job.output_path
        elif file is not None:
            try:
                data = await file.read()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"failed to read upload: {e}")
            if not data:
                raise HTTPException(status_code=400, detail="uploaded audio is empty")
            suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
            fd, tmp_path = tempfile.mkstemp(prefix="stt-", suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            audio_path = tmp_path
        else:
            raise HTTPException(
                status_code=400,
                detail="provide either a multipart 'file' upload or a 'job_id'",
            )

        try:
            result = stt_manager.transcribe(
                audio_path,
                model_repo=model or None,
                language=language or None,
                word_timestamps=word_timestamps,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            # Not-cached / not-downloaded → 409 so the caller can trigger a
            # download and retry, rather than treating it as a hard 500.
            raise HTTPException(status_code=409, detail=str(e))
        return result
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.get("/api/generate/stream")
async def stream_generation():
    from sse_starlette.sse import EventSourceResponse
    async def stream():
        try:
            while True:
                payload = {"jobs": [j.serialize() for j in gen_manager.list_jobs()]}
                yield {"event": "snapshot", "data": json.dumps(payload)}
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return
    return EventSourceResponse(stream())


# ───────────── static frontend ─────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR), html=False), name="assets")

    @app.get("/", response_class=Response)
    def index() -> Response:
        # Read index.html and substitute __APP_VERSION__ tokens with the
        # current VERSION. This auto-bumps cache-buster query strings on
        # every release so users never see stale JS/CSS in Pinokio's
        # aggressively-caching webview — see v1.3.6 fix where the manual
        # `?v=phase2-...` strings hadn't been bumped since v1.1.8 and
        # users were running the wrong app.js for 5+ patch releases.
        html = (FRONTEND_DIR / "index.html").read_text()
        html = html.replace("__APP_VERSION__", APP_VERSION)
        return Response(content=html, media_type="text/html")
