# VoiceStudio (Mac)

Apple Silicon text-to-speech studio. Sibling app to **ImageStudio Mac** (FLUX image generation) and **MusicStudio Mac** (MusicGen / Stable Audio). Same scaffolding, focused on TTS.

> **Current status**: local TTS generation, voice cloning, transcription, model management, and a five-provider cloud audio gateway are available from one UI and API.

## What it does

- **Catalog of focused local models** across 13 families, including Qwen3-TTS,
  Chatterbox, OmniVoice, VoxCPM2, Kokoro, F5-TTS, Spark-TTS, Bark,
  Orpheus, KittenTTS, VibeVoice, Voxtral, and Marvis.
- **Apple Silicon first** — the priority families use curated MLX tiers instead
  of presenting every redundant precision. Qwen3 includes 0.6B and 1.7B Base
  voice cloning, with long cloned scripts automatically rendered in short
  sentence-aware sections and joined into one chapter file. Qwen's Base clone
  mode does not expose a native speed control in the current MLX engine.
  Qwen3 also includes 1.7B preset voices and 1.7B VoiceDesign. Chatterbox and
  OmniVoice expose their native cloning and quality controls. Kokoro keeps one
  full-quality MLX model with all 54 voices, nine language variants, speed, and
  equal voice blending. VoxCPM2 keeps a fast 4-bit tier and a bf16 final-render
  tier, both with voice design and transcript-aware cloning. Bark uses its current
  native MLX conversion with all 130 multilingual presets and complete sampling controls.
- **Smart downloads** — filters out redundant duplicate weight formats automatically. F5-TTS goes from 6.3 GB → 1.3 GB, Bark avoids more than 4 GB of duplicate preset files, and Chatterbox goes from 11 GB → 3 GB.
- **Resume on retry** — partial downloads pick up where they left off.
- **Imports** — link or move TTS weights from other launchers (e.g. a standalone VoxCPM webui).
- **Cloud audio gateway** — connect ElevenLabs, GenAIPro, Fish Audio, fal.ai, or Kie.ai in Settings, explicitly allow paid use, map provider-native IDs onto voices in the library, then use cloud and local models from the same Generate workspace. ElevenLabs supports a centralized named account pool with quota-aware failover.
- **Restart-safe cloud jobs** — asynchronous provider tasks are saved immediately and recalled after an Update or restart, so Voice Studio polls the existing paid task instead of submitting it twice.
- **Hub-managed shared voices** — Studio Hub can securely install one reference
  voice under the same stable ID, audio hash, and transcript on every Voice
  Studio Mac. Existing machine-local voices are protected from collisions.
- **Direct API** — bound on `0.0.0.0:47870`, hit it from your main Mac over LAN, Tailscale, or anywhere on the network.

## How to use

1. Install: click **Install** in the Pinokio sidebar (creates the conda env).
2. Start: click **Start** (runs uvicorn on port 47870 across all interfaces).
3. Click **Open UI** to see the catalog. Pick models from **Models** → **Download**.
4. **Install Generation** (the ✨ wand sidebar item) to use local models. Cloud models do not require the local generation engine.
5. For cloud speech, open **Settings → Cloud audio providers**. For ElevenLabs,
   add each account to the pool on the main Hub Mac, check balances, and enable
   paid usage. Then use **Voices → Edit** to map that same voice separately for
   each account. Other providers continue to use one saved key.

### ElevenLabs account pool

The pool lives in Voice Studio's private local settings on the Mac running the
main Studio Hub. Remote Voice Studio Macs do not need ElevenLabs keys. Studio
Hub routes ElevenLabs cloud jobs to this local Voice Studio gateway; remote Macs
remain available for local TTS engines.

Voice Studio selects an enabled account with a matching voice mapping, preferring
the most known remaining credits. Exhausted or invalid accounts are skipped,
temporary rate limits cool down automatically, and definite account-local
failures move to the next mapped account. Keys created in the same ElevenLabs
workspace share that workspace's quota, so use separate workspaces/accounts when
you need genuinely separate plan balances.

If a paid response connection drops, Voice Studio first recovers the exact
result from ElevenLabs History. It only adopts one unambiguous text/model/voice
match and never blindly resubmits an uncertain paid request. Connection failures
that happen before submission retry automatically.

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

## API

Once running, the API is at `http://<your-mac-ip>:47870`. Examples:

### JavaScript

```js
// List the catalog
const r = await fetch("http://localhost:47870/api/catalog");
const { models, families } = await r.json();

// Inspect all five cloud providers. Models appear after key + paid consent + enabled.
const providers = await fetch("http://localhost:47870/api/providers").then(r => r.json());

// Add a named ElevenLabs account (the response contains only masked key data).
await fetch("http://localhost:47870/api/providers/elevenlabs/accounts", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ label: "ElevenLabs 2", api_key: "your-api-key" }),
});

// Start a download
await fetch("http://localhost:47870/api/downloads", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ repo: "mlx-community/Kokoro-82M-bf16" }),
});

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

# List cloud-provider readiness and models
providers = requests.get("http://localhost:47870/api/providers").json()
print(providers)

# Add another ElevenLabs account to the local gateway pool
requests.post(
    "http://localhost:47870/api/providers/elevenlabs/accounts",
    json={"label": "ElevenLabs 2", "api_key": "your-api-key"},
)

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

# Cloud provider status and current models
curl http://localhost:47870/api/providers | jq .

# Add an ElevenLabs account, then refresh all balances
curl -X POST http://localhost:47870/api/providers/elevenlabs/accounts \
  -H "content-type: application/json" \
  -d '{"label":"ElevenLabs 2","api_key":"your-api-key"}'
curl -X POST http://localhost:47870/api/providers/elevenlabs/accounts/refresh | jq .

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

Remote calls require the fleet's `X-Studio-Token`. Provider-specific voice IDs
and generated embeddings are intentionally not distributed.

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
- **Chatterbox, OmniVoice, Qwen3-TTS, Bark, Spark-TTS, Kokoro**: permissive
  (MIT / Apache-2.0; check each catalog entry for exact terms)
- **VoxCPM2**: Apache-2.0

Voice cloning models can imitate any voice from a short reference. **Only clone voices you have permission to use.**
