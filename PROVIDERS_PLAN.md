# Voice Studio — Cloud Audio-Provider Gateway · Build Plan

> **Vision:** Turn Voice Studio into an **audio gateway**. Alongside the local TTS
> engines, it exposes cloud providers (ElevenLabs, fal, Fish Audio, kie, …) behind
> the SAME `/api/generate` contract Story Studio already calls. Story Studio links
> **one** connection and sees a single, always-current list of local **and** cloud
> models. Adding/removing models happens by linking a provider, not by editing
> Story Studio. This mirrors the pattern Chat Studio already uses for LLMs
> (`chatstudio-mac.git/app/backend/providers.py` + `router.py`).

Repo: `~/pinokio/api/voicestudio-mac.git` (this app). Reference: `~/pinokio/api/chatstudio-mac.git`.

---

## 0. How to resume on a fresh session

1. Read this file, then read the code it references (below) to confirm nothing drifted.
2. Voice Studio is a **live production app** on `http://localhost:47870` — **never kill/restart it**. Verify frontend changes by `curl` against 47870 (served no-cache) or in the browser; verify backend changes by **boot-testing a second instance on a temp port** (see §7), never against the live server.
3. Backend changes only go live after the user clicks **Update** in the Pinokio sidebar (restart). Frontend changes are live on browser reload. The UI must **degrade gracefully** until the backend restarts.
4. Ship each slice: bump `VERSION`, prepend a `CHANGELOG.md` entry, `git add` only your files, commit, `git push origin main`. Follow the existing changelog voice.
5. Current state as of this plan: **v1.11.0** — Phase 0 + Phase 1 **backend** done. Next up: **Phase 1 frontend** (§4).

---

## 1. Status snapshot

| Piece | State | Where |
|---|---|---|
| `providers.py` (adapter interface + registry) | ✅ done | `app/backend/providers.py` |
| ElevenLabs adapter (sync) | ✅ done | `providers.py → ElevenLabsAdapter` |
| Self-healing job fields + `_run_cloud` worker | ✅ done | `app/backend/generation.py` |
| Cloud routing in `start_txt2speech` + catalog merge + mp3 serving | ✅ done | `app/backend/main.py` |
| `/api/providers*` endpoints | ✅ done | `app/backend/main.py` |
| **Settings → Providers UI** (key/paid/test/enable) | ⬜ **NEXT** | `app/frontend/*` |
| **Voice-library provider tags** (multi-provider) | ⬜ **NEXT** | `voices.py` + `app/frontend/*` |
| **Cloud models in the Generate UI** | ⬜ **NEXT** | `app/frontend/*` |
| fal adapter (async submit/poll) | ⬜ Phase 2 | `providers.py` |
| Fish Audio adapter | ⬜ Phase 2 | `providers.py` |
| kie adapter | ⬜ Phase 3 | `providers.py` |
| Fleet "provider health" surface (Hub) | ⬜ Phase 3 | `studiohub-mac` |

---

## 2. Decisions locked (from the user)

- **Voices = the existing voice library, tagged per provider.** A single voice can be
  tagged for **several** providers at once (fal, kie, genaipro, ElevenLabs), because
  those providers largely resell the **same ElevenLabs models** (fal has a wider voice
  library). The tag stores, per provider, the provider-native voice id.
- **kie and fal are essentially ElevenLabs-model resellers** — the underlying model
  catalog overlaps heavily; the difference is the voice library breadth + pricing.
- **Output format:** store the provider's **native MP3**, serve as-is. No transcoding
  (avoids an encoder dependency).
- **Paid consent:** a cloud model surfaces only with a saved key **AND** an explicit
  per-provider **paid** toggle **AND** enabled. "A key alone is not consent to spend."
- **Self-healing / never double-charge:** persist the provider task id on the job;
  retries (and, for async providers, restart recovery) **re-poll** that id instead of
  re-submitting. Plus a per-request character cap.
- **Model concept = engine + voice** (like local), surfaced through the existing
  `/api/voices` + model list — not a combinatorial explosion of model×voice entries.

---

## 3. Architecture (as built)

**Synthetic id:** a cloud model is `provider:<key>:<model_id>` (e.g.
`provider:elevenlabs:eleven_multilingual_v2`). `providers.parse_id()` returns
`(key, model)` for those and `None` for local repos — that's the router.

**Adapter interface** (`providers.TTSAdapter`, runs in a generation **thread**, blocking httpx is fine):
```
is_async: bool                                   # True → submit()/poll(); False → synthesize()
list_models(api_key) -> [CloudModel]             # live-fetched, TTL-cached
list_voices(api_key) -> [{id,label,lang,gender,preview_url}]   # optional
synthesize(api_key, text, model, voice, params) -> (bytes, mime)   # sync providers
submit(api_key, text, model, voice, params) -> SubmitResult(task_id)   # async providers
poll(api_key, task_id) -> PollResult(done, audio, mime, error, progress)
cancel(api_key, task_id) -> None                 # best-effort
test(api_key) -> (ok, message)
```

**Registry:** `providers.PROVIDERS: dict[key, Provider]`. `Provider(key, name, adapter,
env_var, docs_url, supports_live_listing, always_paid, curated_models)`.

**Settings-backed state** (in `settings.json` under key `"providers"`):
`{ "<key>": { "api_key", "paid", "enabled" } }`. Helpers in `providers.py`:
`get_api_key / has_key / paid_enabled / is_enabled / is_live / set_key / set_paid /
set_enabled`. `is_live(key) == enabled AND has_key AND paid_enabled` — this gate is
what makes a model visible/usable.

**Live listing:** `models_for_provider(key, force=False)` — TTL-cached (300s) live fetch
when the provider has a key + `supports_live_listing`, else the curated fallback. Never
raises. `force=True` bypasses the cache (used by `/models/live`).

**Job model** (`generation.GenerationJob`): added `provider: Optional[str]` and
`provider_task_id: Optional[str]`. Both are serialized to disk (`_to_disk`/`_from_disk`)
and `provider` is in the public `serialize()`. `start_txt2speech` sets `job.provider`
from `parse_id(repo)`. `_run_txt2speech`: if `job.provider` → `_run_cloud(job)`, else the
local dispatch.

**`_run_cloud(job)`** (`generation.py`): validates `is_live`, enforces a **5000-char cap**,
then: sync adapter → `synthesize()` → write bytes; async adapter → submit **once**,
persist `provider_task_id` **before** polling, then `poll()` until done (recall-safe).
Writes `output/<job_id>.mp3` (or `.wav`). Everything else (history, SSE, per-job actions)
is shared with local jobs.

---

## 4. NEXT — Phase 1 frontend (make ElevenLabs usable in the UI)

Voice frontend is vanilla Alpine.js: `app/frontend/{index.html, app.js, style.css}`,
served no-cache. Study the existing Settings tab, the Generate model dropdown, and the
Voices library tab first — mirror their conventions (and note earlier work already added
a webview-safe `askConfirm()` modal + `pushToast`).

**4a. Settings → Providers panel.** For each provider from `GET /api/providers`
(`{providers:[{key,name,docs_url,has_key,paid,enabled,live,models:[...]}]}`):
- API-key password input → `POST /api/providers/{key}/key {api_key}`.
- A **paid** toggle → `POST /api/providers/{key}/paid {value}` (label it clearly:
  "Enable paid usage — this provider bills per use").
- An enable/disable toggle → `POST /api/providers/{key}/enabled {value}`.
- A **Test** button → `POST /api/providers/{key}/test {api_key?}` → show `{ok,message}`.
- Show live model count + a "refresh models" action → `GET /api/providers/{key}/models/live`.
- Link `docs_url` ("get a key").

**4b. Voice-library provider tags.** Extend `voices.py` `Voice` dataclass with
`providers: list = field(default_factory=list)` where each entry is
`{ "provider": "<key>", "voice_id": "<provider-native id>" }` (a voice can be tagged for
several). It auto-persists via `asdict(voice)` → `metadata.json`. Add to the existing
update path (there's an `update()` method) + an endpoint (e.g. `PUT
/api/voices/{id}/providers`). Frontend: in the Voices tab, let the user tag a voice for a
provider and paste/select that provider's voice id (offer `list_voices` results to pick
from). `_from_disk`/loader must default `providers` to `[]` for old voices.

**4c. Cloud models in Generate.** `/api/catalog` already returns cloud models
(`kind:"cloud"`, `cache:{state:"cloud"}`, `provider`, `repo`). In the Generate model
dropdown, show them (grouped "Cloud" vs "Local"). When a cloud model is selected, the
voice picker must offer voices **tagged for that provider**, and submit
`txt2speech` with `repo = provider:key:model` and `voice = <that provider's voice_id>`.
The backend already routes it. Handle graceful degradation: if the running server predates
this (endpoints 404), hide the Providers panel / cloud models.

**Acceptance:** with a real ElevenLabs key entered + paid on, an ElevenLabs model appears
in Generate, a tagged voice can be picked, and generating produces an MP3 in history with
working play/download/reveal — over the existing job engine.

---

## 5. Phase 2 — fal + Fish Audio (async is where self-healing matters)

- **fal** (`fal.ai`) — **async queue** API: submit → `request_id` → poll status → result.
  Implement as `is_async = True`: `submit()` returns `SubmitResult(request_id)`, `poll()`
  maps queued/in-progress→`done=False` (with `progress`), completed→`done=True` with the
  audio (download the result URL), failed→`error`. This is exactly what the persisted
  `provider_task_id` + submit-once-poll design was built for. Reuse the base URL pattern
  from Chat's fal entry. fal has a **wider voice library** — surface it via `list_voices`.
  Also add **restart recovery**: persist in-flight cloud jobs (currently `_persist` only
  saves terminal jobs) and, on startup after `_load_history`, re-poll any running job that
  has a `provider_task_id` instead of re-submitting.
- **Fish Audio** — REST TTS with a reference-model concept; write `synthesize` (likely
  sync) + `list_models`/`list_voices`.
- Register both in `PROVIDERS`; the router, catalog merge, endpoints, and UI all work
  unchanged — only the adapter is new.

## 6. Phase 3 — kie + fleet health

- **kie** (`kie.ai`) — resells ElevenLabs models; adapter maps its REST shape. Curate
  models if it has no clean listing endpoint.
- **Fleet health:** surface per-provider live/linked status to Story Studio / Studio Hub
  so the fleet shows which cloud providers are connected and current.

---

## 7. Conventions & gotchas (do not skip)

- **Live production app.** Don't restart voicestudio (47870). Boot-test backend changes on
  a temp port: `PYTORCH_ENABLE_MPS_FALLBACK=1 conda_env/bin/python -m uvicorn
  backend.main:app --app-dir app --host 127.0.0.1 --port 47999`, curl, then kill. Model
  loading is lazy, so the endpoints answer without a full model load.
- **Backend activates on Update** (restart). No new deps beyond `httpx` (already in
  `app/requirements.txt`). MINOR bump when a phase adds a feature.
- **Never double-charge:** any new adapter that costs credits MUST use the
  submit-once/persist-task-id/re-poll path for async, and rely on the char cap. Verify
  with a fake key (graceful 401, no crash, curated fallback) before shipping — the
  ElevenLabs adapter is the reference.
- **Frontend degrades gracefully** when the backend predates the change (endpoints 404):
  hide the feature, show a "run Update once" hint — see how `refreshOutputStats` /
  delete-generation already do this in `app.js`.
- **Verify before claiming done.** Syntax (`node --check app/frontend/app.js`,
  `conda_env/bin/python -m py_compile app/backend/*.py`), then a real request.
- **Commit hygiene:** stage only your files (there's a pre-existing, already-committed
  `<app>-serve.sh` set — don't touch it), descriptive message, push.

---

## 8. Quick reference — endpoints already live (after Update)

```
GET  /api/providers                      → {providers:[{key,name,docs_url,has_key,paid,enabled,live,models}]}
POST /api/providers/{key}/key            {api_key}      → serialize_provider(key)
POST /api/providers/{key}/paid           {value:bool}   → serialize_provider(key)
POST /api/providers/{key}/enabled        {value:bool}   → serialize_provider(key)
POST /api/providers/{key}/test           {api_key?}     → {ok, message}
GET  /api/providers/{key}/models/live                   → {models:[{id,label,notes,repo}]}
GET  /api/catalog                        → now includes cloud models (kind:"cloud")
POST /api/generate/txt2speech            {repo:"provider:elevenlabs:<model>", voice:"<voiceid>", text}
```
Generation, jobs, history, SSE stream, per-job reveal/delete, disk stats/prune — all
shared with local generation, unchanged.
