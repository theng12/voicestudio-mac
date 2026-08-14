# VoiceStudio (Mac)

Apple Silicon text-to-speech studio. Sibling app to **ImageStudio Mac** (FLUX image generation) and **MusicStudio Mac** (MusicGen / Stable Audio). Same scaffolding, focused on TTS.

> **Current status**: local TTS generation, voice cloning, transcription, and model management are available from one UI and API. Voice Studio is local-only — cloud TTS providers were removed in 1.33.0.

## What it does

- **Catalog of focused local models** across 18 families, including Qwen3-TTS,
  Chatterbox, OmniVoice, Fish Audio S2 Pro, VoxCPM2, Kokoro, F5-TTS, Spark-TTS,
  Bark, Orpheus, KittenTTS, VibeVoice, Voxtral, Marvis, Audio8 TTS Preview,
  MOSS-TTS-Nano, Echo-TTS, and LongCat AudioDiT.
- **Apple Silicon first** — the priority families use curated MLX tiers instead
  of presenting every redundant precision. Qwen3 includes 0.6B and 1.7B Base
  voice cloning, preset speakers, and VoiceDesign. Long Qwen scripts are
  automatically rendered in short sentence-aware sections and joined into one
  chapter file entirely inside Voice Studio. Because the current
  MLX Qwen engine ignores its native speed argument, Voice Studio applies the
  selected pace to the finished WAV with pitch-preserving tempo adjustment.
  The 1.7B Qwen tiers require a 16 GB Mac; 0.6B remains the qualified 8 GB tier.
  Chatterbox, OmniVoice, and Fish Audio S2 Pro expose their native cloning and
  quality controls. Fish S2 Pro is a high-memory research/non-commercial model;
  its 8-bit tier is the practical 24 GB candidate and its bf16 tier is for 32 GB+.
  LongCat AudioDiT 1B 4-bit is a 16 GB+ internal cloning candidate using the
  shared MLX worker; it remains outside GenStudio routing until multi-voice
  long-form listening qualification passes.
  Kokoro keeps one
  full-quality MLX model with all 54 voices, nine language variants, speed, and
  equal voice blending. VoxCPM2 keeps a fast 4-bit tier and a bf16 final-render
  tier, both with voice design, transcript-aware cloning, sentence-safe long-form
  rendering, and exact pitch-preserving final tempo control. Bark uses its current
  native MLX conversion with all 130 multilingual presets and complete sampling controls.
- **Smart downloads** — filters out redundant duplicate weight formats,
  recognizes an already-complete immutable snapshot without creating another
  history entry, and uses resumable classic HTTP by default after Xet stalls
  were observed on fleet downloads. Set `VOICESTUDIO_ENABLE_XET=1` only on a
  diagnosed machine to opt back in. F5-TTS goes from 6.3 GB → 1.3 GB, Bark
  avoids more than 4 GB of duplicate preset files, and Chatterbox goes from
  11 GB → 3 GB.
- **Resume on retry** — partial downloads pick up where they left off.
  A normal partial is preserved until it finishes; proven-stale leftovers are
  cleaned after success, and a transfer with no byte progress for 15 minutes
  automatically receives one fresh resumable attempt on the next fleet check.
- **Imports** — link or move TTS weights from other launchers (e.g. a standalone VoxCPM webui).
- **Hub-managed shared voices** — Studio Hub can securely install one reference
  voice under the same stable ID, audio hash, and transcript on every Voice
  Studio Mac. Existing machine-local voices are protected from collisions.
- **Direct API** — bound on `0.0.0.0:47870`, hit it from your main Mac over LAN, Tailscale, or anywhere on the network.

## How to use

1. Install: click **Install** in the Pinokio sidebar (creates the conda env).
2. Start: click **Start** (runs uvicorn on port 47870 across all interfaces).
3. Click **Open UI** to see the catalog. Pick models from **Models** → **Download**.
4. **Install Generation** (the ✨ wand sidebar item) to enable generation.
   The same action stays visible as **Reinstall Generation** while Voice Studio
   is running, including startup-service mode; it stops/restarts the appropriate
   server automatically. **What's New** is also always available in the sidebar
   and displays the installed checkout's complete release notes offline.
5. Use **Models → Storage & dependencies** to see the actual on-disk model
   families, required tokenizers/codecs, missing companions, legacy packages,
   and safe removal actions. Existing Hugging Face downloads are indexed in
   place and are never moved or downloaded again just to appear in this view.

### Local-only boundary

Voice Studio synthesises with local Apple Silicon engines only. The former
hosted-provider endpoints, credential storage, voice-provider metadata, and
cloud-job history schema are absent. A stale request whose `repo` starts with
`provider:` receives a clear `400` before any local engine or catalog check.
Unknown legacy settings are removed automatically when settings load.

### Local generation memory protection

Direct local generation checks live free unified memory before loading or
running a model. If the available headroom is too small, the job is stopped
before inference with a clear message instead of pushing the Mac into swap or a
Metal allocation failure. If MLX/MPS still reports an allocation failure, Voice
Studio clears both engine caches and retries that job once. Two consecutive
allocation failures restart Voice Studio automatically when the startup service
is installed; launchd then brings it back. Normal Pinokio foreground runs stay
open so they can be inspected or restarted manually.

Operators can inspect the current state at `GET /api/generate/memory`, or find
the same snapshot under `GET /api/generate/diagnostics` → `memory`.

Each local TTS job also carries versioned `resource_usage` evidence while it is
running and after it becomes terminal. Voice Studio samples the host's lowest
available unified memory, peak memory percentage and pressure level, swap
activity, Voice Studio process-tree RSS, and MLX active/cache/peak allocation.
The terminal summary records whether a memory failure or supervised restart was
observed and whether the model remained loaded. These are measurements from the
exact attempt—not an inferred minimum-RAM declaration—and persist in job
history across restarts.

`GET /api/health` reports whether Voice Studio is busy, the exact loaded model
and runtime slot, live host memory, a `process` block (`pid`, `started_at`,
`started_at_iso`, `uptime_seconds`) recording when this process started, and
read-only `restart_health` evidence with 24-hour/seven-day watchdog restart
counts and alert severity. The two restart readings are deliberately separate:
`restart_health` only sees restarts the watchdog performed, so a deliberate
upgrade or `launchctl` bounce leaves `last_restart_at` null, while `process`
is always populated. The same restart signal is included in
`GET /api/generate/diagnostics`; it never changes service state or marks an
otherwise healthy worker unavailable. Every local
`/api/catalog` row reports dependency readiness, downloaded availability,
loaded state, the cold/loaded free-memory requirements, the minimum total
unified memory, and whether the
model is eligible on the current machine at that moment.

Settings now also provides model-memory modes. Fresh installs use
**Immediate** so model memory is released after each completed local task and
the Mac is ready for another sibling Studio; an explicit operator choice always
wins. **Performance** preserves loaded local TTS and Whisper models for faster
repeat work and never releases on idle. Balanced unloads after 10 idle minutes
and Memory Saver after 2 minutes. **Release Memory / Unload Model** manually
releases both caches when no generation or transcription is active. Weights,
shared voices, clone references, and outputs remain on disk. The same controls
are available through `GET/PUT /api/memory-policy` and
`POST /api/memory/release`, which also report `release_count` alongside
`counters_since` and a `process` block — the counters are in-process and reset
on restart, so a zero is only readable next to the process start it belongs to.

### Local output retention

Generated speech files are temporary local backups. Automatic cleanup is
enabled by default, keeps completed files for three days, and enforces an 80 GB
hard cap by deleting the oldest completed outputs first. Shared voice masters,
clone references and transcripts, active jobs, uploads, model caches,
credentials, and settings are never eligible.

The Generate page exposes the same policy used by Studio Hub:

```text
GET  /api/storage-policy
PUT  /api/storage-policy          # { enabled, retention_days, max_gb }
POST /api/storage-policy/cleanup  # optional { target_bytes }
```

## Automatic updates (optional)

Open **Settings → Automatic updates** to choose:

- **Off** — the default. No updater schedule is loaded.
- **Notify only** — checks on your daily or weekly schedule and sends one useful
  notification when a new version is available.
- **Download and install automatically** — installs only after Voice Studio is
  idle, then restarts and verifies the mode that was actually active.

The default maintenance time is 02:00, staggered from the sibling Studios. Keep
**Update only while idle** enabled: generation, queued work, model loading,
transcription, and downloads defer the update without cancelling anything. Use
**Update after current work** for a one-time automatic retry even while the
regular mode is Off.

Every install requires the expected GitHub origin, `main`, a clean worktree, a
fast-forward update, and enough disk space. Local edits are never discarded.
After dependencies install, Voice Studio must pass its import check, health
endpoint, and running-version check before success is reported. A failed update
makes one bounded rollback attempt and clearly reports whether the previous
version recovered. Technical logs are rotated under `logs/auto_update/`.

Saving preferences validates the LaunchAgent separately; the Settings panel says
**Installed & verified** only after launchd accepts it. Turning the mode Off
unloads and removes that schedule immediately. If the updater enters Repair,
open the technical details, fix the named Git/service issue, then choose Retry.

## Versioning

Voice Studio KH uses [Semantic Versioning](https://semver.org/) with this project-specific interpretation:

- **MAJOR** (1.x.x → 2.x.x) — breaking change. Re-install required.
- **MINOR** (1.1.x → 1.2.x) — new engine / feature / model family. **Re-run "Install Generation"** to pick up any new Python deps.
- **PATCH** (1.2.0 → 1.2.1) — bugfix / UI tweak / catalog entry within an existing family. **Just run "Update"** from the Pinokio sidebar.

Current version is stored at the project root in [`VERSION`](VERSION). The full release history with what changed in each version lives in [`CHANGELOG.md`](CHANGELOG.md).

Every shipped app, catalog, launcher, dependency, service, or worker-contract
change must increase `VERSION` and add a clear top changelog entry. Run
`python3 release_metadata_check.py` before committing: it verifies that the
installed version and **What's New** entry agree, and that product changes have
both release files and a numerically higher semantic version. Use a patch bump for compatible fixes/small changes, a
minor bump for features, engines, or model families, and a major bump for a
breaking or reinstall-required change.

The WebUI version area includes **What's New**, which opens the installed release history in a modal without leaving Voice Studio.

The WebUI footer shows the running version. The same value is also surfaced at:

- `GET /api/version` → `{"app_version": "1.0.0", "title": "Voice Studio KH"}`
- `GET /api/health` → includes `app_version`
- `GET /api/generate/diagnostics` → includes `app_version`
- `GET /api/auto-update/status` → public updater settings and state (secrets redacted)
- `GET /api/auto-update/readiness` → idle state and active-work reasons
- `POST /api/auto-update/settings` → save and validate the opt-in schedule
- `POST /api/auto-update/check` → run a safe version check
- `POST /api/auto-update/update` → update now or pass `{"after_current":true}`
- `POST /api/auto-update/retry` → retry a failed update

## Truth audit (for contributors)

The Models tab shows a green "✓ engine ready" chip per model. That chip is driven by the `_WIRED_FAMILIES` set in `app/backend/generation.py`. If a family is in `_WIRED_FAMILIES` but its dispatch branch raises `NotImplementedError`, users see a green chip and then hit a wall when they click Generate.

To prevent that drift, run the truth audit before any release that touches `generation.py`:

```
python3 audit_truth.py            # human-readable report
python3 audit_truth.py --strict   # exits non-zero on drift (for CI)
```

The script reads `app/backend/catalog.py` + `app/backend/generation.py` via AST and reports four kinds of drift: commission lies, omission lies, orphan families, and phantom wires. It also handles the `MLX_AUDIO_FAMILIES` config-table pattern used here (where one worker handles N families dynamically).

No deps beyond stdlib — runs without the venv.

## Model audit evidence

Exact checkpoint audits live under `model-audits/<run-id>/`. A valid record
binds its controls, limits, adapter, hardware requirements, operation set, and
immutable model revision to a canonical SHA-256 contract hash.

Passed records are surfaced additively as `genstudio_candidate` on the matching
`GET /api/catalog` or `GET /api/transcribe/availability` row. The sibling only
asserts that the checkpoint passed its local audit and may be considered as a
candidate. It never emits `approved_for_genstudio`; Studio Hub remains the
separate authority that deliberately exposes an exact audited contract.

Consumers should also require `genstudio_candidate_runtime_match: true` before
treating the local cache as evidence for that candidate revision. Normal cache,
runtime-ready, memory, busy, and fleet-health signals remain separate machine
observations rather than being folded into the immutable contract.

## API

Once running, the API is at `http://<your-mac-ip>:47870`. Examples:

### JavaScript

```js
// List the catalog
const r = await fetch("http://localhost:47870/api/catalog");
const { models, families } = await r.json();

// Start a download. An already-complete matching snapshot returns
// { job: null, already_cached: true, cache: ... } instead of another history row.
const download = await fetch("http://localhost:47870/api/downloads", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ repo: "mlx-community/Kokoro-82M-bf16" }),
}).then(r => r.json());

// Watch download progress (SSE)
const es = new EventSource("http://localhost:47870/api/downloads/stream");
es.onmessage = (e) => console.log(JSON.parse(e.data));
```

### Python

```python
import requests

# List catalog
r = requests.get("http://localhost:47870/api/catalog").json()
for m in r["models"]:
    print(m["repo"], m["size_gb"], "GB", m["cache"]["state"])

# Start a download
requests.post(
    "http://localhost:47870/api/downloads",
    json={"repo": "mlx-community/Kokoro-82M-bf16"},
)
```

### curl

```bash
# Catalog
curl http://localhost:47870/api/catalog | jq .

# Dependency-aware inventory of the existing Hugging Face cache
curl http://localhost:47870/api/model-storage | jq .

# Remove one complete package after active-work and dependency safety checks
curl -X DELETE http://localhost:47870/api/model-storage/owner/repository | jq .

# Start a download
curl -X POST http://localhost:47870/api/downloads \
  -H "content-type: application/json" \
  -d '{"repo":"mlx-community/Kokoro-82M-bf16"}'

# Watch downloads via SSE
curl -N http://localhost:47870/api/downloads/stream
```

### Studio Hub fleet voice contract

Studio Hub uses two authenticated maintenance endpoints; normal users add and
transcribe shared voices in Hub rather than calling these directly:

- `PUT /api/voices/{stable_12_hex_id}/fleet-sync` — multipart audio, SHA-256,
  metadata, permission acknowledgement, and optional transcript. Repeating the
  same ID and hash is safe.
- `DELETE /api/voices/{stable_12_hex_id}/fleet-sync?audio_sha256=...` — removes
  only an exact Hub-managed copy. It refuses machine-local voices and hash
  mismatches.

Remote calls require the fleet's `X-Studio-Token`, an equivalent Bearer header,
or the protected session cookie established after successful authentication.
Voice Studio rejects query-string credentials such as `?token=...` so fleet
secrets do not leak through browser history, access logs, or copied links.
Studio Hub uses `X-Studio-Token` for direct Studio calls and `X-Hub-Token` for
controller-proxied calls. Generated embeddings are intentionally not
distributed.

### Private GenStudio reference execution

Customer uploads do not enter the operator Shared Voices library. Studio Hub
temporarily transports the exact bytes to
`POST /api/generate/txt2speech/reference` as multipart `audio`, `request_json`,
the source checksum, optional ordered transcript segments, and the source
expiry. The endpoint accepts only local clone-capable models and refuses a
simultaneous `voice_library_id`.

Voice Studio reads the exact model audit's `input_limits.reference_audio`
profile when present. It decodes the upload, removes surrounding silence,
selects a duration-compatible speech window, resamples and normalizes a mono
PCM WAV, slices timestamped transcript evidence, and caches the derived copy by
source checksum + model + audit profile + preparation revision. An unaudited
model keeps its established adapter fallback until a grounded Group audit
publishes exact limits.

Stable errors such as `REFERENCE_AUDIO_TOO_SHORT`,
`REFERENCE_TRANSCRIPT_REQUIRED`, and
`REFERENCE_TRANSCRIPT_ALIGNMENT_REQUIRED` are returned as machine-readable
`detail.code` values. Successful jobs report source and derived checksums,
preparation revision, selected duration, long-form strategy, and chunk count;
private filesystem paths and customer text never enter the public job payload
or generation start log.

### Final TTS artifact contract

Qwen3-TTS (preset, clone, and VoiceDesign), VoxCPM2, Kokoro, Chatterbox,
OmniVoice, VibeVoice, Fish Audio S2 Pro, Audio8 TTS Preview, and MOSS-TTS-Nano
accept one logical long-form request. Voice Studio alone splits it at
sentence-safe boundaries, renders private temporary sections, validates every
section, and joins them into one WAV. Qwen, VoxCPM2, VibeVoice, Fish Audio
S2 Pro, Audio8, and MOSS-TTS-Nano apply the
requested pitch-preserving speed adjustment once to that joined WAV; Kokoro
uses its native synthesis-speed control consistently in every private section.
Temporary section files never have an API route and are deleted before the job
becomes terminal. GenStudio may therefore offer a 40,000-character customer
request without exposing the models' shorter internal synthesis windows.

`GET /api/generate/jobs/{id}` exposes `output_url` only after the final WAV has
passed validation and been atomically published. Successful local Qwen/VoxCPM2
jobs include the internal model repository, immutable cached runtime revision,
applicable voice-library ID and audio-hash voice revision, runtime, decoded
duration, sample rate, channels, byte size, SHA-256, media type, and format.
Studio Hub supplies the assigned worker identity and independently verifies the
same final bytes; GenStudio verifies them again before durable publication.
Live progress includes `chunk_index` and `chunk_total`, and cancellation is
checked between private sections. A model qualifies as sellable long-form when
the complete adapter-managed request passes; the raw checkpoint does not need
to accept 40,000 characters in one native call. Local jobs additionally expose
the worker-owned `voicestudio.resource-telemetry` v1 summary so fleet
qualification can compare the same exact evidence on 8, 16, and 24 GB machines.
The worker-owned part of this boundary lives in
`app/backend/voicestudio_genstudio_integration.py`; add future VoiceStudio
evidence fields there with a regression test.

### Qwen 1.7B Base section size

The Generate tab exposes an optional **Long-form delivery → Section size**
control only for the audited
`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` checkpoint. Auto keeps the
audited 400-character section size. Custom accepts whole numbers from 230
through 400 and remembers the choice with that model's existing Generate
settings. Other models do not show this control and cannot receive a custom
section-size override.

Voice Studio continues to choose and apply the 300/600/180 ms sentence,
paragraph, and soft-split pauses automatically; those pacing safeguards are
not user-adjustable. API callers omit `section_max_characters` for Auto, or
send an integer `section_max_characters` for Custom. Invalid, out-of-range, or
unsupported values are rejected before generation is queued. This is a Voice
Studio-local optional control and does not change the GenStudio contract.

## Folder layout

```
voicestudio-mac/
├── app/
│   ├── backend/        # FastAPI server (Python)
│   ├── frontend/       # Single-page UI (Alpine.js, no build step)
│   ├── requirements.txt
│   └── requirements-generation.txt
├── install.js          # Sets up conda env + Phase 1 deps
├── install_generation.js  # Adds heavy Phase 2 deps (torch, transformers, diffusers)
├── start.js            # Launches uvicorn on port 47870
├── update.js           # git pull + reinstall Phase 1 deps
├── auto_update/        # ignored per-machine updater config/status (created on use)
├── reset.js            # Nuke the conda env
├── pinokio.js          # Sidebar menu
├── pinokio.json        # Pinokio metadata
└── ENVIRONMENT         # HF_HOME and share-proxy config
```

## Ports

VoiceStudio uses **port 47870** so it doesn't clash with ImageStudio (47868) or MusicStudio (47869). All three can run simultaneously.

## Run as an always-on server (auto-start + self-healing)

By default you start the app by opening Pinokio and clicking **Start**. If instead you want this Mac to behave like a **server** — the API always up, started automatically on boot, and self-healing — use the one-click service.

### Turn it on
In the Pinokio sidebar click **❤️ Install as Startup Service**. That's it. It:

- Installs a macOS **launchd LaunchAgent** that runs the server (`serve.sh`) on **port 47870**.
- **Starts automatically** every time you log in (so it comes back after a reboot).
- **Restarts itself if it crashes** (launchd `KeepAlive`).
- Adds a **health watchdog** that pings `/api/health` every 60s and relaunches the server if it ever hangs (alive-but-not-responding).

No admin/sudo needed for this step — it's a per-user agent. To remove it later, click **Startup Service: ON — click to remove**.

Logs live in `logs/service/`. Reach the API over Tailscale/LAN at `http://<this-mac>:47870`.

> Use the **service OR** Pinokio's **Start** button — not both. They share port 47870, so running both makes them fight over it.

### One-time Mac settings for full power-cut recovery (why they matter)
The service handles *software* restarts. To survive an actual **power outage** with zero human steps, each Mac also needs three system settings (admin-level, done once — the button does **not** change these):

1. **Power back on automatically when electricity returns**
   ```bash
   sudo pmset -a autorestart 1
   ```
   *Why:* otherwise the Mac just stays off after the power drops and comes back. This tells it to boot itself the moment power is restored.

2. **Enable Automatic login** — System Settings ▸ Users & Groups ▸ *Automatically log in as …*
   *Why:* the Apple GPU (Metal / MLX) is **only available inside a logged-in session**. A service that starts before login can't use the GPU, so the models would fail or fall back to slow CPU. Auto-login gets the Mac into a real session by itself.

3. **Turn FileVault OFF** — System Settings ▸ Privacy & Security ▸ FileVault
   *Why:* with FileVault on, a reboot stops at the encrypted-disk password screen and **never reaches auto-login** — so the server never comes back on its own. (On a Tailscale-only box this is a reasonable trade. If you must keep FileVault, you'll have to type the disk password in person after every power cut.)

With all three set **plus** the startup service installed: power returns → Mac powers on → auto-logs in → the server (and watchdog) start with GPU access → and any crash/hang is auto-recovered. Fully hands-off.

### Rolling it out to many Macs
The service files ship inside this launcher, so on each Mac you just click **Install as Startup Service** once. Do the three system settings once per machine (or bake them into your provisioning). After that, updates flow through the normal **Update** button.

## License

The launcher scripts in this repo are MIT. Each TTS model has its own license — see the catalog for per-model notes. The big restrictions to remember:

- **F5-TTS**: non-commercial
- **Echo-TTS**: non-commercial **and ShareAlike** (CC-BY-NC-SA-4.0) — the most
  restrictive license in the catalog
- **Chatterbox, OmniVoice, Qwen3-TTS, Bark, Spark-TTS, Kokoro, Audio8 TTS
  Preview, MOSS-TTS-Nano**: permissive
  (MIT / Apache-2.0; check each catalog entry for exact terms)
- **VoxCPM2**: Apache-2.0

Voice cloning models can imitate any voice from a short reference. **Only clone voices you have permission to use.**
