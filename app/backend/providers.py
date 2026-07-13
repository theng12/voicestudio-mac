"""
Cloud TTS provider gateway for Voice Studio (Mac).

Turns Voice Studio into an *audio gateway*: alongside the local engines
(VoxCPM, Kokoro, F5-TTS, ...), it can expose cloud text-to-speech providers
(ElevenLabs first; fal, Fish Audio, kie, ... next) behind the SAME
`/api/generate` contract Story Studio already calls. A cloud model is addressed
by a synthetic repo id `provider:<key>:<model_id>`; the router in generation.py
sends those here, and everything else — the async job engine, history, SSE
progress, per-job actions — is shared with local generation.

WHY AN ADAPTER PER PROVIDER (unlike Chat Studio's LLM gateway):
  Chat's providers are all OpenAI-compatible, so one base_url + one client
  covers them. Audio APIs are NOT standardized — ElevenLabs, fal, Fish, kie
  each have their own endpoints and request/response shapes. So each provider
  gets a thin `TTSAdapter` (list_models / list_voices / synthesize, plus
  submit/poll for async queue providers) instead of a shared client.

SELF-HEALING — NEVER DOUBLE-CHARGE:
  Cloud generation costs credits. For async providers (fal's queue), we persist
  the provider's task id on the job (`GenerationJob.provider_task_id`) the moment
  it's issued; a retry or a post-restart recovery POLLS that id via `poll()`
  instead of re-submitting via `submit()`. Sync providers (ElevenLabs) are
  atomic — the audio either came back (job done) or it didn't (safe to retry) —
  so they need no task id. `Adapter.is_async` tells the worker which path to use.

Model/voice model:
  kie and fal largely resell ElevenLabs' *models* (fal with a wider voice
  library), so the underlying model catalog overlaps heavily across providers.
  Voices therefore come from Voice Studio's own voice library, tagged with the
  provider keys they work with (a voice can be tagged for several providers) —
  see voices.py. The adapter's `synthesize` takes the provider-native voice id.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from . import settings as app_settings


# ───────────────────────── data model ─────────────────────────

@dataclass(frozen=True)
class CloudModel:
    id: str                # the model id the provider's API expects
    label: str             # human-friendly name for the UI
    notes: str = ""        # short tagline (languages, latency, quality)


@dataclass
class SubmitResult:
    """Return of an async adapter's submit(): the provider's task id to poll."""
    task_id: str


@dataclass
class PollResult:
    """Return of an async adapter's poll(): still running, or finished."""
    done: bool
    audio: Optional[bytes] = None
    mime: Optional[str] = None
    error: Optional[str] = None
    progress: float = 0.0


# ───────────────────────── adapter interface ─────────────────────────

class TTSAdapter:
    """Interface every provider implements. Methods run inside a generation
    worker THREAD (not async), so blocking httpx is fine. Raise on hard errors
    with a human-readable message; the worker turns that into job.error."""

    is_async: bool = False   # True → use submit()/poll(); False → use synthesize()

    def list_models(self, api_key: str) -> list[CloudModel]:
        raise NotImplementedError

    def list_voices(self, api_key: str) -> list[dict]:
        """Provider-native voices as [{id, label, lang, gender, preview_url?}].
        Optional — return [] if the provider has no listable voices. Voice
        Studio's own tagged library is the primary source; this is a convenience
        for importing/matching."""
        return []

    # --- sync providers (ElevenLabs): one blocking call returns the audio ---
    def synthesize(self, api_key: str, text: str, model: str, voice: str,
                   params: dict) -> tuple[bytes, str]:
        raise NotImplementedError

    # --- async providers (fal): submit → poll (self-healing recall) ---
    def submit(self, api_key: str, text: str, model: str, voice: str,
               params: dict) -> SubmitResult:
        raise NotImplementedError

    def poll(self, api_key: str, task_id: str) -> PollResult:
        raise NotImplementedError

    def cancel(self, api_key: str, task_id: str) -> None:
        """Best-effort cancel of an async task. Default: no-op."""
        return None

    def test(self, api_key: str) -> tuple[bool, str]:
        """Validate the key. Return (ok, message)."""
        raise NotImplementedError


@dataclass(frozen=True)
class Provider:
    key: str                       # slug used in the synthetic id `provider:<key>:<model>`
    name: str                      # display name
    adapter: TTSAdapter
    env_var: str                   # env override (e.g. VOICESTUDIO_ELEVENLABS_API_KEY)
    docs_url: str = ""             # where to get a key
    supports_live_listing: bool = True   # models/voices fetched live (TTL-cached)
    # Cloud TTS always costs money, so a saved key alone is NOT consent to spend:
    # the user must also flip the per-provider "paid" toggle. Kept as a field in
    # case a provider ever offers a free tier.
    always_paid: bool = True
    curated_models: tuple[CloudModel, ...] = ()   # offline/error fallback list


# ───────────────────────── ElevenLabs adapter ─────────────────────────

_EL_BASE = "https://api.elevenlabs.io"
_EL_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class ElevenLabsAdapter(TTSAdapter):
    """ElevenLabs is synchronous: POST /v1/text-to-speech/{voice_id} returns the
    MP3 bytes directly. Voices and models are listable, so the catalog stays
    live. Billed per character — the worker enforces the char guardrail before
    calling synthesize()."""
    is_async = False

    def _headers(self, api_key: str) -> dict:
        return {"xi-api-key": api_key, "accept": "audio/mpeg"}

    def list_models(self, api_key: str) -> list[CloudModel]:
        with httpx.Client(timeout=_EL_TIMEOUT) as c:
            r = c.get(f"{_EL_BASE}/v1/models", headers={"xi-api-key": api_key})
            r.raise_for_status()
            out: list[CloudModel] = []
            for m in r.json():
                if not m.get("can_do_text_to_speech", True):
                    continue
                langs = ", ".join(
                    (lang.get("name") or lang.get("language_id", ""))
                    for lang in (m.get("languages") or [])[:4]
                )
                out.append(CloudModel(
                    id=m["model_id"],
                    label=m.get("name") or m["model_id"],
                    notes=langs,
                ))
            return out

    def list_voices(self, api_key: str) -> list[dict]:
        with httpx.Client(timeout=_EL_TIMEOUT) as c:
            r = c.get(f"{_EL_BASE}/v1/voices", headers={"xi-api-key": api_key})
            r.raise_for_status()
            out = []
            for v in r.json().get("voices", []):
                labels = v.get("labels") or {}
                out.append({
                    "id": v["voice_id"],
                    "label": v.get("name") or v["voice_id"],
                    "lang": labels.get("language", ""),
                    "gender": labels.get("gender", ""),
                    "preview_url": v.get("preview_url", ""),
                })
            return out

    def synthesize(self, api_key: str, text: str, model: str, voice: str,
                   params: dict) -> tuple[bytes, str]:
        if not voice:
            raise ValueError("ElevenLabs needs a voice id — tag a voice for this provider.")
        fmt = params.get("output_format", "mp3_44100_128")
        body = {"text": text, "model_id": model or "eleven_multilingual_v2"}
        vs = {k: params[k] for k in ("stability", "similarity_boost", "style", "speed")
              if k in params and params[k] is not None}
        if vs:
            body["voice_settings"] = vs
        with httpx.Client(timeout=_EL_TIMEOUT) as c:
            r = c.post(
                f"{_EL_BASE}/v1/text-to-speech/{voice}",
                headers=self._headers(api_key),
                params={"output_format": fmt},
                json=body,
            )
            if r.status_code >= 400:
                raise RuntimeError(_http_err("ElevenLabs", r))
            return r.content, "audio/mpeg"

    def test(self, api_key: str) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=_EL_TIMEOUT) as c:
                r = c.get(f"{_EL_BASE}/v1/user", headers={"xi-api-key": api_key})
            if r.status_code == 200:
                data = r.json()
                tier = (data.get("subscription") or {}).get("tier", "")
                return True, f"Connected{f' · {tier} plan' if tier else ''}."
            return False, _http_err("ElevenLabs", r)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"


def _http_err(provider: str, r: httpx.Response) -> str:
    try:
        detail = r.json()
        detail = detail.get("detail") or detail.get("error") or detail
    except Exception:
        detail = r.text[:200]
    return f"{provider} HTTP {r.status_code}: {detail}"


# ───────────────────────── registry ─────────────────────────

PROVIDERS: dict[str, Provider] = {
    "elevenlabs": Provider(
        key="elevenlabs",
        name="ElevenLabs",
        adapter=ElevenLabsAdapter(),
        env_var="VOICESTUDIO_ELEVENLABS_API_KEY",
        docs_url="https://elevenlabs.io/app/settings/api-keys",
        supports_live_listing=True,
        curated_models=(
            CloudModel("eleven_multilingual_v2", "Multilingual v2", "29 languages · highest quality"),
            CloudModel("eleven_turbo_v2_5", "Turbo v2.5", "low latency · 32 languages"),
            CloudModel("eleven_flash_v2_5", "Flash v2.5", "fastest · ~75ms"),
        ),
    ),
    # fal / fish / kie / genaipro adapters land here in later phases.
}


# ───────────────── settings-backed key / paid / enabled ─────────────────
# Stored under settings.json key "providers": { "<key>": {api_key, paid, enabled} }.

import os


def _all() -> dict:
    return app_settings.get("providers") or {}


def _one(key: str) -> dict:
    return _all().get(key, {})


def get_api_key(key: str) -> str:
    prov = PROVIDERS.get(key)
    if prov:
        env = os.environ.get(prov.env_var)
        if env and env.strip():
            return env.strip()
    return (_one(key).get("api_key") or "").strip()


def has_key(key: str) -> bool:
    return bool(get_api_key(key))


def paid_enabled(key: str) -> bool:
    return bool(_one(key).get("paid"))


def is_enabled(key: str) -> bool:
    # Default enabled once configured; the user can turn a provider off without
    # deleting the key. "Live" = enabled AND has key AND paid consent.
    return _one(key).get("enabled", True)


def is_live(key: str) -> bool:
    return is_enabled(key) and has_key(key) and paid_enabled(key)


def _write(key: str, patch: dict) -> None:
    data = _all()
    entry = dict(data.get(key, {}))
    entry.update(patch)
    data[key] = entry
    app_settings.set_value("providers", data)


def set_key(key: str, api_key: Optional[str]) -> None:
    _write(key, {"api_key": (api_key or "").strip()})


def set_paid(key: str, paid: bool) -> None:
    _write(key, {"paid": bool(paid)})


def set_enabled(key: str, enabled: bool) -> None:
    _write(key, {"enabled": bool(enabled)})


# ───────────────── live model listing (TTL cache) ─────────────────

_LIVE_TTL_S = 300.0
_live_cache: dict[str, tuple[float, list[CloudModel]]] = {}
_voice_cache: dict[str, tuple[float, list[dict]]] = {}


def models_for_provider(key: str, force: bool = False) -> list[CloudModel]:
    """Models for one provider: live-fetch (TTL-cached) when it has a key +
    supports listing, else the curated fallback. Never raises."""
    prov = PROVIDERS.get(key)
    if prov is None:
        return []
    if prov.supports_live_listing and has_key(key):
        now = time.time()
        cached = _live_cache.get(key)
        if not force and cached and (now - cached[0]) < _LIVE_TTL_S:
            return cached[1]
        try:
            models = prov.adapter.list_models(get_api_key(key))
            if models:
                _live_cache[key] = (now, models)
                return models
        except Exception:
            pass  # fall through to curated
    return list(prov.curated_models)


def voices_for_provider(key: str, force: bool = False) -> list[dict]:
    """Provider-native voice catalog, cached briefly like model listings.

    Voice discovery is a convenience for mapping Voice Studio library entries
    to provider IDs. It never affects generation routing and never raises: a
    missing key or provider outage simply leaves the picker empty.
    """
    prov = PROVIDERS.get(key)
    if prov is None or not has_key(key):
        return []
    now = time.time()
    cached = _voice_cache.get(key)
    if not force and cached and (now - cached[0]) < _LIVE_TTL_S:
        return cached[1]
    try:
        voices = prov.adapter.list_voices(get_api_key(key))
        cleaned = [
            {
                "id": str(v.get("id") or "").strip(),
                "label": str(v.get("label") or v.get("id") or "").strip(),
                "lang": str(v.get("lang") or "").strip(),
                "gender": str(v.get("gender") or "").strip(),
                "preview_url": str(v.get("preview_url") or "").strip(),
            }
            for v in voices
            if str(v.get("id") or "").strip()
        ]
        _voice_cache[key] = (now, cleaned)
        return cleaned
    except Exception:
        return []


def synthetic_id(key: str, model_id: str) -> str:
    return f"provider:{key}:{model_id}"


def parse_id(repo: str) -> Optional[tuple[str, str]]:
    """`provider:<key>:<model_id>` → (key, model_id); None for local repos."""
    if not repo or not repo.startswith("provider:"):
        return None
    rest = repo[len("provider:"):]
    pkey, _, model = rest.partition(":")
    if not pkey or pkey not in PROVIDERS:
        return None
    return pkey, model


def adapter_for(repo: str) -> Optional[tuple[Provider, str]]:
    parsed = parse_id(repo)
    if parsed is None:
        return None
    pkey, model = parsed
    return PROVIDERS[pkey], model


# ───────────────── public serialization (for /api/providers) ─────────────────

def serialize_provider(key: str, include_models: bool = True) -> dict:
    prov = PROVIDERS[key]
    d = {
        "key": prov.key,
        "name": prov.name,
        "docs_url": prov.docs_url,
        "always_paid": prov.always_paid,
        "has_key": has_key(key),
        "paid": paid_enabled(key),
        "enabled": is_enabled(key),
        "live": is_live(key),
        "voice_mapping_supported": True,
    }
    if include_models:
        # Only surface models when the provider is actually usable, so Story
        # Studio never sees a model it can't call (no key / no paid consent).
        models = models_for_provider(key) if is_live(key) else []
        d["models"] = [
            {"id": m.id, "label": m.label, "notes": m.notes,
             "repo": synthetic_id(key, m.id)}
            for m in models
        ]
    return d


def list_providers_public(include_models: bool = True) -> list[dict]:
    return [serialize_provider(k, include_models) for k in PROVIDERS]


def cloud_models_for_catalog() -> list[dict]:
    """Flat list of every LIVE cloud model, shaped like a catalog entry, for
    merging into /api/generate/availability so Story Studio sees one unified,
    always-current list of local + cloud models."""
    out = []
    for key, prov in PROVIDERS.items():
        if not is_live(key):
            continue
        for m in models_for_provider(key):
            out.append({
                "repo": synthetic_id(key, m.id),
                "label": f"{prov.name} · {m.label}",
                "provider": key,
                "provider_name": prov.name,
                "model_id": m.id,
                "notes": m.notes,
                "kind": "cloud",
                "capabilities": ["tts"],
            })
    return out
