# Changelog — Voice Studio KH

All notable changes to Voice Studio KH are documented here.

Versioning follows [Semantic Versioning](https://semver.org/) with this project-specific interpretation:

- **MAJOR** (1.x.x → 2.x.x) — breaking change. Re-install required.
- **MINOR** (1.1.x → 1.2.x) — new engine / new feature / new model family. **Re-run "Install Generation"** to pick up new Python deps.
- **PATCH** (1.2.0 → 1.2.1) — bugfix / UI tweak / catalog entry within an existing family. **Just run Update** from the Pinokio sidebar.

---

## [1.2.6] — 2026-05-26

### Fixed — VoxCPM soft cap lowered 3000 → 1500 (Metal OOM on 16 GB Macs)

Story studio hit voicestudio with a 2755-char voice-cloning request on `mlx-community/VoxCPM2-4bit`. The job ran ~3-4 minutes then **crashed the entire server**:

```
[metal::malloc] Attempting to allocate 13133537280 bytes which is greater than
the maximum allowed buffer size of 9534832640 bytes.
Abort trap: 6
```

= 13.1 GB requested vs the M4's ~9.5 GB **per-Metal-buffer cap**. Process aborted instantly; full server crash (not a job failure).

**Root cause of my v1.2.4 miscall**: I bumped `voxcpm` + `voxcpm-mlx` soft caps to 3000 chars based on OpenBMB's documented architecture (`max_tokens=4096` audio tokens @ 6.25 Hz ≈ 11 min audio). But "engine architecture allows it" ≠ "your 16 GB Mac can hold it." VoxCPM is diffusion-based — activation buffers grow linearly with output audio length, and at ~3 minutes of generation the working tensors spike past Metal's per-buffer ceiling. The audit grounded the cap in the engine's spec, but should have grounded it in the *machine's* spec.

**The math from the crash data:**
- 2755 chars triggered 13.13 GB request → exceeds 9.53 GB Metal cap by 38%.
- Ratio of safe (9.53) ÷ requested (13.13) = 0.73.
- 2755 × 0.73 ≈ ~2000 chars as a tight ceiling. With safety margin for other apps: **~1500**.

**Changes:**
- `voxcpm` family `text_guidance.soft_max_chars`: 3000 → **1500**
- `voxcpm-mlx` family `text_guidance.soft_max_chars`: 3000 → **1500**
- Both notes now warn explicitly: *"On 16 GB Macs, longer voice-cloning calls can OOM Metal — split into multiple requests."*
- Source comments above each `TextGuidance` block now distinguish **engine ceiling** (4096 tokens / 11 min) from **hardware ceiling** (~1500 chars on M-series 16 GB).

### What this does NOT yet fix

The fix is preventive — the soft cap blocks the chip text from misleading users. But it's still a *soft* cap. A caller hitting the API directly (e.g., story studio's API integration) can ignore the chip and submit any length. The proper fix is a **runtime memory gate** in `_generate_voxcpm` / `_generate_mlx_audio` that estimates Metal buffer need from input length × engine factor and raises a clear `RuntimeError` BEFORE the alloc attempt — so a single bad request fails its own job instead of crashing the server.

Flagged as TODO. Approach: introduce `MAX_ALLOC_BYTES = 9_500_000_000` (M-series per-buffer Metal cap) and a per-family `estimate_memory_bytes(input_chars)` function. When over the cap, raise before calling `generate_audio()`. Won't ship until we have empirical data on the linear coefficient.

### Notes

- PATCH bump (1.2.5 → 1.2.6) — pure cap correction + note rewrite. No schema, no code path, no new deps. Run `Update` from the Pinokio sidebar, then Stop → Start.
- The other 14 families' caps stay where v1.2.4 set them — they're either far below their hardware ceilings already, or don't have the diffusion-activation-growth profile that triggers this kind of OOM.
- This is the third time this exact Metal OOM has shown up in the project history. v1.2.2 documented it as a workaround note. v1.2.4 inadvertently re-opened it by raising the cap. v1.2.6 closes it for VoxCPM specifically. The right structural fix is the runtime memory gate — file as P1 for next iteration.

---

## [1.2.5] — 2026-05-24

### Fixed — Hint chip text shortened from dev-grade docs to user-friendly one-liners

The v1.2.4 audit landed correct numbers but a side effect was that every `text_guidance.note` ballooned into a multi-sentence source citation (XTTS hit **455 chars**, F5-TTS **421 chars**, Orpheus **431 chars**). Those notes flow straight into the chip above the textarea, so users were seeing a wall of dev-speak instead of a usable hint.

All 16 notes rewritten to **80-121 chars**, action-first. The audit citation moved to a Python comment immediately above each `TextGuidance(...)` block so the source trail stays in `catalog.py` for anyone reading the file.

Before / after example (Bark):

> **Before (361 chars):** Hard cap from upstream. Suno's own FAQ states 'output is limited to ~13-14 seconds' because Bark is GPT-style with a fixed 1024-token semantic/coarse context window. ~150 chars maps to that ceiling at neutral narration pace; past it, output hallucinates or goes silent. Our worker feeds the whole text in one shot, so the cliff is real — split into short lines.
>
> **After (103 chars):** Hard cap ~150 chars (~13 sec). Past the cap, Bark hallucinates or goes silent — split into short lines.

Same information density user actually needs (cap, what happens past it, what to do); citation now lives in a `# Audit (v1.2.4): ...` comment above the block.

### Length stats

| family | new char count |
|---|---:|
| spark-tts / spark-tts-mlx | 81 |
| kokoro / kokoro-mlx | 92 |
| voxcpm / voxcpm-mlx | 96 |
| chatterbox / chatterbox-mlx | 101 |
| bark | 103 |
| kittentts | 105 |
| xtts | 107 |
| orpheus | 108 |
| vibevoice | 113 |
| qwen3-tts | 114 |
| f5-tts | 115 |
| omnivoice | 121 |

Median ~104 chars. No note over 121 chars. The chip block can now fit comfortably in one or two visual lines.

### Notes

- PATCH bump (1.2.4 → 1.2.5) — pure copy edit on `text_guidance.note` fields + comment additions. No schema, no value changes, no new deps. Run `Update` from the Pinokio sidebar, then Stop → Start.
- The Generate-button warning and counter line under the textarea also already auto-pull from `text_guidance` — they update with the new values transparently. No frontend code changes.
- Full audit trail (file paths, line numbers, formulas) is preserved in v1.2.4's CHANGELOG entry above and in `# Audit (v1.2.4):` comments throughout `catalog.py`.

---

## [1.2.4] — 2026-05-24

### Fixed — All 16 family `text_guidance.soft_max_chars` audited against upstream source

Followup to v1.2.3 (where VoxCPM was the only family fixed). The remaining 14 families have now all been verified against either upstream docs, the model card, or — most reliably — the actual code in the installed `mlx-audio`, `transformers`, or `voxcpm` packages. Notes now cite the exact file, line, or constant the cap comes from, so future audits don't have to redo this work.

**Changed values (engine could handle far more than the guess admitted):**

| Family | Old | New | Source |
|---|---:|---:|---|
| `qwen3-tts` | 400 | **3000** | `mlx_audio/tts/models/qwen3_tts/qwen3_tts.py:1149` — `max_tokens=4096` per segment @ 12 Hz token rate ≈ 5.7 min audio. Plus `split_pattern="\n"` for transparent text splitting. |
| `spark-tts` / `spark-tts-mlx` | 400 | **750** | `mlx_audio/tts/models/spark/spark.py:229` — `max_tokens=3000` per call @ BiCodec ~50 Hz ≈ 60 sec audio ≈ ~780 chars in English. |
| `f5-tts` | 400 | **null (unlimited)** | `f5_tts/infer/utils_infer.py` — `chunk_text(max_chars=135)` internally splits any input into 135-char chunks and stitches with 0.15 sec crossfade. The engine handles long-form transparently; soft cap was meaningless. |
| `omnivoice` | 600 | **null (unlimited)** | `mlx_audio/tts/models/omnivoice/omnivoice.py:483` — flow-matching (diffusion), not autoregressive. Takes explicit `duration_s` or estimates from text + ref clip via `RuleDurationEstimator`. No per-call cliff. |

**Guesses that landed correct (kept as-is, only the `note` was updated to cite the source):**

| Family | Cap | Source |
|---|---:|---|
| `bark` | 150 | Suno's official GitHub FAQ: *"output is limited to ~13-14 seconds — Bark is GPT-style with a fixed context window"* + transformers `BarkSemanticConfig.block_size=1024`. |
| `orpheus` | 170 | `mlx_audio/tts/models/llama/llama.py:367, 525` — `max_tokens=1200` per segment. Orpheus emits ~85 SNAC tokens/sec → 1200 tokens ≈ 14 sec audio. |
| `xtts` | 250 | Coqui's `TTS/tts/layers/xtts/tokenizer.py` — `char_limits` dict hardcodes per-language caps. English=250 (exact match). Note now lists all 16 language caps including CJK floor (ja=71). |
| `chatterbox` / `chatterbox-mlx` | 500 | `mlx_audio/tts/models/chatterbox_turbo/chatterbox_turbo.py:859` — `max_chars_per_chunk = (max_tokens // 8) * 4`. Default `max_tokens=1000` → exactly 500 chars per chunk. |

**Kept null/unlimited (engine auto-chunks transparently, soft cap would mislead):**

- `kokoro`, `kokoro-mlx`: KPipeline sentence-chunks via `split_pattern=r"\n+"`. Unchanged from v1.1.8.
- `kittentts`: `mlx_audio/tts/models/kitten_tts/kitten_tts.py:42` — `chunk_text(max_len=400)`. Per-chunk ceiling exists (400 chars) but engine auto-chunks; tiny model makes long-form cheap. Note now cites the source.
- `vibevoice`: `mlx_audio/tts/models/vibevoice/vibevoice.py:397` — `max_tokens=512` per segment (~500 chars / ~43 sec). Streaming architecture multi-segments transparently. Note now warns: if you hit voice drift on very long calls, break manually.

### Side observations (not fixed in this version, flagged for follow-up)

- **OmniVoice voice cloning now works upstream**: `mlx_audio/tts/models/omnivoice/omnivoice.py:483` exposes `ref_audio` + `ref_text` parameters. Our `_generate_omnivoice` worker (added in v1.2.0) raises `NotImplementedError` when `voice_library_id` is set — that error message is stale now that mlx-audio's port supports cloning. Worth wiring up in a future PATCH.
- **mlx-audio's OmniVoice port supersedes the `ailuntx/OmniVoice-MLX` git install**: our `requirements-generation.txt` pulls in `ailuntx/OmniVoice-MLX` as a separate package, but mlx-audio now ships its own port. Consolidating onto mlx-audio's path would remove a dependency. Not urgent — both work.

### Notes

- PATCH bump (1.2.3 → 1.2.4) — pure soft-cap corrections + note enrichment, no code path changes, no new deps. Run `Update` from the Pinokio sidebar, then Stop → Start.
- All notes now reference specific file paths + line numbers so the audit trail is captured in-source.
- `audit_truth.py` still reports **NO DRIFT** — 16 families, 12 wired, 0 commission/omission lies.

---

## [1.2.3] — 2026-05-24

### Fixed — VoxCPM `text_guidance.soft_max_chars` raised from 600 → 3000 (was a guess)

The 600-char soft cap I shipped in v1.1.8 for both `voxcpm` and `voxcpm-mlx` wasn't from any official source — I picked it as a conservative "one paragraph" heuristic. After verifying against upstream:

- **OpenBMB model card** (openbmb/VoxCPM2): documents an 8192-token architecture max and 6.25 Hz LM token rate. No char-level cap published. Only qualitative warning: *"Occasional instability may occur with very long or highly expressive inputs."*
- **`voxcpm` Python package** (PyTorch reference, `core.py:189`): generation defaults to `max_len=4096` audio tokens.
- **`mlx-audio` voxcpm worker** (`mlx_audio/tts/models/voxcpm/voxcpm.py:259`): same `max_tokens=4096` default. Config also exposes `max_length=8192` as the architecture cap.

4096 audio tokens at 6.25 Hz ≈ **655 seconds ≈ 11 minutes of audio per call** — roughly 8,000-10,000 characters of English text. Our 600-char cap was ~7% of what the engine actually supports.

New value: **3000 chars (~3 minutes audio)** for both `voxcpm` and `voxcpm-mlx`. Well under the 4096-token ceiling, but high enough to cover a full audiobook chapter section in one call. The `note` field now cites the official numbers (token rate + architecture max) so future audits don't have to redo this work.

### Notes

- PATCH bump (1.2.2 → 1.2.3) — pure soft-cap correction, no code path changes. Run `Update` from the Pinokio sidebar.
- **The same audit hasn't been done for the other 14 families.** Numbers I cited for Bark (150), Orpheus (170), XTTS (250), F5-TTS (400), Chatterbox (500), Spark-TTS (400), Qwen3-TTS (400), and OmniVoice (600) were also rough heuristics — Bark / Orpheus / XTTS are at least grounded in well-known training-window constraints, but the others deserve the same source-checking pass if you start running into the soft cap on them. Ping me when you do.
- "Unlimited" families (Kokoro, Kokoro-MLX) stay as-is — KPipeline really does sentence-chunk to arbitrary length.

---

## [1.2.2] — 2026-05-24

### Fixed — Phantom `Spark-TTS-0.5B-4bit` catalog entry replaced with real variants

The catalog row for `mlx-community/Spark-TTS-0.5B-4bit` pointed at a HuggingFace repo that **doesn't exist** (the API returns HTTP 401 for that exact name). Anyone who clicked Download on that card would see the request silently fail with no clear error. Verified against the live HF API: the only mlx-community Spark-TTS variants that actually exist are `bf16`, `4-6bit`, `6bit`, and `8bit`.

- **Removed**: `mlx-community/Spark-TTS-0.5B-4bit` (phantom).
- **Added**: `mlx-community/Spark-TTS-0.5B-4-6bit` (mixed quant, ~1.6 GB) — now the recommended starter.
- **Added**: `mlx-community/Spark-TTS-0.5B-6bit` (~1.7 GB).
- **Added**: `mlx-community/Spark-TTS-0.5B-bf16` (~2.3 GB, full precision).
- **Kept**: `mlx-community/Spark-TTS-0.5B-8bit` (~1.7 GB) — was always real.
- Updated sizes are HEAD-request-verified against `model.safetensors`: 4-6bit=0.30 GB · 6bit=0.41 GB · 8bit=0.54 GB · bf16=1.01 GB. Each repo also bundles `wav2vec2-large-xlsr-53` (~1.26 GB) as a reference encoder — that's the bulk of the on-disk size.

### Diagnosed — Server crashes from Metal allocation OOM during VoxCPM2 load

Server crash logged at `logs/api/start.js/latest`:

```
libc++abi: terminating due to uncaught exception of type std::runtime_error:
[metal::malloc] Attempting to allocate 12111175680 bytes which is greater
than the maximum allowed buffer size of 9534832640 bytes.
```

That's ~12 GB requested against the M4's ~9.5 GB Metal buffer limit. Most likely trigger: loading `VoxCPM2-bf16` (4.96 GB on disk → unpacks to ~8-10 GB at runtime) for generation, exceeding the per-buffer cap. The 4-bit variant should stay under the cap.

Not a code change in this version — just documenting the failure mode. **Workaround**: prefer `VoxCPM2-4bit` over `bf16` on 16 GB Macs, or close other RAM-heavy apps before generating. A real fix would need either chunked loading in upstream `mlx-audio` or runtime gating in `generation.py` based on the variant's expected unpacked size — flagged for a future iteration.

### Notes

- PATCH bump (1.2.1 → 1.2.2) — catalog correctness fix, no new deps, no schema changes. Run `Update` from the Pinokio sidebar, then Stop → Start.
- If you already had `mlx-community/Spark-TTS-0.5B-4bit` queued or partially downloaded in localStorage, that entry will simply disappear from the Models tab after Update (nothing to remove from disk since nothing was downloaded).
- The other 3 Spark-TTS variants in the catalog (`8bit`, `6bit`, `4-6bit`, `bf16`) work via the existing `_generate_mlx_audio` dispatch — no new worker code needed.

---

## [1.2.1] — 2026-05-24

### Added — KittenTTS, VibeVoice, and refreshed Chatterbox MLX builds

Three more MLX-native families wired up. All ride the existing `mlx-audio` `load_model` path — no new Python deps, just catalog entries + `MLX_AUDIO_FAMILIES` table rows + frontend voice-picker hints.

- **KittenTTS** (`kittentts` family) — KittenML's ultra-tiny preset-voice TTS, Apache-2.0. Smaller than Kokoro by an order of magnitude. 4 entries: `kitten-tts-mini-0.8-4bit` (recommended, ~70 MB), `kitten-tts-mini-0.8-fp16`, `kitten-tts-micro-0.8-4bit`, `kitten-tts-nano-0.8-fp16` (smallest in the catalog at ~30 MB). 8 preset voices: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo. **Requires `espeak-ng` on the system** — install with `brew install espeak-ng` if generation fails.
- **VibeVoice Realtime** (`vibevoice` family) — Microsoft's MIT-licensed 0.5B Qwen2.5-based streaming TTS. 3 entries: `VibeVoice-Realtime-0.5B-4bit` (recommended), `-8bit`, `-fp16`. Designed for low-latency / long-form streaming. Preset voice names like `en-Emma_woman`. English-only today.
- **Chatterbox 2026 MLX builds** — added 5 new ModelEntry rows to the existing `chatterbox-mlx` family pointing at the newer mlx-community conversions (Jan 2026, mlx-audio 0.2.7): `chatterbox-4bit` (recommended, smaller than the old build), `chatterbox-8bit`, `chatterbox-fp16` (full precision), `chatterbox-turbo-4bit` (Resemble's faster Turbo variant), `chatterbox-turbo-8bit`. The older `chatterbox-mlx-4bit/8bit` entries are kept — users with those downloads still work.

### Coverage update

`audit_truth.py` reports **NO DRIFT** — catalog now has 16 families, 12 wired (added kittentts + vibevoice to `_WIRED_FAMILIES`). 4 still-roadmap families (`chatterbox`, `f5-tts`, `spark-tts`, `xtts`) remain as PyTorch placeholders that raise `NotImplementedError`.

### Frontend tweaks

- `isKittenTts(repo)` + `isVibeVoice(repo)` helpers added to `app.js`.
- Both folded into `isMlxVoicePicker` (gets the free-form voice text input) and `isMlxAudio` (gets the speed slider).
- Voice-picker placeholder updated to show one example per family; hint text now lists KittenTTS voice names + the espeak-ng caveat, and notes VibeVoice's `lang-name_gender` naming convention.

### Notes

- PATCH bump (1.2.0 → 1.2.1) — pure catalog + wiring additions, no new Python deps, no breaking changes. Run `Update` from the Pinokio sidebar.
- If KittenTTS or VibeVoice fail to import after Update, the `Engines ready` chip in the Models tab will stay grey for those families. Run `Install Generation` to refresh `mlx-audio` to the latest version (some KittenTTS / VibeVoice readers need mlx-audio ≥ 0.2.7).
- Orpheus was checked but skipped — the collection page 404'd and the existing 4-bit / 8-bit / bf16 entries already cover the main precisions. Let me know if you want me to add specific extra variants (5-bit / 6-bit / fp16).

---

## [1.2.0] — 2026-05-24

### Added — OmniVoice (MLX) family

k2-fsa's [OmniVoice](https://github.com/k2-fsa/OmniVoice) — a 0.6B diffusion-language-model TTS with **646-language** support and natural-language voice design — wired up via [ailuntx's experimental MLX port](https://github.com/ailuntx/OmniVoice-MLX). This is the broadest multilingual coverage in the catalog (next nearest is VoxCPM2 at ~30 languages), and one of the few permissively-licensed (Apache-2.0) options for commercial work.

- **4 new catalog entries** (`app/backend/catalog.py`):
  - `mlx-community/OmniVoice-4bit` — 0.5 GB, recommended starter, 8 GB Mac friendly
  - `mlx-community/OmniVoice-8bit` — 0.9 GB, higher-precision quant
  - `mlx-community/OmniVoice-bfloat16` — 1.3 GB, reference quality
  - `mlx-community/OmniVoice-fp32` — 2.4 GB, dense fp32 baseline
- **New `omnivoice` family** in `FAMILIES` with `text_guidance` (auto-split, ~600 chars / ~40s soft cap).
- **`_generate_omnivoice` worker** in `app/backend/generation.py` — uses `from omnivoice.mlx import OmniVoiceMLX`. Hybrid stack: diffusion LM in MLX, Higgs audio tokenizer on PyTorch (both already required by other families). Per-repo model eviction on switch since unified memory can't hold two diffusion-LM TTS instances at once.
- **`omnivoice` added to `_WIRED_FAMILIES`** + `audit_truth.py` reports **NO DRIFT** (14 families, 10 wired, 0 commission/omission lies).
- **`/api/generate/availability` reports `omnivoice_available`** based on a 3-layer import probe (`omnivoice.mlx.OmniVoiceMLX`).
- **Frontend** (`app/frontend/index.html` + `app.js`):
  - New `isOmniVoice(repo)` helper.
  - Dedicated `Voice description (required)` block — same control surface as VoxCPM2 voice-design but with OmniVoice-specific copy + inline non-verbal symbol hints (`[laughter]`, `[cough]`).
  - Speed slider also surfaces (worker accepts `speed`, clamped to 0.5–2.0).
  - `canSubmit` blocks Generate when no voice description is provided.

### Limitations (intentional, will revisit)

- **Voice cloning is not yet wired on the MLX backend.** The official PyTorch API supports `ref_audio` + `ref_text` cloning, but the experimental `OmniVoice-MLX` loader only exposes voice-design (`instruct=...`). Selecting a reference voice from your library with OmniVoice raises a clear `NotImplementedError` pointing at clone-capable alternatives (VoxCPM2, Spark-TTS, Chatterbox). When the upstream MLX loader adds clone support we'll wire it in a PATCH bump.
- **Upstream MLX backend is marked "experimental"** by its author. Quality may vary by language — feedback welcome.
- `omnivoice` does NOT use the `mlx-audio` package shared by the other 6 MLX families; it has its own loader. That's why `_generate_omnivoice` is a separate worker rather than another row in `MLX_AUDIO_FAMILIES`.

### New dependency

`requirements-generation.txt` adds `omnivoice @ git+https://github.com/ailuntx/OmniVoice-MLX.git`. **Run "Install Generation" from the Pinokio sidebar** to pick up the new package, then Stop → Start the server.

### Notes

- MINOR bump (1.1.8 → 1.2.0) — new engine family + new Python dep, per `README.md` versioning rules.
- No breaking changes to existing engines or APIs.
- Soft-cap chars guess of 600 is conservative; tighten or loosen `FAMILIES["omnivoice"].text_guidance` in `catalog.py` if real-world results suggest a different ceiling.

---

## [1.1.8] — 2026-05-24

### Added — Per-family text-length guidance + soft-block on hard-cap engines

Until now the Generate tab gave no signal about how much text each TTS engine could reasonably take. Bark would silently hallucinate past ~13 seconds, Orpheus and XTTS have similar training-window cliffs, and chunked engines (Kokoro, F5, VoxCPM, Chatterbox, Spark, Qwen3) cleanly auto-split — but the UI didn't tell you which was which.

- **New `TextGuidance` field on every `Family`** (`app/backend/catalog.py`) — three fields per engine: `soft_max_chars` (rough character threshold, `None` for engines with no practical cap), `chunking` (`"unlimited"` / `"auto-split"` / `"hard-cap"`), and a one-liner `note`. Surfaced through `serialize_family()` so the frontend can read it via `/api/catalog`. Populated honestly per engine: Kokoro and Kokoro-MLX flagged `unlimited`, Bark (150) / Orpheus (170) / XTTS (250) flagged `hard-cap`, the other 8 families flagged `auto-split` with conservative chunk-size hints.
- **Hint chip above the textarea** — color-coded by chunking: green `∞` for unlimited, blue `✂` for auto-split, amber `⚠` for hard-cap. Surfaces the engine's real constraint before you hit Generate.
- **Model-aware counter under the textarea** — was `420 chars · ~28s of audio`. Now appends `· over recommended 400-char chunk size` (auto-split engines) or `· ⚠ exceeds Suno Bark's 150-char cap` (hard-cap engines) when text crosses the threshold. Counter text turns amber to match.
- **Two-click soft-block for hard-cap engines** — when text exceeds `soft_max_chars` AND the family is `hard-cap`, the Generate button turns amber and the label flips to `⚠ Click again to generate anyway`. Second click submits normally. Editing the text or switching models resets the confirmation. Auto-split and unlimited engines never block — hint only.

### Added — Per-model preset persistence

Voice / speed / seed / cfg knobs now persist across restarts, keyed by repo so each model remembers its own settings. Same localStorage pattern as the existing Models-tab filter prefs.

- **Two new localStorage keys** (`app/frontend/app.js`): `voicestudio.gen.presets` is `{ [repo]: { field: value, ... } }`, `voicestudio.gen.lastRepo` is the last-active repo. Restored after `refreshCatalog()` + `refreshGenAvailability()` + `refreshVoices()` so option lists are populated when fields hydrate.
- **Allowlist of 13 fields** persisted per repo: `voice`, `preset_speaker`, `bark_voice_preset`, `voice_library_id`, `speed`, `seed`, `batchCount`, `cfg_value`, `inference_timesteps`, `normalize_text`, `instruct`, `voice_design_prompt`, `ref_transcript`. Transient session state (`jobs`, `submitting`, `currentJob`, `text`, `overCapConfirmed`) is intentionally excluded.
- **Watchers re-save on any field change.** `$watch("gen.repo")` additionally pulls in the new repo's preset *after* `onModelChange()`'s default-snap runs — `$watch` fires on the microtask after the synchronous `@change` handler, so snap → restore order is correct.
- **Last-repo restore is validated**: if the stored `lastRepo` references a model you've since uninstalled, restore quietly skips and falls back to the default-selected model.
- Stale presets for uninstalled models stay in localStorage harmlessly; if you reinstall later, the old settings come back.

### Notes

- PATCH bump — pure UX additions, no breaking changes, no new Python deps. Run `Update` from the Pinokio sidebar.
- The text in the textarea is intentionally **not** persisted — that's a different feature (would balloon storage on long inputs and stale content from yesterday rarely matches today's intent).
- Soft-block character thresholds (`soft_max_chars`) are conservative best-effort values pulled from each engine's training-window or upstream docs. If real-world experience says a number's too tight or too loose, edit `FAMILIES["…"].text_guidance` in `catalog.py`.

---

## [1.1.7] — 2026-05-24

### Fixed — Cancelled queued jobs no longer pop back to "queued" in the UI

Follow-up to v1.1.6. Same race + same fix as ImageStudio v1.3.2. The worker entry (`_run_txt2speech`) had a redundant `job.state = "queued"` BEFORE `with _GEN_LOCK:`. If the user clicked Cancel between `submit_job()` returning and the worker thread actually being scheduled, the worker would re-assert `state="queued"` and clobber the cancel decision. The `cancel_event` flag survived, so the worker eventually settled `state="cancelled"` once it acquired the lock — but by then the previous synthesis had finished and minutes had passed, during which the cancelled card was visibly stuck in the queue UI.

Removed the redundant assignment. The dataclass default already initializes `state="queued"`, so it was dead code — except in the cancel-race window where it was actively destructive.

### Notes

- PATCH bump — UX bugfix, no schema or dependency changes. Run `Update` from the Pinokio sidebar.

---

## [1.1.6] — 2026-05-24

### Fixed — Cancel button works for queued jobs (and explains itself for running jobs)

Mirrored from ImageStudio v1.3.1 (per the "apply UX wins to all 3 apps" rule). VoiceStudio had the same latent bug: `manager.cancel()` only set `cancel_event`, so queued jobs blocked on `_GEN_LOCK` couldn't react until the running synthesis finished. Clicking ✕ Cancel on a queued job appeared to do nothing.

- **Backend (`generation.py`):** `manager.cancel()` immediately flips queued jobs to `state="cancelled"` + `finished_at` + persists. Worker still safely no-ops when it later wakes up and sees `cancel_event.is_set()`.
- **Frontend (`app.js`):** `cancelPending()` toasts differently depending on state:
  - **Queued** → "✓ Cancelled — Queued job removed." (instant)
  - **Running** → "⏸ Cancel signal sent" + honest about why: mlx-audio TTS engines (Kokoro, VoxCPM, Chatterbox, Orpheus, Spark, Qwen3-TTS) are blocking synthesis calls that don't honor mid-flight cancellation. The result gets discarded after synthesis finishes.

### Notes

- PATCH bump — UX bugfix, no schema or dependency changes. Run `Update` from the Pinokio sidebar.

---

## [1.1.5] — 2026-05-24

### Changed — MLX-only filter ON by default + persistent preferences

Same change as ImageStudio v1.2.2. Models tab opens with `🍎 Apple Silicon (MLX) only` pre-toggled, hiding the 9 non-MLX entries (PyTorch Kokoro / VoxCPM v1 / Bark + 4 PyTorch roadmap engines + VoxCPM v2). On your M4 this turns 25 cards → 16 cards on first load.

User's MLX + Fits-my-Mac choices persist via localStorage (`voicestudio.modelFilters.*` keys).

### Notes

- Non-destructive — catalog unchanged. Untoggle MLX-only to see everything (PyTorch Bark's tag system, VoxCPM v1's voice cloning, etc).
- PATCH bump — `Update` from Pinokio.

---

## [1.1.4] — 2026-05-24

### Added — `audit_truth.py` script

Mirrors the v1.2.1 ImageStudio tool. AST-parses `catalog.py` + `generation.py` to detect drift between `_WIRED_FAMILIES` and actual dispatch coverage. Handles the VoiceStudio-specific `MLX_AUDIO_FAMILIES` config-table pattern (where 6 families share one `_generate_mlx_audio` worker).

```
python3 audit_truth.py            # human report
python3 audit_truth.py --strict   # exit non-zero on drift
```

Result: `✓ NO DRIFT` — all 9 wired families (kokoro, voxcpm, bark + 6 mlx-audio: qwen3-tts, voxcpm-mlx, kokoro-mlx, chatterbox-mlx, spark-tts-mlx, orpheus) verified against actual dispatch.

Documented in README "Truth audit (for contributors)" section.

### Notes

- PATCH bump — pure dev tooling, no runtime change.

---

## [1.1.3] — 2026-05-24

Mirrors v1.1.2 + v1.1.3 UX wins from ImageStudio (per the "apply UX wins across all 3 apps" rule).

### Added — collapse-by-default model cards (was v1.1.2 in ImageStudio)

- **Compact model cards** — cards default to showing only label + chips + repo + size + hardware + capabilities. The `best_for` line, use-case bullets, and "Saved at" path are hidden behind a per-card `▾ Show details` toggle. With 25 models in the catalog this turns the Models tab from a wall of text into a scannable gallery.
- **Bulk expand/collapse** — `▾ Expand all` / `▴ Collapse all` toolbar buttons operate on the currently-filtered list.
- **MLX-only filter chip** — `🍎 Apple Silicon (MLX) only` toggle. On VoiceStudio this filters 25 → 16 (cuts the 4 PyTorch-only roadmap engines + PyTorch Kokoro/VoxCPM v1/Bark).
- **Fits my Mac filter chip** — `🖥 Fits my Mac (16 GB)` toggle. Hides only "risky" models; "tight" still shows since they might be acceptable with apps closed.

### Added — filter feedback clarity (was v1.1.3 in ImageStudio)

- **Active chips now announce themselves**: 2px bold border, 45% saturated background, white text, and a ✓ prefix so toggled-on chips are unmistakable.
- **Smart empty state**: when filters yield 0 results, you see a list of every active filter as red ✕ chips — click one to remove just that filter instead of nuking everything.

### Notes

- PATCH bump — pure UX additions, no breaking changes, no new Python deps.
- Just run `Update` from the Pinokio sidebar; no re-install needed.

---

## [1.1.1] — 2026-05-24

### Added

- **Sidebar port display + external-browser escape hatch.** The Pinokio sidebar now shows a `Port 47870 · Open in Browser` item whenever the server is running. Two benefits:
  - **Visibility**: the port number is always readable in the sidebar — if the embedded webview ever caches a black screen, you can read the port and type `localhost:47870` into Chrome / Safari instead of being stranded.
  - **One-click escape**: clicking the item opens the WebUI in your system default browser via `web.open` with `target="_blank"`.

### Why

The embedded webview occasionally caches a broken state across restarts. Hard-refresh inside the webview doesn't always help, and without knowing the port the user has no way out.

### Files

- New: `open_external.js` (5-line wrapper around `web.open`)
- Modified: `pinokio.js` adds the port display + escape-hatch item to the `running.start` menu branch

### Notes

- PATCH bump — pure UX addition, no breaking changes, no new Python deps.
- Just run `Update` from the Pinokio sidebar; no re-install needed.

---

## [1.1.0] — 2026-05-24

### Added

- **Hardware fit detection** per model card. Detects your Mac's chip + unified memory via sysctl and shows a color-coded chip on each model:
  - 🟢 **fits** — your RAM ≥ 1.5× the model's floor (plenty of headroom)
  - 🟡 **tight** — meets the floor but close other apps before generating
  - 🔴 **may not fit** — below the floor, will swap or OOM
- **"Your Mac" banner** at the top of the Models tab showing detected chip + RAM, so the per-card fit chips have a clear anchor.
- **Structured use cases** per model — all 25 entries populated with ✅ "good at" / ⚠️ "weak at" / ❌ "avoid" bullets. Highlights TTS-specific gotchas honestly:
  - VoxCPM v1 **requires** a reference transcript for cloning (empty transcript will error)
  - Kokoro is **English-only** and **can't clone** — uses fixed voicepacks
  - Bark is **slow** (30-60 sec per clip) and **inconsistent** — not for long-form
  - Chatterbox-MLX exaggeration > 0.7 gets unstable
  - 4-bit MLX quants can fumble on rare-word pronunciation
  - Orpheus has 8 preset voices (tara/dan/leah/+5) and inline emotion tags
- **`/api/system`** endpoint exposing the chip + RAM snapshot.
- **`fit` field** in `/api/catalog` per model — `{state, label, hint, actual_gb, required_gb}`.

### Notes

- No new Python dependencies — `system_info.py` uses stdlib `subprocess` + macOS's built-in `sysctl`.
- Mirrors the same Tier 1 hardware-fit pattern shipped in ImageStudio v1.1.0.
- Just run `Update` from the Pinokio sidebar; no re-install needed.

---

## [1.0.0] — 2026-05-24

First versioned release. Covers all work from the initial scaffold through Phase D (mlx-community catalog expansion).

### Engines wired (9 families)

PyTorch-based:

- **Kokoro v1.0** (82M) — tiny + real-time English TTS, 28 preset voicepacks, MIT
- **VoxCPM v1 / v2** — OpenBMB's multilingual TTS with voice cloning + emotion control
- **Suno Bark (full + small)** — expressive TTS with `[laughter]` / `[singing]` / `[MUSIC]` tags

MLX-native (via `mlx-audio`):

- **Qwen3-TTS** — Alibaba's TTS in 3 modes: CustomVoice (preset speakers), VoiceDesign (natural-language voice prompt), Base (voice cloning)
- **VoxCPM2 (MLX)** — 4-bit / 8-bit / bf16 variants, 30-language, 48 kHz studio quality
- **Kokoro (MLX)** — same Kokoro at lower memory footprint, no PyTorch needed
- **Chatterbox (MLX)** — Resemble AI's voice cloning with exaggeration/intensity dial
- **Spark-TTS (MLX)** — SparkAudio's zero-shot cloning + natural-language style control
- **Orpheus (MLX)** — Canopy Labs' 3B LLaMA-arch TTS with `<laugh>` / `<sigh>` inline tags

### Roadmap engines (catalog-only, worker not yet wired)

F5-TTS, original PyTorch Chatterbox, original PyTorch Spark-TTS, Coqui XTTS-v2

### Architecture

- **Generalized mlx-audio worker** — one `_generate_mlx_audio` function handles all 6 mlx-audio families via per-family mode resolvers + the `MLX_AUDIO_FAMILIES` config table. Adding a new mlx-audio model is now: 1 catalog entry + (sometimes) 1 config row, no new worker code.
- **3-state diagnostic system** — every engine reports `deps_ok` (packages importable) + `wired` (worker exists) + `ready` (both). UI shows which engines need install vs which are roadmap.
- **Per-engine memory management** — each worker owns a model cache that evicts on repo switch to fit Apple Silicon unified memory.
- **`/api/diagnostics`** endpoint surfaces package health + engine status to the frontend.

### Voice library

- Upload, browser-record (24 kHz mono WAV via MediaRecorder + AudioContext), or import from a seed catalog (public-domain LibriVox)
- Per-voice transcript (recommended for VoxCPM v1, optional for others)
- Engine-agnostic — same voice works with any cloning-capable family

### Generate UX

- **Queue panel** — pending + running jobs visible with per-row cancel buttons
- **Batch counter** — submit N sequential generations with auto-incrementing seeds
- **History pagination** — per-row metadata (model, voice, duration), 12 per page
- **Library filters** — search + family chips + status chips + capability chips + sort
- **Bark tag chips** — click to insert `[laughter]` / `[singing]` / `♪ ♪` at cursor
- **Per-engine controls** — engines surface only the knobs they support; defaults snap to each family's sweet spot on model switch
- **Slider + number input pairs** — type 0.93 or drag, both work

### Frontend

- Alpine.js SPA (no build step), Alpine loaded locally
- Sticky topbar (z-index 20) + sticky library toolbar (`top: var(--topbar-height)`)
- Live JS toast system + SSE job stream (`/api/generate/jobs/<id>/stream`)
- NoCacheStaticMiddleware to prevent webview from holding old HTML

### Backend

- FastAPI + uvicorn, port 47870
- `_GEN_LOCK` serializes GPU-bound generations
- Job history persisted to `app/output/.history.json` (survives restarts)
- HF cache structure detection + flat-folder import (for legacy launcher imports)

---

## Format reference

```
## [X.Y.Z] — YYYY-MM-DD

### Added
- New engines / models / UI features

### Changed
- Behavior changes to existing features

### Fixed
- Bug fixes

### Removed
- Dropped engines / deprecated UI

### Notes
- Migration steps, breaking-change details, etc.
```
