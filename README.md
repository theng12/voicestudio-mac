# VoiceStudio (Mac)

Apple Silicon text-to-speech studio. Sibling app to **ImageStudio Mac** (FLUX image generation) and **MusicStudio Mac** (MusicGen / Stable Audio). Same scaffolding, focused on TTS.

> **Phase 1 status**: catalog browsing, downloads (with redundant-file filtering), weight imports from other apps, HF token settings, and direct API access all work. **TTS generation lands in Phase 2.**

## What it does

- **Catalog of 9 open-source TTS models** across 7 families:
  - **Kokoro** (82M, MIT, real-time, English) — recommended starter
  - **VoxCPM / VoxCPM2** (OpenBMB, multilingual, voice cloning)
  - **F5-TTS** (highest-quality English voice cloning, non-commercial)
  - **Chatterbox** (Resemble, MIT, voice cloning with emotion slider)
  - **Spark-TTS** (Apache-2.0, controllable zero-shot)
  - **Bark / Bark small** (Suno, MIT, expressive tags)
  - **XTTS-v2** (Coqui, 17 languages, non-commercial)
- **Smart downloads** — filters out redundant duplicate weight formats automatically. F5-TTS goes from 6.3 GB → 1.3 GB, Bark from 20 GB → 4 GB, Chatterbox from 11 GB → 3 GB.
- **Resume on retry** — partial downloads pick up where they left off.
- **Imports** — link or move TTS weights from other launchers (e.g. a standalone VoxCPM webui).
- **Direct API** — bound on `0.0.0.0:47870`, hit it from your main Mac over LAN, Tailscale, or anywhere on the network.

## How to use

1. Install: click **Install** in the Pinokio sidebar (creates the conda env).
2. Start: click **Start** (runs uvicorn on port 47870 across all interfaces).
3. Click **Open UI** to see the catalog. Pick models from **Models** → **Download**.
4. **Install Generation** (the ✨ wand sidebar item) — adds torch + transformers + diffusers. Required for Phase 2.

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

// Start a download
await fetch("http://localhost:47870/api/downloads", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ repo: "hexgrad/Kokoro-82M" }),
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

# Start a download
requests.post(
    "http://localhost:47870/api/downloads",
    json={"repo": "hexgrad/Kokoro-82M"},
)
```

### curl

```bash
# Catalog
curl http://localhost:47870/api/catalog | jq .

# Start a download
curl -X POST http://localhost:47870/api/downloads \
  -H "content-type: application/json" \
  -d '{"repo":"hexgrad/Kokoro-82M"}'

# Watch downloads via SSE
curl -N http://localhost:47870/api/downloads/stream
```

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
├── reset.js            # Nuke the conda env
├── pinokio.js          # Sidebar menu
├── pinokio.json        # Pinokio metadata
└── ENVIRONMENT         # HF_HOME and share-proxy config
```

## Ports

VoiceStudio uses **port 47870** so it doesn't clash with ImageStudio (47868) or MusicStudio (47869). All three can run simultaneously.

## License

The launcher scripts in this repo are MIT. Each TTS model has its own license — see the catalog for per-model notes. The big restrictions to remember:

- **F5-TTS**: non-commercial
- **XTTS-v2**: non-commercial (Coqui CPML)
- **Chatterbox, Bark, Spark-TTS, Kokoro**: permissive (MIT / Apache-2.0)
- **VoxCPM / VoxCPM2**: check the OpenBMB license per release

Voice cloning models can imitate any voice from a short reference. **Only clone voices you have permission to use.**
