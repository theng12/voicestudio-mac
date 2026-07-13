"""
Cloud TTS provider gateway for Voice Studio (Mac).

Turns Voice Studio into an *audio gateway*: alongside the local engines
(VoxCPM, Kokoro, F5-TTS, ...), it can expose cloud text-to-speech providers
(ElevenLabs, GenAIPro, Fish Audio, fal.ai, and Kie.ai) behind the SAME
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
  Cloud generation costs credits. For async providers, we persist the provider's
  task id and opaque recall metadata on the job the moment they're issued; a retry
  or a post-restart recovery POLLS that task via `poll()` instead of re-submitting
  via `submit()`. Sync providers (ElevenLabs and Fish Audio) are
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

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

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
    metadata: dict = field(default_factory=dict)


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

    def poll(self, api_key: str, task_id: str,
             metadata: Optional[dict] = None) -> PollResult:
        raise NotImplementedError

    def cancel(self, api_key: str, task_id: str,
               metadata: Optional[dict] = None) -> None:
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


# ───────────────────────── GenAIPro adapter ─────────────────────────

_GENAIPRO_BASE = "https://genaipro.io/api"
_GENAIPRO_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_GENAIPRO_MODELS = (
    CloudModel("eleven_multilingual_v2", "Multilingual v2", "high quality · multilingual"),
    CloudModel("eleven_turbo_v2_5", "Turbo v2.5", "low latency · multilingual"),
    CloudModel("eleven_flash_v2_5", "Flash v2.5", "fastest ElevenLabs model"),
    CloudModel("eleven_v3", "Eleven v3", "latest expressive model"),
)


class GenAIProAdapter(TTSAdapter):
    """GenAIPro Labs TTS is asynchronous: create a task, persist its id, poll
    until completed, then download the provider-hosted MP3. Its documented
    model list is curated here while voices are fetched live and paginated."""
    is_async = True

    @staticmethod
    def _headers(api_key: str) -> dict:
        return {
            "authorization": f"Bearer {api_key}",
            "accept": "application/json",
        }

    def list_models(self, api_key: str) -> list[CloudModel]:
        return list(_GENAIPRO_MODELS)

    def list_voices(self, api_key: str) -> list[dict]:
        out: list[dict] = []
        with httpx.Client(timeout=_GENAIPRO_TIMEOUT) as c:
            for page in range(20):
                r = c.get(
                    f"{_GENAIPRO_BASE}/v1/labs/voices",
                    headers=self._headers(api_key),
                    params={"page_size": 100, "page": page},
                )
                if r.status_code >= 400:
                    raise RuntimeError(_http_err("GenAIPro", r))
                payload = r.json()
                batch = payload if isinstance(payload, list) else payload.get("voices", [])
                for voice in batch:
                    out.append({
                        "id": voice.get("voice_id", ""),
                        "label": voice.get("name") or voice.get("voice_id", ""),
                        "lang": voice.get("language") or voice.get("locale") or "",
                        "gender": voice.get("gender", ""),
                        "preview_url": voice.get("preview_url", ""),
                    })
                if len(batch) < 100:
                    break
        return out

    def submit(self, api_key: str, text: str, model: str, voice: str,
               params: dict) -> SubmitResult:
        if not voice:
            raise ValueError("GenAIPro needs a voice id — tag a voice for this provider.")
        body = {
            "input": text,
            "voice_id": voice,
            "model_id": model or "eleven_multilingual_v2",
            "speed": max(0.7, min(1.2, float(params.get("speed", 1.0)))),
        }
        optional = {
            "stability": params.get("stability"),
            "similarity": params.get("similarity", params.get("similarity_boost")),
            "style": params.get("style"),
            "use_speaker_boost": params.get("use_speaker_boost"),
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        with httpx.Client(timeout=_GENAIPRO_TIMEOUT) as c:
            r = c.post(
                f"{_GENAIPRO_BASE}/v1/labs/task",
                headers=self._headers(api_key),
                json=body,
            )
        if r.status_code >= 400:
            raise RuntimeError(_http_err("GenAIPro", r))
        task_id = str((r.json() or {}).get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError("GenAIPro did not return a task id.")
        return SubmitResult(task_id=task_id)

    def poll(self, api_key: str, task_id: str,
             metadata: Optional[dict] = None) -> PollResult:
        with httpx.Client(timeout=_GENAIPRO_TIMEOUT) as c:
            r = c.get(
                f"{_GENAIPRO_BASE}/v1/labs/task/{task_id}",
                headers=self._headers(api_key),
            )
        if r.status_code >= 400:
            raise RuntimeError(_http_err("GenAIPro", r))
        data = r.json() or {}
        status = str(data.get("status") or "").lower()
        progress = float(data.get("process_percentage") or 0) / 100.0
        if status in {"failed", "error", "cancelled", "canceled"}:
            return PollResult(
                done=True,
                error=str(data.get("error") or data.get("message") or f"Task {status}."),
            )
        if status != "completed":
            return PollResult(done=False, progress=progress)
        audio_url = str(data.get("result") or "").strip()
        if not audio_url:
            return PollResult(done=True, error="GenAIPro completed without an audio URL.")
        audio, mime = _download_provider_audio(
            "GenAIPro", audio_url, allowed_host_suffixes=("genaipro.io",)
        )
        return PollResult(done=True, audio=audio, mime=mime, progress=1.0)

    def cancel(self, api_key: str, task_id: str,
               metadata: Optional[dict] = None) -> None:
        with httpx.Client(timeout=_GENAIPRO_TIMEOUT) as c:
            c.delete(
                f"{_GENAIPRO_BASE}/v1/labs/task/{task_id}",
                headers=self._headers(api_key),
            )

    def test(self, api_key: str) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=_GENAIPRO_TIMEOUT) as c:
                r = c.get(f"{_GENAIPRO_BASE}/v2/me", headers=self._headers(api_key))
            if r.status_code != 200:
                return False, _http_err("GenAIPro", r)
            data = r.json() or {}
            username = data.get("username") or "account"
            balance = data.get("balance")
            suffix = f" · balance {balance:g}" if isinstance(balance, (int, float)) else ""
            return True, f"Connected as {username}{suffix}."
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"


def _download_provider_audio(
    provider: str,
    url: str,
    *,
    allowed_host_suffixes: tuple[str, ...],
) -> tuple[bytes, str]:
    """Download a provider result without allowing arbitrary callback URLs.

    Async APIs return an audio URL. Validate every redirect target so a bad or
    compromised response cannot turn Voice Studio into an internal-network
    request proxy.
    """
    current = url
    with httpx.Client(timeout=_GENAIPRO_TIMEOUT, follow_redirects=False) as c:
        for _ in range(4):
            parsed = urlparse(current)
            host = (parsed.hostname or "").lower()
            allowed = any(
                host == suffix or host.endswith(f".{suffix}")
                for suffix in allowed_host_suffixes
            )
            if parsed.scheme != "https" or not allowed:
                raise RuntimeError(f"{provider} returned an untrusted audio URL.")
            r = c.get(current, headers={"accept": "audio/*"})
            if r.status_code in {301, 302, 303, 307, 308}:
                location = r.headers.get("location")
                if not location:
                    raise RuntimeError(f"{provider} returned an invalid audio redirect.")
                current = urljoin(current, location)
                continue
            if r.status_code >= 400:
                raise RuntimeError(_http_err(provider, r))
            if not r.content:
                raise RuntimeError(f"{provider} returned an empty audio file.")
            mime = r.headers.get("content-type", "audio/mpeg").split(";", 1)[0]
            return r.content, mime
    raise RuntimeError(f"{provider} returned too many audio redirects.")


# ───────────────────────── Fish Audio adapter ─────────────────────────

_FISH_BASE = "https://api.fish.audio"
_FISH_TIMEOUT = httpx.Timeout(180.0, connect=10.0)
_FISH_MODELS = (
    CloudModel("s2-pro", "S2-Pro", "recommended · expressive · 80+ languages"),
    CloudModel("s1", "S1", "natural multilingual speech"),
)


class FishAudioAdapter(TTSAdapter):
    """Fish Audio's REST TTS endpoint returns the complete audio response.

    The provider calls voice clones "models"; Voice Studio exposes those as
    provider-native voices while keeping S2-Pro/S1 as the generation models.
    """
    is_async = False

    @staticmethod
    def _headers(api_key: str, *, model: Optional[str] = None) -> dict:
        headers = {
            "authorization": f"Bearer {api_key}",
            "accept": "application/json",
        }
        if model:
            headers["model"] = model
        return headers

    def list_models(self, api_key: str) -> list[CloudModel]:
        return list(_FISH_MODELS)

    def list_voices(self, api_key: str) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        with httpx.Client(timeout=_FISH_TIMEOUT) as c:
            # Own private/unlisted voices first, then popular public voices.
            for own_only, max_pages in ((True, 5), (False, 5)):
                for page in range(1, max_pages + 1):
                    r = c.get(
                        f"{_FISH_BASE}/model",
                        headers=self._headers(api_key),
                        params={
                            "page_size": 100,
                            "page_number": page,
                            "self": own_only,
                            "sort_by": "task_count",
                        },
                    )
                    if r.status_code >= 400:
                        raise RuntimeError(_http_err("Fish Audio", r))
                    payload = r.json() or {}
                    items = payload.get("items") or []
                    for item in items:
                        voice_id = str(item.get("_id") or item.get("id") or "").strip()
                        if (
                            not voice_id
                            or voice_id in seen
                            or item.get("type") not in (None, "tts")
                            or item.get("state") == "failed"
                        ):
                            continue
                        seen.add(voice_id)
                        tags = [str(tag).lower() for tag in (item.get("tags") or [])]
                        gender = "female" if "female" in tags else ("male" if "male" in tags else "")
                        samples = item.get("samples") or []
                        sample = samples[0] if samples and isinstance(samples[0], dict) else {}
                        preview = sample.get("audio") or sample.get("url") or ""
                        if isinstance(preview, dict):
                            preview = preview.get("url") or ""
                        out.append({
                            "id": voice_id,
                            "label": item.get("title") or voice_id,
                            "lang": ", ".join((item.get("languages") or [])[:4]),
                            "gender": gender,
                            "preview_url": preview,
                        })
                    if not payload.get("has_more") or not items:
                        break
        return out

    def synthesize(self, api_key: str, text: str, model: str, voice: str,
                   params: dict) -> tuple[bytes, str]:
        body = {
            "text": text,
            "format": "mp3",
            "sample_rate": 44100,
            "mp3_bitrate": 128,
            "normalize": True,
            "prosody": {
                "speed": max(0.5, min(2.0, float(params.get("speed", 1.0)))),
                "volume": 0,
                "normalize_loudness": True,
            },
        }
        if voice:
            body["reference_id"] = voice
        with httpx.Client(timeout=_FISH_TIMEOUT) as c:
            r = c.post(
                f"{_FISH_BASE}/v1/tts",
                headers={
                    **self._headers(api_key, model=model or "s2-pro"),
                    "content-type": "application/json",
                    "accept": "audio/mpeg",
                },
                json=body,
            )
        if r.status_code >= 400:
            raise RuntimeError(_http_err("Fish Audio", r))
        if not r.content:
            raise RuntimeError("Fish Audio returned an empty audio file.")
        mime = r.headers.get("content-type", "audio/mpeg").split(";", 1)[0]
        return r.content, mime

    def test(self, api_key: str) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=_FISH_TIMEOUT) as c:
                r = c.get(
                    f"{_FISH_BASE}/wallet/self/api-credit",
                    headers=self._headers(api_key),
                )
            if r.status_code != 200:
                return False, _http_err("Fish Audio", r)
            credit = (r.json() or {}).get("credit")
            suffix = f" · credit {credit}" if credit not in (None, "") else ""
            return True, f"Connected{suffix}."
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"


# ───────────────────────── fal.ai adapter ─────────────────────────

_FAL_QUEUE_BASE = "https://queue.fal.run"
_FAL_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_FAL_MODELS = (
    CloudModel(
        "fal-ai/elevenlabs/tts/eleven-v3",
        "Eleven v3",
        "expressive · 70+ languages · inline audio tags",
    ),
    CloudModel(
        "fal-ai/elevenlabs/tts/turbo-v2.5",
        "Turbo v2.5",
        "low latency · multilingual",
    ),
    CloudModel(
        "fal-ai/elevenlabs/tts/multilingual-v2",
        "Multilingual v2",
        "high quality · multilingual",
    ),
)
_FAL_VOICES = (
    "Aria", "Roger", "Sarah", "Laura", "Charlie", "George", "Callum",
    "River", "Liam", "Charlotte", "Alice", "Matilda", "Will", "Jessica",
    "Eric", "Chris", "Brian", "Daniel", "Lily", "Bill", "Rachel",
)


class FalAudioAdapter(TTSAdapter):
    """fal's queue API returns opaque status/result/cancel URLs on submit.

    Those URLs are persisted in SubmitResult.metadata so restart recovery uses
    fal's exact route rather than reconstructing a model-dependent queue URL.
    """
    is_async = True

    @staticmethod
    def _headers(api_key: str) -> dict:
        return {
            "authorization": f"Key {api_key}",
            "accept": "application/json",
        }

    def list_models(self, api_key: str) -> list[CloudModel]:
        return list(_FAL_MODELS)

    def list_voices(self, api_key: str) -> list[dict]:
        return [
            {"id": name, "label": name, "lang": "", "gender": "", "preview_url": ""}
            for name in _FAL_VOICES
        ]

    def submit(self, api_key: str, text: str, model: str, voice: str,
               params: dict) -> SubmitResult:
        if not voice:
            raise ValueError("fal needs a voice name or id — tag a voice for this provider.")
        body = {
            "text": text,
            "voice": voice,
            "speed": max(0.7, min(1.2, float(params.get("speed", 1.0)))),
            "output_format": "mp3_44100_128",
            "apply_text_normalization": "auto",
        }
        for key in ("stability", "similarity_boost", "style", "language_code"):
            if params.get(key) not in (None, ""):
                body[key] = params[key]
        if params.get("seed") is not None and int(params["seed"]) >= 0:
            body["seed"] = int(params["seed"])
        url = f"{_FAL_QUEUE_BASE}/{model}"
        with httpx.Client(timeout=_FAL_TIMEOUT) as c:
            r = c.post(url, headers=self._headers(api_key), json=body)
        if r.status_code >= 400:
            raise RuntimeError(_http_err("fal", r))
        data = r.json() or {}
        task_id = str(data.get("request_id") or data.get("requestId") or "").strip()
        if not task_id:
            raise RuntimeError("fal did not return a request id.")
        metadata = {
            key: data[key]
            for key in ("status_url", "response_url", "cancel_url")
            if isinstance(data.get(key), str) and data[key]
        }
        if not metadata.get("status_url") or not metadata.get("response_url"):
            raise RuntimeError("fal did not return status and response URLs.")
        for value in metadata.values():
            _require_trusted_https_url("fal", value, ("queue.fal.run",))
        return SubmitResult(task_id=task_id, metadata=metadata)

    def poll(self, api_key: str, task_id: str,
             metadata: Optional[dict] = None) -> PollResult:
        metadata = metadata or {}
        status_url = str(metadata.get("status_url") or "")
        response_url = str(metadata.get("response_url") or "")
        if not status_url or not response_url:
            return PollResult(done=True, error="fal task recovery metadata is missing.")
        status = self._get_json(api_key, status_url)
        state = str(status.get("status") or "").upper()
        if state == "IN_QUEUE":
            return PollResult(done=False, progress=0.1)
        if state == "IN_PROGRESS":
            return PollResult(done=False, progress=0.5)
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            return PollResult(
                done=True,
                error=str(status.get("error") or status.get("message") or f"fal task {state.lower()}."),
            )
        if state != "COMPLETED":
            return PollResult(done=False, progress=0.25)
        result = self._get_json(api_key, response_url)
        payload = result.get("data") if isinstance(result.get("data"), dict) else result
        audio = payload.get("audio") if isinstance(payload, dict) else None
        audio_url = audio.get("url") if isinstance(audio, dict) else audio
        if not isinstance(audio_url, str) or not audio_url:
            return PollResult(done=True, error="fal completed without an audio URL.")
        content, mime = _download_provider_audio(
            "fal",
            audio_url,
            allowed_host_suffixes=("fal.media", "storage.googleapis.com"),
        )
        return PollResult(done=True, audio=content, mime=mime, progress=1.0)

    def cancel(self, api_key: str, task_id: str,
               metadata: Optional[dict] = None) -> None:
        cancel_url = str((metadata or {}).get("cancel_url") or "")
        if not cancel_url:
            return
        _require_trusted_https_url("fal", cancel_url, ("queue.fal.run",))
        with httpx.Client(timeout=_FAL_TIMEOUT) as c:
            c.put(cancel_url, headers=self._headers(api_key))

    def test(self, api_key: str) -> tuple[bool, str]:
        # GET the model endpoint: authentication is checked but generation only
        # occurs on POST, so the Settings test can never create a paid request.
        url = "https://fal.run/fal-ai/elevenlabs/tts/eleven-v3"
        try:
            with httpx.Client(timeout=_FAL_TIMEOUT) as c:
                r = c.get(url, headers=self._headers(api_key))
            if r.status_code >= 400:
                return False, _http_err("fal", r)
            return True, "Connected."
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _get_json(self, api_key: str, url: str) -> dict:
        _require_trusted_https_url("fal", url, ("queue.fal.run",))
        with httpx.Client(timeout=_FAL_TIMEOUT) as c:
            r = c.get(url, headers=self._headers(api_key))
        if r.status_code >= 400:
            raise RuntimeError(_http_err("fal", r))
        return r.json() or {}


def _require_trusted_https_url(
    provider: str,
    url: str,
    allowed_host_suffixes: tuple[str, ...],
) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in allowed_host_suffixes
    )
    if parsed.scheme != "https" or not allowed:
        raise RuntimeError(f"{provider} returned an untrusted URL.")


# ───────────────────────── Kie.ai adapter ─────────────────────────

_KIE_BASE = "https://api.kie.ai/api/v1"
_KIE_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_KIE_MODELS = (
    CloudModel(
        "elevenlabs/text-to-speech-multilingual-v2",
        "Multilingual v2",
        "high quality · multilingual",
    ),
    CloudModel(
        "elevenlabs/text-to-speech-turbo-2-5",
        "Turbo 2.5",
        "low latency · multilingual",
    ),
)


class KieAudioAdapter(TTSAdapter):
    """Kie Market TTS through createTask and unified recordInfo polling."""
    is_async = True

    @staticmethod
    def _headers(api_key: str) -> dict:
        return {
            "authorization": f"Bearer {api_key}",
            "accept": "application/json",
        }

    def list_models(self, api_key: str) -> list[CloudModel]:
        return list(_KIE_MODELS)

    def list_voices(self, api_key: str) -> list[dict]:
        # Kie accepts ElevenLabs names or ids but does not document a voice-list
        # endpoint. Offer its documented/default ElevenLabs names plus manual ids.
        return [
            {"id": name, "label": name, "lang": "", "gender": "", "preview_url": ""}
            for name in _FAL_VOICES
        ]

    def submit(self, api_key: str, text: str, model: str, voice: str,
               params: dict) -> SubmitResult:
        if not voice:
            raise ValueError("Kie.ai needs a voice name or id — tag a voice for this provider.")
        inp = {
            "text": text,
            "voice": voice,
            "stability": float(params.get("stability", 0.5)),
            "similarity_boost": float(params.get("similarity_boost", 0.75)),
            "style": float(params.get("style", 0)),
            "speed": max(0.7, min(1.2, float(params.get("speed", 1.0)))),
            "timestamps": False,
        }
        for key in ("previous_text", "next_text", "language_code"):
            if params.get(key) not in (None, ""):
                inp[key] = params[key]
        data = self._request(
            api_key,
            "POST",
            f"{_KIE_BASE}/jobs/createTask",
            body={"model": model, "input": inp},
        )
        task_id = str((data.get("data") or {}).get("taskId") or "").strip()
        if not task_id:
            raise RuntimeError("Kie.ai did not return a task id.")
        return SubmitResult(task_id=task_id)

    def poll(self, api_key: str, task_id: str,
             metadata: Optional[dict] = None) -> PollResult:
        data = self._request(
            api_key,
            "GET",
            f"{_KIE_BASE}/jobs/recordInfo",
            params={"taskId": task_id},
        ).get("data") or {}
        state = str(data.get("state") or "").lower()
        try:
            progress = max(0.0, min(1.0, float(data.get("progress") or 0) / 100.0))
        except (TypeError, ValueError):
            progress = 0.0
        if state in {"fail", "failed", "error", "cancelled", "canceled"}:
            return PollResult(
                done=True,
                error=str(data.get("failMsg") or data.get("failCode") or "Kie.ai task failed."),
            )
        if state != "success":
            return PollResult(done=False, progress=progress)
        payload = data.get("resultJson") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = {}
        urls = payload.get("resultUrls") if isinstance(payload, dict) else None
        audio_url = str(urls[0] if isinstance(urls, list) and urls else "").strip()
        if not audio_url:
            return PollResult(done=True, error="Kie.ai completed without an audio URL.")
        audio, mime = _download_provider_audio(
            "Kie.ai",
            audio_url,
            allowed_host_suffixes=("kie.ai", "aiquickdraw.com"),
        )
        return PollResult(done=True, audio=audio, mime=mime, progress=1.0)

    def test(self, api_key: str) -> tuple[bool, str]:
        try:
            data = self._request(api_key, "GET", f"{_KIE_BASE}/chat/credit")
            credit = data.get("data")
            suffix = f" · credit {credit}" if credit not in (None, "") else ""
            return True, f"Connected{suffix}."
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _request(
        self,
        api_key: str,
        method: str,
        url: str,
        *,
        body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        with httpx.Client(timeout=_KIE_TIMEOUT) as c:
            r = c.request(
                method,
                url,
                headers={
                    **self._headers(api_key),
                    **({"content-type": "application/json"} if body is not None else {}),
                },
                json=body,
                params=params,
            )
        if r.status_code >= 400:
            raise RuntimeError(_http_err("Kie.ai", r))
        data = r.json() or {}
        if data.get("code") not in (None, 200):
            raise RuntimeError(
                f"Kie.ai API {data.get('code')}: {data.get('msg') or 'request failed'}"
            )
        return data


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
    "genaipro": Provider(
        key="genaipro",
        name="GenAIPro",
        adapter=GenAIProAdapter(),
        env_var="VOICESTUDIO_GENAIPRO_API_KEY",
        docs_url="https://docs.genaipro.io/#description/authentication",
        supports_live_listing=False,
        curated_models=_GENAIPRO_MODELS,
    ),
    "fish": Provider(
        key="fish",
        name="Fish Audio",
        adapter=FishAudioAdapter(),
        env_var="VOICESTUDIO_FISH_API_KEY",
        docs_url="https://fish.audio/app/api-keys/",
        supports_live_listing=False,
        curated_models=_FISH_MODELS,
    ),
    "fal": Provider(
        key="fal",
        name="fal.ai",
        adapter=FalAudioAdapter(),
        env_var="VOICESTUDIO_FAL_API_KEY",
        docs_url="https://fal.ai/dashboard/keys",
        supports_live_listing=False,
        curated_models=_FAL_MODELS,
    ),
    "kie": Provider(
        key="kie",
        name="Kie.ai",
        adapter=KieAudioAdapter(),
        env_var="VOICESTUDIO_KIE_API_KEY",
        docs_url="https://kie.ai/api-key",
        supports_live_listing=False,
        curated_models=_KIE_MODELS,
    ),
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
