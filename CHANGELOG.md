# Changelog — Voice Studio KH

All notable changes to Voice Studio KH are documented here.

Versioning follows [Semantic Versioning](https://semver.org/) with this project-specific interpretation:

- **MAJOR** (1.x.x → 2.x.x) — breaking change. Re-install required.
- **MINOR** (1.1.x → 1.2.x) — new engine / new feature / new model family. **Re-run "Install Generation"** to pick up new Python deps.
- **PATCH** (1.2.0 → 1.2.1) — bugfix / UI tweak / catalog entry within an existing family. **Just run Update** from the Pinokio sidebar.

---

## [1.10.3] — 2026-07-13

### Added — official OmniVoice voice cloning on Apple Silicon

- Added the official `k2-fsa/OmniVoice` checkpoint to the Models catalog. It runs through the installed PyTorch/MPS API and supports cloning from a 3–10 second reference clip in the Voices library.
- Kept the existing `mlx-community/OmniVoice-*` variants as the lightweight voice-design path. The Generate UI now makes the backend choice explicit instead of implying that every OmniVoice entry can clone.
- Reference transcripts are used when saved; otherwise OmniVoice may auto-transcribe the reference clip. A generated voice-design sample can be saved to the library and reused as a cloning reference.

### Verification

- Python compilation, JavaScript syntax checks, startup regression test, catalog smoke test, and `audit_truth.py` all pass.
- The live server was not restarted during this change. Download the new official checkpoint from Models, then use the existing Update/restart workflow before first generation.

No new package is required beyond the already-installed OmniVoice package; **Just run Update**.

## [1.10.2] — 2026-07-13

### Fixed — Voice Studio restarts no longer preload every model library

- Server startup now checks whether PyTorch, Transformers, and Kokoro are installed without importing their full model stacks. Real imports still happen when generation starts, and the diagnostics endpoint still performs deep package checks on demand.
- This removes the restart-time import chain through PyTorch, spaCy, pandas, SciPy, and scikit-learn. On the reference Mac, the full backend import fell from 16.7 seconds to about 3 seconds.
- Normal engine availability checks are lightweight too, and the UI no longer waits for the deliberate deep diagnostics scan before becoming usable.
- Added a regression test that fails if the generation module imports a heavy model library during server startup.

No launcher or dependency changes; **Just run Update**.

## [1.10.1] — 2026-07-13

### Fixed — saved fleet credentials apply without restarting Voice Studio

- Protected requests now verify against the current owner-only fleet-token file instead of a startup snapshot. Studio Hub credential saves and rotations take effect immediately, and authenticated browser cookies follow the current value.

Verified with a live-rotation middleware regression test plus the full test suite. No launcher, voice engine, or dependency changes; **Just run Update**.

## [1.10.0] — 2026-07-12

### Added — secure fleet access and capability contract

- Remote API and output access now requires the automatically shared StudioHub fleet token; loopback Pinokio use remains passwordless.
- Browser writes are same-origin protected, authenticated browser sessions use an HttpOnly cookie, and remote Studio pages prompt once per tab when a token is needed.
- Added the normalized `GET /api/capabilities` contract for Hub preflight and rolling-update orchestration, including TTS, voice cloning, and speech-to-text support.

### Verification

- Python and JavaScript syntax checks pass. Security-contract tests cover public health/capability routes, protected catalog access, accepted fleet credentials, cross-origin write rejection, and private token permissions.

## [1.9.1] — 2026-07-12

### Fixed — Voice generation failures and misleading controls

- OmniVoice now unwraps its one-item batch before writing WAV audio. The old code
  passed the outer list to SoundFile, which interpreted thousands of samples as
  channels and left an empty, unreadable output file.
- Voxtral now tolerates its `voice_num_audio_tokens` tekken metadata with current
  `mistral-common`; mlx-audio already reads that mapping, so the compatibility shim
  ignores only the unsupported constructor keyword while loading the tokenizer.
- Chatterbox's Generate button now requires a reference-library voice, and all
  disabled Generate states explain the actual missing field instead of always saying
  “Type some text.” OmniVoice guidance now lists its real fixed trait vocabulary and
  provides valid presets instead of suggesting unsupported free-form prose.
- Failed generations remove partial or empty WAV files.

### Security

- Hugging Face token storage is forced to owner-only (`0600`) permissions.
- Remote version metadata is rendered with `textContent`, closing the update-banner
  HTML injection path.
- FastAPI/Starlette were raised to patched releases identified by `pip-audit`.

### Verification

- Python/JavaScript/HTML checks pass; the Voxtral tokenizer loads under the scoped
  compatibility shim, OmniVoice output-shape handling is covered with synthetic data,
  and the generation truth audit remains clean. LAN binding/CORS remain unchanged as
  part of the documented service-mode contract.

## [1.9.0] — 2026-07-10

### Added — Audio-generator overhaul: live feedback, per-job actions, disk management

A batch of generator improvements (frontend live immediately; the backend bits below activate after one **Update** — no new Python deps, so no "Install Generation" needed):

- **Live generation feedback.** The progress readout showed "Generating… undefined/undefined" — it read fields that don't exist on the job. Now a real bar + percentage + elapsed time. The queue panel is sticky (stays visible while you scroll) and shows a live progress bar on the running job; the "Generating…" strip echoes the same. *(Backend: workers now report `progress` — per-chunk for Kokoro, phase-based otherwise.)*
- **Per-generation actions.** Each result now has **Reveal** (show the file in Finder), **Delete** (remove it and its WAV — two-click confirm), plus the existing Download and Reuse. *(Backend: new `DELETE /api/generate/history/<built-in function id>`.)*
- **Disk management.** A footer shows how many files and how much disk the outputs use, with one-click prune ("keep newest 50" / "delete > 30 days"). Fixes outputs piling up unbounded. *(Backend: `GET /api/output/stats`, `POST /api/output/prune`.)*
- **Auto-play** toggle — plays the newest result when a generation finishes.
- **Friendlier empty state** when there are no generations yet.

### Fixed — Three more native `confirm()` dialogs replaced with a webview-safe modal

Remove-token, Import-move, and Remove-voice used `window.confirm()`, which Pinokio's embedded webview silently blocks — so those buttons did nothing. All now use an in-app confirm modal (same class of bug as the Clear-history fix in 1.8.8).

### Notes
- MINOR bump (1.8.8 → 1.9.0). Frontend (app.js/index.html/style.css) is live on reload; the new endpoints + per-chunk progress need one **Update** (restart) — the UI degrades gracefully until then (disk/delete just show a "run Update" hint). Deferred: MP3/FLAC export (needs an audio-encoder dependency).

---
## [1.8.8] — 2026-07-10

### Fixed — "Clear history" now works; added an "Open outputs folder" button

- **Clear history** used the native `window.confirm()` dialog, which Pinokio's
  embedded webview can silently block (it returns false) — so the button did
  nothing. Replaced with a webview-safe two-click confirm: the first click arms
  the button ("Click again to clear"), a second click within 3s clears. It now
  also keeps any in-progress job on screen and only trims finished entries.
- **Open outputs folder** — new button in the Recent generations header that
  reveals the folder holding every generated WAV in Finder (via the existing
  `/api/reveal`). Handy because the history index and the files on disk can
  diverge (clearing history keeps the WAVs).

### Notes
- PATCH bump (1.8.7 → 1.8.8) — frontend only (app.js + index.html + style.css). Live on reload; no restart needed.

---
## [1.8.7] — 2026-07-10

### Fixed — download ETA settle-guard, real catalog sizes, memory floors, and dead-entry cleanup

**Absurd download ETA (`downloads.py`).** The speed EMA's first sample was taken while `snapshot_download()` was still resolving repo metadata, before real bytes landed — a near-zero "instant" speed (e.g. 1.57 KB over ~3 sec) that, divided into a multi-GB remaining total, produced an ETA like "99679m 03s" seconds after clicking Download. `eta_seconds` is now suppressed until the job has ≥3 s of runtime so the EMA settles to a representative rate first.

**Unreadable long durations (`app.js`).** `formatDuration()` only had `Xm YYs`, so a legitimately long ETA rendered as e.g. "734m 12s". Added hour/day rollup (`Xh YYm`, `Xd YYh`); short job-render durations are unchanged.

**Catalog sizes corrected to real Hugging Face download sizes.** 13 entries were under-counted because they bundle files the old estimate ignored — OmniVoice (4-bit 0.5→1.1 GB, 8-bit 0.9→1.5, bf16 1.3→2.0) and Spark-TTS ship an audio-tokenizer / wav2vec2 encoder; VibeVoice-fp16 1.0→2.1; Kokoro-82M-4bit 0.18→0.67; and others. Verified against the HF API `blobs=true` file listing, with each entry's `ignore_patterns` applied to match what `downloads.py` actually fetches.

**Memory floors recalibrated.** Seven small TTS models were over-classified — e.g. OmniVoice fp32 (a 3.3 GB, 0.6B model) required a 16 GB floor, so on a 16 GB Mac it read "⚠ tight". Floors now reflect the real footprint (fp32 → 8 GB, so a 16 GB Mac reads "✓ fits"). Same for Qwen3-TTS-1.7B, chatterbox-fp16, Spark-8bit/bf16, VibeVoice-fp16, and OmniVoice-bf16.

**Removed 3 entries.** `mlx-community/chatterbox-mlx-4bit` and `-8bit` return HTTP 401 (undownloadable) and were already superseded by the newer `chatterbox-4bit/8bit/fp16` in the same family; `Spark-TTS-0.5B-6bit` was a redundant middle tier between the 4-6bit (recommended) and 8bit variants.

**Checked, left unchanged:** the PyTorch VoxCPM / Kokoro / F5-TTS entries (a different runtime from their MLX ports — not duplicates). `py_compile` clean; catalog re-imports to 40 models.

## [1.8.6] — 2026-07-10

### Fixed — API examples now generate speech instead of copied FLUX images

The API tab and token help still contained Image Studio content: a FLUX repository,
`txt2img` requests, image dimensions, and PNG download routes. Every generated example
would fail against Voice Studio's actual API. Curl, JavaScript, Python, re-download, job
search, endpoint summaries, and token guidance now use `txt2speech`, voice fields, and WAV
audio routes. Import examples now name a voice model instead of FLUX, and the workspace
also hides a stale voice preset when no model is selected.

### Verification

- Cross-checked every documented route and request field against `backend/main.py`, ran
  JavaScript and HTML validation, and exercised the API tab against the live frontend.
- Byte formatting remains intentionally decimal for downloads; binary units remain only
  for the voice-upload size limit, where the code and limit use MiB-sized byte constants.

---

## [1.8.5] — 2026-07-10

### Changed — Generate opens with a focused voice workspace overview

The Generate tab previously dropped straight from a plain heading into warnings and
dependency details. It now opens with a compact workspace overview showing the active
model, voice, and compute target before the existing controls. The header icon and active
tab also use the refined Studio treatment established in Image Studio.

### Verification

- Validated Alpine expressions, JavaScript syntax, HTML parsing, and desktop/mobile
  layout against the live no-cache frontend without restarting the managed service.
- Generation controls, diagnostics, engine behavior, saved voices, and API routes were
  checked and deliberately left unchanged.

---

## [1.8.4] — 2026-07-10

### Changed — Version now shown as a badge in the top-right header (consistent across all sibling apps)

The app version was displayed inconsistently across the Studio fleet (bottom footer on
some, top-right on Chat, missing on Video). It's now a small `v1.8.4`-style badge in the
top-right of the header on every app, matching Chat Studio — visible at a glance without
scrolling to a footer.

### Notes

- PATCH bump (1.8.3 → 1.8.4) — frontend only (`index.html` + `style.css`). Served with
  no-cache headers, so it appears on the next browser reload without a restart.

---
## [1.8.3] — 2026-07-10

### Fixed — Update reinstalls the service (rewrites the launchd plist) instead of kickstarting a stale one

The service scripts were renamed from generic `serve.sh` / `watchdog.sh` to
`<app>-serve.sh` / `<app>-watchdog.sh`, and the launchd plist's `ProgramArguments`
now points at the renamed script. A machine with the service already installed has
a plist pointing at the OLD `serve.sh` — so a plain **kickstart** (`restart_service.sh`)
would relaunch a plist pointing at a now-deleted path and the service would fail to
come back up after an update.

`update.js` (and `install_generation.js`) now restart the service with
**`install_service.sh`** instead of `restart_service.sh`. `install_service.sh`
regenerates the plist to match the current on-disk scripts *before* relaunching
(bootout → bootstrap → kickstart), so the rename is folded in automatically. It's
idempotent and safe to run on every update.

### Notes

- PATCH bump (1.8.2 → 1.8.3) — launcher scripts only. Applies only where the app
  runs as a launchd service (`service/.installed`); the `start.js` path is unchanged.

---
## [1.8.2] — 2026-07-10

### Added — In-app auto-check banner: tells you when to update instead of failing silently

On load the web UI checks `GET /api/update-status` and shows a dismissible banner when this install needs attention:

- **A newer version is published** — compares this install's VERSION against the repo's published VERSION (fetched from GitHub raw, cached ~6h, in a background thread so it never blocks). Banner: "⬆ Update available (vX → vY)", pointing at the one-click **Update** button in the Pinokio sidebar.
- **The generation engine isn't installed** — detects the missing stack directly. Banner: "⚠ Generation engine not installed — the Generate tab won't work", pointing at **Install Generation** (or **Update**) in the sidebar. This is the exact silent failure that let a broken generation install look fine before.

Detect-in-app, apply-via-sidebar: a sandboxed web page (external browser, Tailscale) can't reliably drive Pinokio's script runner, so the banner points at the sidebar's one-click Update rather than trying to self-update. The banner is self-contained (no framework coupling) and degrades silently if the endpoint isn't live yet (e.g. a running service that hasn't restarted onto the new build).

### Notes

- PATCH bump (1.8.1 → 1.8.2) — backend adds `GET /api/update-status`; frontend adds the banner to `index.html`. No change to existing features.

---
## [1.8.1] — 2026-07-10

### Fixed — One-click Update that actually works, and generation installs that don't silently fail

Overhauled the update/install flow. It was tedious and, worse, quietly broken:

- **One Update button, correct in every run mode.** The old "Update & Restart" was hardwired to stop/start `start.js`, but in production this app runs as an always-on launchd **service** — so it stopped nothing and then launched a *second* server that fought the service for the fixed port. The unified `update.js` now detects the mode and restarts the **real** server (kickstart the service **or** start `start.js` — never both), so updating no longer requires manually stopping production first.
- **Generation deps refresh on the same click.** `update.js` used to install only the base deps; heavy ML deps came from a separate "Reinstall Generation" button, so a release that bumped a model dependency silently didn't apply on Update. Update now refreshes generation deps too (when generation is installed) — no second button to hunt for.
- **Install from source, not a drifted lock.** `install_generation.js` (and Update) now install from `requirements-generation.txt`, the authoritative range file. The generation `.lock.txt` had drifted — on some machines it contained only base packages, so "Install Generation" installed nothing while the UI still reported success. Source-first can't have that failure mode.
- **Verify-then-notify.** After installing, the key modules are imported; a failure breaks the run and withholds the "installed" notification. The old script fired "Generation engine installed" unconditionally — even on total failure.
- **"Update & Restart" folded into "Update"** (kept as a back-compat alias that forwards to `update.js`).

### Notes

- PATCH bump (1.8.0 → 1.8.1) — launcher scripts only (`update.js`, `install_generation.js`, `update_and_restart.js`, `pinokio.js`). No app-code change.
- Verified: all launcher scripts load; the menu renders a single mode-aware "Update"; generation deps import in the env.

---
## [1.8.0] — 2026-07-09

### Added — dependency lockfiles: fresh installs are now reproducible forever

`requirements.txt` / `requirements-generation.txt` use version **floors** (`>=`), so a fresh install months from now would resolve to whatever PyPI serves that day — one breaking release in any dependency (torch, mlx, kokoro, …) bricks the app on a new machine while existing installs keep working. Same fix Chat Studio shipped in its v1.19.0.

- **`app/requirements.lock.txt`** — the pinned phase-1 set (36 packages, compiled from the floors constrained to the verified env's installed versions).
- **`app/requirements-generation.lock.txt`** — the FULL verified env (240 packages), including the two git-sourced engines (`mlx-audio`, `omnivoice`) **pinned to exact commits** — previously these installed whatever the upstream repo's HEAD was that day, the single most drift-prone part of this app.
- `install.js`, `install_generation.js`, and `update.js` now install from the locks. Upgrade flow (edit floors → verify → regenerate both locks → commit) is documented in each lock's header.

Verified: phase-1 lock resolves all-satisfied against the live env; both launcher scripts pass `node --check`; python was already pinned (`python=3.12`).

### Notes

- MINOR bump (1.7.5 → 1.8.0) — install-pipeline change, no package versions changed (locks pin exactly what's installed and verified).

---

## [1.7.5] — 2026-07-08

### Fixed — Start now refuses to compete with startup service mode

The startup service already takes over port `47870` when installed, and the service-mode sidebar hides the normal Start button. But `start.js` itself still had no direct guard, so any stale menu, direct script launch, or automation path could still try to start a second Uvicorn server on the same fixed port and fail with "address already in use."

`start.js` now checks for `service/.installed` before launching the server. If service mode is active, it exits immediately with a clear message telling the user to use **Open UI (service)** or uninstall the startup service first. The existing Uvicorn URL capture and `local.set` behavior are unchanged.

**Verified:** `node --check start.js`, direct inspection against the required Pinokio URL-capture pattern (`input.event[1]`), and current logs showing service install already takes over the same port by stopping the previous Pinokio Start process.

### Notes

- PATCH bump (1.7.4 → 1.7.5) — launcher guard only, no app/backend change. **Just run Update**.

## [1.7.4] — 2026-07-01

### Fixed — UX/UI consistency pass: unified the download flow, chip colors, and one more GB-formatting gap

Requested as a follow-up audit alongside v1.7.2/v1.7.3: "run a ux/ui consistency test and fix and make it better." Audited chip color semantics, byte/size formatting, download interaction patterns, and terminology across the whole frontend. Applied the changes that had real, user-visible impact; explicitly skipped low-value ones (see below).

**Chip color system consolidated (`style.css`):** Three independent, hardcoded color palettes were all expressing the same "good / caution / bad" semantics with subtly different hex values — `.chip.ok/.warn/.bad` (the canonical one, backed by the `--ok`/`--warn`/`--bad` CSS variables) vs. `.chip.engine-ready/-pending/-missing` (its own greens/ambers/oranges) vs. `.chip.fit-ok/-tight/-risky` (a third palette), plus `.dep-chip` and `.diag-pending`/`.diag-row-pending` each hardcoding their own amber. All of these now reference `var(--ok)`/`var(--warn)`/`var(--bad)` via the same `color-mix(in srgb, var(--X) N%, transparent)` pattern already used elsewhere in the stylesheet. Result: every "ready/good," "caution/pending," and "missing/risky" indicator in the app — engine-readiness chips, RAM-fit chips, dependency chips, diagnostics rows — now renders the exact same green/amber/red, instead of 3 different greens and 2 different ambers that all meant the same thing.

**Two more raw byte-formatting gaps found and fixed (same bug class as v1.7.2/v1.7.3):** The Subtitle-models grid card and the Whisper-model `<select>` dropdown on the Subtitles tab both built their size text as `m.size_gb + ' GB'` directly, bypassing the shared `formatGb()` helper entirely — so a Whisper model under 1 GB (e.g. `whisper-base`, 0.15 GB) showed "0.15 GB" instead of "150 MB," while the exact same model showed the correctly-formatted size everywhere else in the app. Both now call `formatGb(m.size_gb)`, matching every other size display.

**Download confirmation flow unified across TTS and Whisper models:** Clicking "Download" behaved differently depending on which tab you were on — TTS models opened a confirmation dialog (size, RAM requirement, gated-repo token prompt) via `confirmDownload()`, while Whisper/subtitle models downloaded immediately with no confirmation via a separate `downloadWhisperModel()` path. Same button label, same icon, two different behaviors. Whisper downloads (both the Models-tab card and the Subtitles-tab inline download button) now route through the same `confirmDownload()` → `pendingDownload` → `startDownload()` flow as every other model. The confirm dialog's memory-requirement and recommended-hardware lines are now conditionally shown (`x-show`) since Whisper models don't carry those fields — they simply don't render for Whisper, rather than showing `undefined`. `startDownload()` now detects whether the confirmed model is a Whisper model and, if so, runs the same completion-polling loop `downloadWhisperModel()` used to run standalone (kept as `_pollWhisperUntilCached()`); the old duplicate method was removed.

**Terminology aligned:** the Subtitle-models grid card showed "✓ ready" for a cached model while every other tab in the app calls the same on-disk state "✓ cached" (see the Models-tab chip legend). Changed to "✓ cached" to match.

**Checked and deliberately left unchanged (real inconsistencies, but not worth the churn or not actually bugs):**
- The Download-confirm modal's Cancel button (`class="ghost"`, no `.btn`) vs. other modals' Cancel buttons (`class="btn ghost"`) — verified in `style.css` that `.btn` has no bearing here: the applicable rule is the tag+class selector `button.ghost`, which matches regardless of whether `.btn` is also present. Zero rendering difference, so not a real bug (same conclusion reached earlier this session for the API-docs Copy buttons).
- "Clear" vs. "Remove" vs. "Discard + re-record" across various destructive actions — re-checked each instance in context; "Clear" is consistently used for bulk/list-clearing actions (history, filters, finished downloads) and "Remove" for single-item deletion from a persisted collection (voice library). Consistent on inspection, not a real bug.
- Empty-state copy tone varies a little (conversational vs. neutral vs. directive) across tabs — real but low-impact stylistic drift; left alone to avoid rewriting seven unrelated strings with no functional benefit.
- The "🚀 Ready to generate" filter chip vs. the "✓ Cached" filter chip on the Models tab — these looked like a possible duplicate label at first glance, but they filter on two genuinely different conditions (cached-only vs. cached-**and**-engine-installed), each with a clarifying tooltip. Not a bug.

### Notes

- PATCH bump (1.7.3 → 1.7.4) — frontend-only (`app.js`, `index.html`, `style.css`), no backend/schema change. Already live on the running server (static assets, no-cache headers) — `Update` makes it permanent.
- Verified via `curl` against the live server (port 47870 is the user's own running Pinokio instance, not something this session restarts) plus a Node.js syntax check on `app.js`.

---

## [1.7.3] — 2026-07-01

### Fixed — Audited every byte/size display in the app for the same GB-vs-GiB bug; found and fixed two more instances

Follow-up to v1.7.2's download-progress fix — asked "does this affect other models / other places too?" Audited every byte-formatting code path in the app (frontend and backend) rather than assuming the one fix covered everything.

**Already covered by v1.7.2, confirmed universal:** `downloadCaption()` — the single shared renderer for download progress — is called from exactly two places: the Models-tab per-card "active download" caption *and* the Downloads-tab job table. Both read from the same `humanBytes()` helper, and the underlying job data comes from one shared `manager.list_jobs()` regardless of engine family. So the original fix already applies to **every** downloadable model — TTS engines and Whisper alike — not just the one that got reported.

**Found two more instances of the same bug class, now fixed:**

- **`formatGb()`** (used for the *static* size shown on every model card, the RAM-planner's "best pick" caption, and the download-confirmation dialog) rounded sub-1 GB values with `× 1024` instead of `× 1000`. Real impact: any catalog entry under 1 GB — Kokoro (0.34 GB), whisper-tiny (0.07 GB), whisper-base (0.15 GB), several MLX quant variants — displayed an advertised size ~2.4% larger than its real decimal size (e.g. Kokoro showed "348 MB" instead of "340 MB"). Same root cause as v1.7.2, just a different formatter that hadn't been touched. Now uses `× 1000`, matching `humanBytes()` and the catalog's own convention.
- **`_setSubtitleFile()`** (the file-size caption shown when you pick/drop an audio clip on the Subtitles tab) had its own inline binary (`/1024/1024`) computation instead of calling the shared `humanBytes()`. Not a cross-reference bug (there's no separate "advertised size" for a user's own file to disagree with), but a duplicate, inconsistent implementation — replaced with a call to `humanBytes()` so every byte count in the app now goes through exactly one, correct, decimal formatter.

**Confirmed correct and deliberately left unchanged:** `system_info.py`'s RAM-detection (`hw.memsize / 1024**3`) — installed memory capacity is conventionally reported in binary GiB (matches Apple's own "About This Mac"), which is a different domain from network/file-transfer byte counts. Not the same bug; changing it would make the RAM figure wrong instead of right. Also left alone: a Python code sample string on the API docs tab (`len(img)//1024`) — that's illustrative example text for a different, hypothetical app, not live app logic.

### Notes

- PATCH bump (1.7.2 → 1.7.3) — pure frontend formatting, no backend change, no schema change. Already live on the running server (static assets, no-cache headers) — `Update` makes it permanent.
- With this, every byte/size display in the app — download progress, catalog card sizes, RAM-planner picks, download-confirmation dialogs, and file-picker previews — uses one consistent decimal (SI) convention, matching what Hugging Face's own site shows and what `du`/Finder will report once a file is fully on disk.

---

## [1.7.2] — 2026-07-01

### Fixed — Download progress showed 1.5 GB for a model the catalog lists as 1.6 GB (unit mismatch, not data loss)

Reported: downloading `mlx-community/whisper-large-v3-turbo` — the Models tab lists it as **1.6 GB**, but live progress only ever showed **1.5 GB**, and the job seemed to vanish from the Downloads tab entirely.

**Root cause, verified live against a real download job:** the model's `weights.safetensors` is exactly `1,613,979,758` bytes.

- Divided the standard (decimal/SI) way — same convention HF's own site and our static catalog `size_gb` use — that's **1.614 GB**, which rounds to the "1.6 GB" shown before downloading.
- The frontend's `humanBytes()` helper (used only for *live* download byte counters) divided by **1024** at each step instead — same bytes, but that's **1.503 GiB**, mislabeled "GB" in the UI.

Same bytes, two unit systems, two different-looking numbers. Nothing was actually missing.

**Fix:** `humanBytes()` in `app.js` now divides by 1000 (decimal) like everything else in the app, so live download progress agrees with the catalog's advertised size. Verified against the real in-flight job: `1,613,979,758` bytes → **1.61 GB**, consistent with the catalog's "1.6 GB" (small residual rounding — 1 vs 2 decimal places between the two display contexts — is expected and no longer looks like data loss).

### Diagnosed — why the download appeared to disappear from the Downloads tab

Not a code bug: `GET /api/downloads` and the SSE stream both return every in-memory job unconditionally, confirmed live (a fresh whisper download showed up immediately). What actually happened: **the server was restarted while the download was mid-flight** (the timestamps on a stray 0-byte `.incomplete` blob on disk lined up exactly with the last server restart). Download jobs are tracked in-memory only, so a restart — including our own "Update & Restart" button — silently drops any job in progress and leaves a partial blob behind. Re-triggering the download today picked up cleanly and is progressing normally; no code path prevented it from showing up.

Not changed in this release (flagged for later if it becomes a recurring annoyance): persisting in-flight download jobs across a server restart, and/or auto-detecting a stale `.incomplete` blob on startup to offer a one-click resume.

### On which Whisper model to use

`whisper-tiny` mis-transcribing (including the "wrong accent" pattern) is a well-known limitation of that model, not a bug — it's the least accurate tier in the registry, meant for quick tests only. `whisper-large-v3-turbo` (1.6 GB, the app's recommended default, currently mid-download as of this fix) is a large jump in accuracy and should resolve it. The full non-turbo `whisper-large-v3` (3.1 GB) is not a better default on 8 GB Macs — it shares the same unified-memory pool as any loaded TTS engine, and turbo already carries "near-large accuracy" per its own catalog note. `whisper-large-v3-turbo-q4` (0.5 GB) is the safer pick specifically for tight-RAM 8 GB machines if turbo's 1.6 GB footprint is ever a concern.

### Notes

- PATCH bump (1.7.1 → 1.7.2) — pure frontend formatting fix in `app.js`. No backend change, no new deps, no schema change. Already live on the running server without a restart (static asset, no-cache headers) — `Update` picks it up permanently.

---

## [1.7.1] — 2026-06-26

### Changed — Models tab split into "Audio Generator" + "Audio Transcriber" sub-tabs

The Models tab previously stacked the TTS catalog and the Whisper speech-to-text models on one long page. They're now two clean sub-tabs so the two model types don't muddle together:

- **🎙️ Audio Generator (TTS)** — the RAM planner, "Best for your RAM" picks, search/sort/family/capability/RAM-fit filters, and the TTS family cards. Sorting stays here, scoped to the generator catalog.
- **🎬 Audio Transcriber (Whisper · STT)** — the Whisper subtitle/transcription models, with a "ready" count badge on the tab when any are downloaded.

Defaults to the Generator sub-tab; the toggle is purely a view switch (no reload). **Frontend-only — a plain _Update_ is enough.**

---

## [1.7.0] — 2026-06-26

### Added — RAM planner: interactive memory slider + live "Best for your RAM" picks (Models tab)

The Models tab gained a **hardware planner** so you can size models to a machine you don't own yet — set the unified-memory budget and every fit chip re-scores instantly.

- **RAM slider + numeric entry + tier presets** (8 / 16 / 24 / 32 / 48 / 64 / 128 / 256 / 512 GB). Defaults to your detected RAM; drag/type to *preview* a different Mac (e.g. plan an M3 Ultra 512 GB before buying it). A `↩ My Mac` button snaps back to detected. The chosen budget persists across reloads.
- **Live hardware fit** — per-card fit chips (✓ fits / ⚠ tight / ✗ over budget) are now scored **client-side** against the slider value via `fitFor()`/`effectiveRam`, so they update with no server round-trip.
- **✨ Best for your RAM** — a recommendation strip surfaces the highest-quality model in each lane (overall / voice cloning / multilingual / expressive / streaming) that still fits the budget. At 8 GB it favours the lighter tiers; at 512 GB it upgrades to the full-precision builds.
- **Segmented "RAM fit" filter** (All / ✓ Fits / ⚠ Tight / ✗ Over), mirroring the Chat Studio model-tab control for a consistent look across the suite. The old binary "Fits my Mac" chip is folded into this.

> Note: open TTS models are small — catalog RAM floors top out at 16 GB — so on a big machine essentially everything fits; the planner's upside there is picking the highest-precision tier and previewing headroom.

**Frontend-only — no new Python dependencies. A plain _Update_ from the Pinokio sidebar is enough (no re-install / Install Generation needed).**

---

## [1.6.3] — 2026-06-06

### Fixed — Whisper transcription `ImportError: cannot import name 'ReasoningEffort'` (dependency drift)

A Mac mini hit this transcribing with `mlx-community/whisper-tiny`:

```
Whisper model mlx-community/whisper-tiny ships no HF processor, and the fallback
processor from openai/whisper-tiny couldn't be loaded
(ImportError: cannot import name 'ReasoningEffort' from 'transformers' ...)
```

**Diagnosis — verified, not assumed.** Reproduced on the dev box: `WhisperProcessor.from_pretrained("openai/whisper-tiny")` loads **fine** there, and `from transformers import ReasoningEffort` fails everywhere (the symbol isn't in transformers 5.9.0). So the failing Mac had a **different, drifted environment** — not a code bug.

**Root cause: floating dependency pins.** `requirements-generation.txt` had `transformers>=4.55` (any version ≥ 4.55) and `mlx-audio @ git+…mlx-audio.git` (always latest **master**). Every Mac that ran *Install Generation* on a different day resolved a different transformers + a different mlx-audio commit. The mini drifted into a combo where mlx-audio's newer code path expects `transformers.ReasoningEffort` but its transformers doesn't export it. The dev box happened to land on a working combo (`transformers 5.9.0` + `mlx-audio @14add66`).

### Fix 1 — Pinned the whole transformers + MLX stack to one verified-good set

`requirements-generation.txt` now pins the exact combo that's verified working end-to-end (TTS engines + Whisper STT):

```
transformers==5.9.0
tokenizers==0.22.2
mlx==0.31.2
mlx-lm==0.31.3
mlx-audio @ git+https://github.com/Blaizzy/mlx-audio.git@14add666b5313cadff94a231ee11979f6ac1adf7
```

The `mlx-audio` git pin (an **exact commit**, not floating master) is the biggest stability win — every server now converges to one identical environment. To upgrade later: bump the commit + `transformers` together, verify TTS + STT, then commit the new pins.

### Fix 2 — Hardened the processor fallback (resilience + clear errors)

`_attach_processor()` in `transcription.py` now:
- Tries a **narrow `WhisperTokenizer` import first** (all mlx-audio's whisper `get_tokenizer()` actually reads is `processor.tokenizer`). This dodges the heavier `WhisperProcessor` import chain that can blow up on unrelated drifted symbols like `ReasoningEffort`. A tiny `_TokenizerOnlyProcessor` shim exposes just `.tokenizer`. Verified to produce identical transcription.
- Falls back to the full `WhisperProcessor` if the narrow path fails.
- If both fail, raises a **clear, actionable error** that distinguishes a *dependency mismatch* ("re-run Install Generation — it now pins a known-good set; or `uv pip install 'transformers==5.9.0' 'tokenizers==0.22.2'`") from a *network* failure — instead of surfacing a raw `ImportError`.

### Verification

End-to-end through the real `TranscriptionManager.transcribe()`: `whisper-tiny` loads, the tokenizer-only path attaches from `openai/whisper-tiny`, and it transcribes a clip into valid SRT. `whisper-large-v3-turbo`'s base tokenizer (`openai/whisper-large-v3-turbo`) confirmed to load too. `audit_truth.py`: NO DRIFT.

### How to apply across all your Mac servers

On **each** Mac running Voice Studio:

1. **Update** from the Pinokio sidebar (pulls v1.6.3 with the pinned `requirements-generation.txt`).
2. **Re-run "Install Generation"** — this is the important step; it forces the environment to the pinned `transformers==5.9.0` + `mlx-audio @14add66` set. (`uv` will downgrade/upgrade as needed to match.)
3. **Stop → Start** the server.

Manual equivalent (if not using the sidebar), from the app's conda env:

```
uv pip install 'transformers==5.9.0' 'tokenizers==0.22.2' 'mlx==0.31.2' 'mlx-lm==0.31.3' \
  'mlx-audio @ git+https://github.com/Blaizzy/mlx-audio.git@14add666b5313cadff94a231ee11979f6ac1adf7'
```

After that, every server has the identical working environment, and any Whisper model (tiny → large-v3-turbo) transcribes. **You can keep the 0.5 GB `whisper-large-v3-turbo-q4`** on the 8 GB mini — this fix unblocks it.

### Notes

- PATCH bump (1.6.2 → 1.6.3) — a dependency change, so it **requires re-running Install Generation** (same as v1.5.1's `mistral-common` addition). No new engines, no schema change.
- The earlier advice to "switch to the 1.6 GB full turbo to sidestep the broken fallback" was a *workaround*, not a fix — all models share the same processor-fallback code, so the version pin is what actually resolves it for every model.

---

## [1.6.2] — 2026-06-06

### Added — auto-restart the service after Update + a "Repair · take over port" button

Two follow-ups from the post-build audit:

- **Update now restarts the service.** A running launchd service keeps the *old* backend code in memory until restarted. `update.js` now ends with a `bash restart_service.sh` step gated on `{{exists('service/.installed')}}` — so after Update, an installed service is kicked to pick up the new code automatically. No-op if the service isn't installed.
- **"Repair · take over port" menu item** (service mode). Re-runs the installer (boot out → free the port → re-bootstrap), so any wedged/conflicting state is fixable in one click without the Terminal. Distinct from **Restart Service** (a quick `kickstart -k`).

### Fixed — take-over no longer risks killing connected clients
The port take-over in v1.6.1 used `lsof -ti tcp:PORT`, which matches **any** socket on the port — including connected clients (a browser tab, the Pinokio webview, an SSE stream). Clicking Install with the UI open could have killed your browser. Now filtered with `-sTCP:LISTEN` so **only the listening server** is targeted. Verified live: a real client connection is correctly excluded.

### Notes
- PATCH — service scripts + update.js only. `Update`, then re-run **Install as Startup Service** once so the safer take-over + repair are in place.

---

## [1.6.1] — 2026-06-06

### Fixed — "Check Service Status" is now clear + detects the double-run conflict

Two issues surfaced the first time the status button ran against a live service:

- **"Watchdog: not running" looked broken — it isn't.** The watchdog is a *periodic* agent (fires ~1s every 60s), so between checks it's idle by design. The status now says so explicitly instead of dumping a scary raw `state = not running`. The server line is also cleaner: `✓ loaded · running (pid N)`.
- **Port-conflict detection.** If you start the app via Pinokio's **Start** and *also* install the service, both fight for the same port — the service can't bind and launchd crash-loops (the err log fills with `[Errno 48] address already in use`, and the health check is unknowingly answered by the *Pinokio* instance). The status script now detects this from the service err-log and prints a clear **PORT CONFLICT** box.

### Changed — installing the service now cleanly takes over the port
The bigger fix: **Install as Startup Service** now **stops whatever is already listening on the port** (your Pinokio "Start" instance) right before it starts the service. So the common flow — *click Start, then Install Service* — now Just Works: the old instance is stopped, the service binds, no crash loop, no manual `pkill`. (Graceful TERM, then KILL any straggler.) It targets **only the LISTENING server** (`lsof -sTCP:LISTEN`) — never connected clients, so an open browser tab / the Pinokio webview / an SSE stream is left alone. Uninstalling does NOT auto-restart the Pinokio instance — click **Start** again if you want manual mode back.

### Notes
- PATCH — service scripts only; no app/deps change. `Update` to refresh, then re-run **Install as Startup Service** once so the new take-over logic is in place.

---

## [1.6.0] — 2026-06-06

### Added — one-click "Install as Startup Service" (always-on server + self-healing)

For running this on a headless/server Mac (e.g. a fleet reached over Tailscale), you can now make the app a real background service instead of opening Pinokio and clicking Start every time.

New sidebar button **❤️ Install as Startup Service** installs a macOS **launchd LaunchAgent** that:

- runs the server (`serve.sh` → uvicorn on **47870**) **at login**, so it returns automatically after a reboot;
- **restarts on crash** via launchd `KeepAlive`;
- ships a **health watchdog** agent (`watchdog.sh`, every 60s) that hits `/api/health` and relaunches the server if it hangs (alive-but-unresponsive — which KeepAlive can't catch).

No sudo needed (per-user agent). Once installed, the sidebar switches to a **service-mode menu** (see below) for managing it. Service logs go to `logs/service/`.

New files: `serve.sh`, `watchdog.sh`, `install_service.sh`, `uninstall_service.sh`, `service.js`, `unservice.js`. The serve/watchdog scripts are **self-locating** (resolve paths from their own folder) so the same files work on any Mac/username. The per-machine `service/.installed` marker (drives the menu) is gitignored.

### Service mode — manage it entirely from the sidebar
Once the service is installed, Pinokio no longer "sees" the app as running (launchd owns it, not Pinokio's Start). So the sidebar now switches to a dedicated **service-mode menu** that avoids the old contradiction (a "Start" button that would fight the service for the port):

- **Open UI (service)** / **Open in Browser** — go straight to the running server on its fixed port; you no longer need Pinokio's Start to reach it.
- **Check Service Status** (`service_status.js` → `status_service.sh`) — shows the launchd agent state, a live `/api/health` ping (✅ running / ❌ not responding), and the tail of the service log, all in the terminal. This is how you know it's actually up.
- **Restart Service** (`service_restart.js` → `restart_service.sh`) — `launchctl kickstart -k` for a manual kick.
- **Service Logs** — opens `logs/service/`.
- **Uninstall Startup Service** — removes both agents + the marker; the normal Start button comes back.

The "Start" button is hidden while the service is installed, so the two can't collide.

### Docs — power-cut recovery, explained
The install button prints, and the README documents, the three one-time **admin** settings needed for full hands-off recovery after a power outage (the button does NOT change these — you do them once per machine):
1. `sudo pmset -a autorestart 1` — power on automatically when electricity returns.
2. **Auto-login** — required so the Apple GPU (Metal/MLX) is available; a pre-login daemon can't use it.
3. **FileVault off** — otherwise reboot stops at the encrypted-disk password screen and never reaches login.

### Verified
- Headless launch path tested live: `conda_env/bin/python -m uvicorn backend.main:app` with `HF_HOME` set boots and answers `/api/health` (200) on a throwaway port, then shuts down clean.
- Shell scripts `bash -n` clean; plists pass `plutil -lint`; all `.js` parse.

### Notes
- MINOR bump — new feature, no new Python deps. `Update` from the sidebar to get the files, then click **Install as Startup Service** on each Mac.
- Use the **service OR** Pinokio's **Start** — not both (they share port 47870).

---

## [1.5.3] — 2026-06-06

### Fixed — downloads now grab companion codecs too (no surprise second download)

Some engines load a **second** model — an audio codec / tokenizer that lives in a *different* HF repo — at generation time. Downloading just the catalog model left that companion missing, so the first **Generate** triggered a surprise download (you saw it on Marvis: `tokenizer-e351c8d8-checkpoint125.safetensors` downloading at 59% mid-generation — that's the **Mimi codec** from `kyutai/moshiko-pytorch-bf16`).

Now a model download is **complete on the first run**:

- **Companion fetch** — after the main model, the downloader pulls each companion (verified against the engine source):
  - **Marvis** → `kyutai/moshiko-pytorch-bf16` (just the 1 Mimi codec file — the repo is ~15 GB, we take only what's needed)
  - **Orpheus** → `mlx-community/snac_24khz`
  - **Chatterbox** → `mlx-community/S3TokenizerV2`
  - (Voxtral, Qwen3, Kokoro, VoxCPM, OmniVoice, Spark, VibeVoice, F5 are self-contained — no companion.)
- **Honest "cached" badge** — a model now reads `cached` only when its companions are present too. Until then it shows `partial`, so the Models tab never claims "ready" while a hidden codec is still missing. Re-downloading fills in whatever's absent (resumable, won't re-fetch what you have).
- **Accurate progress** — the download size/percent now includes companion bytes.

### Notes

- Backend change — `Update` from the Pinokio sidebar, then Stop + Start the server. No new Python deps, no reinstall.
- Already-downloaded models keep working; their companions were pulled lazily in earlier sessions and are now recognized by the badge.

---

## [1.5.2] — 2026-06-06

### Changed — all results now live in one history list + clearer rows + a real Download button

Generate-tab output cleanup, all per the request:

- **Single results list.** Removed the separate "Latest generation" panel that sat in the generate area. Every finished result — newest first — now appears in **Recent generations** instead of the newest one being split out up top. While a job runs you get a small "⏳ Generating speech… your result will appear in Recent generations below" status; the moment it finishes, it lands at the top of the list. (Errors land there too, with their message.)
- **Easier-to-read attributes.** The model / voice / seed / render-time tags went from faint grey monospace text to readable bordered pills with icons (🎙 model · 🗣 voice · 🎲 seed · ⏱ render time).
- **Unmistakable Download button.** Each row's download went from a tiny `⬇` icon to a full **⬇ Download** button — bigger, boxed, filled accent color, with the ghost "↻ Reuse" stacked beneath it so the primary action is obvious.

### Notes

- Pure frontend (HTML/CSS/JS) — PATCH bump. Just `Update` from the Pinokio sidebar and hard-refresh the web UI (the assets are cache-busted on load).
- The old generate-area "Copy URL" action was part of the removed panel; Download + Reuse remain on every history row.

---

## [1.5.1] — 2026-06-05

### Fixed — Voxtral generation failed with "tekken tokenizers require mistral-common[audio]"

Voxtral-4B-TTS (added in 1.5.0) couldn't generate — its tekken tokenizer loads through `mistral-common`, and the audio path needs the `[audio]` extra. mlx-audio imports it *lazily* at tokenizer-load, so the engine module imported fine (which is why the 1.5.0 wiring check passed) but actual generation raised `RuntimeError: Voxtral TTS tekken tokenizers require mistral-common[audio]`.

**Fix:** added `mistral-common[audio]>=1.5` to `requirements-generation.txt` and installed it. Verified the two engine guards now clear — `MistralTokenizer` imports and `encode_speech_request` is present. (Marvis was double-checked too: its sesame-engine runtime deps — `mlx_lm`, the mimi codec, tokenizers — are all already present, no extra needed.)

> ⚠️ **Re-run "Install Generation"** from the Pinokio sidebar to pick up `mistral-common[audio]`, then Stop + Start the server.

### Added — clickable voice buttons for preset-voice families

Instead of typing a voice name into a free-text field, you now get a row of clickable voice buttons for families with a **verified** roster:

- **Voxtral** — 20 buttons (♂/♀, grouped label per language)
- **Marvis** — 2 (Conversational A/B)
- **Orpheus** — 8 (Tara, Leah, Jess, Mia, Zoe, Dan, Leo, Zac)
- **Kokoro-MLX** — its existing voice list, now as buttons

Clicking a button sets the voice and highlights it. The free-text field stays below as a custom override. Every button's id is verified against the installed engine source (Voxtral `VOICE_MAP`, Marvis `SPEAKER_PROMPTS`), so a click can't produce a phantom voice. **KittenTTS** and **VibeVoice** keep the free-text field — their exact rosters aren't verifiable without the model on disk, and I won't render buttons I can't guarantee.

### Notes

- The voice-button UI is pure frontend; the Voxtral fix needs the dependency install above.
- `audit_truth.py`: still 15 families, NO DRIFT.

---

## [1.5.0] — 2026-06-05

### Added — 2 new preset-voice TTS families: Voxtral-4B-TTS + Marvis TTS

Both are MLX-native, run on 8 GB Apple Silicon, and ship their own built-in voices (no cloning). Each voice was verified against the installed mlx-audio engine code — no phantom voices.

- **Voxtral-4B-TTS** (`mlx-community/Voxtral-4B-TTS-2603-mlx-4bit` + `-bf16`) — **20 preset voices across 9 languages** (en/fr/es/de/it/pt/nl/ar/hi). The voice name picks the language: `casual_male`, `cheerful_female`, `fr_female`, `hi_male`, … (the full `VOICE_MAP` is baked into the engine). Faster-than-real-time at 4-bit. Adds de/it/pt/nl/ar coverage Qwen3-TTS doesn't have.
- **Marvis TTS** (`Marvis-AI/marvis-tts-250m-v0.1`) — a 250M CSM/Llama conversational model by the mlx-audio author, built for low-latency streaming. 2 built-in voices: `conversational_a` (female), `conversational_b` (male). Fully self-contained — its prompt clips ship in the repo and `config.text_tokenizer` points back at itself, so it never falls back to the gated `sesame/csm-1b`.

Both use the generic mlx-audio worker (`voice_picker` mode) — no new worker code, no new Python deps (mlx-audio already bundles the `voxtral_tts` and `sesame` engines; verified they import clean in the installed env).

### Considered but NOT added — MeloTTS

Dropped on purpose. mlx-audio's `melotts` engine needs a converted repo (`bert_weights.npz` + sanitized weights); the original `myshell-ai/MeloTTS-*` repos ship PyTorch `.pth` instead, and no MLX-converted MeloTTS exists on the Hub. Wiring it would have been a guaranteed load failure, so it's intentionally left out rather than shipped broken.

### Fixed — MLX-only filter no longer hides MLX families

While wiring the above, found the `apple_optimized` flag (which the default-ON "🍎 MLX only" filter keys off) only credited `-mlx`-suffixed families plus `qwen3-tts`/`orpheus`. That silently hid **kittentts, vibevoice, omnivoice** (and would have hidden the two new families) from the Models tab under the default filter, even though all are MLX. Now every mlx-audio family is correctly marked `apple_optimized`.

### Notes

- New model families, but **no reinstall needed** — just `Update` from the Pinokio sidebar, then download Voxtral / Marvis from the Models tab.
- `audit_truth.py`: 15 families, NO DRIFT — every catalog family is wired and dispatched.

---

## [1.4.4] — 2026-06-05

### Fixed — Qwen3-TTS CustomVoice: removed 2 phantom preset speakers (Ethan, Chelsie)

Picking **Ethan** (or **Chelsie**) on the Qwen3-TTS CustomVoice model failed every time with the cryptic *"RuntimeError: mlx-audio didn't produce a wav file."* The real cause was buried one layer down:

```
ValueError: Speaker 'Ethan' not supported.
Available: ['serena','vivian','uncle_fu','ryan','aiden','ono_anna','sohee','eric','dylan']
```

The CustomVoice model ships **exactly 9 speakers** (verified against the model's own `config.json` → `spk_id` map). Our `QWEN3_PRESET_SPEAKERS` list carried **11** — two phantoms (`Ethan`, `Chelsie`) copied from an older Qwen roster that this model doesn't contain. They appeared in the dropdown and even passed the app's own validation (which was built from the same bad list), so the failure only surfaced as the generic no-wav wall from mlx-audio's silently-swallowed exception.

**Fix:** trimmed the list to the model's real 9 — Ryan, Aiden, Serena, Vivian, Uncle_Fu, Dylan, Eric, Ono_Anna, Sohee. The list is now documented as deriving from the model's `spk_id` map, with a guard note against re-adding speakers the model can't voice. (mlx-audio matches names case-insensitively, so the capitalised display IDs resolve fine.)

### Audit — checked every model's voice capability against its actual engine

Per the "verify, don't assume" rule, I introspected the installed mlx-audio engines + downloaded model files for **all** families. Result: Qwen3-TTS was the *only* family advertising voices the engine rejects. Full capability map recorded:

| Family | Voice mechanism | Status |
|---|---|---|
| Qwen3-TTS CustomVoice | 9 named presets | **fixed (was 11)** |
| Qwen3-TTS Base | clone (reference) | ✓ correct |
| Qwen3-TTS VoiceDesign | natural-language voice prompt | ✓ correct |
| VoxCPM2 / VoxCPM v1 | zero-shot / voice-design / clone — **no named presets** | ✓ correct |
| Kokoro | 28 named presets (curated English subset of 54) — all valid | ✓ correct |
| Orpheus / KittenTTS / VibeVoice | free-text voice field (tara, dan, leah…) | ✓ correct |
| Spark-TTS | attribute-based (gender + pitch) OR clone | ✓ correct |
| Chatterbox / F5-TTS / OmniVoice | clone (reference) only | ✓ correct |
| Bark | preset speakers (v2/&lt;lang&gt;_speaker_N) | ✓ valid format |

### Notes

- PATCH bump — catalog/metadata fix within an existing family. Run `Update` from the Pinokio sidebar.
- Image / Music apps unaffected — they have no preset-voice lists (the bug class is VoiceStudio-specific). Their analogous drift is already guarded by `audit_truth.py`.

---

## [1.4.3] — 2026-05-27

### Fixed — "Processor not found" on transcription (affected ALL Whisper models, not just q4)

A transcription attempt returned `400: "Processor not found. Make sure the model was loaded with a HuggingFace processor."` The report attributed it to the quantized `whisper-large-v3-turbo-q4` repo "missing its HF processor," with the suggested fix being to download the full 1.6 GB `whisper-large-v3-turbo` instead.

**Verified the claim — it's wrong, and the suggested fix wouldn't have worked.** Checked all six whisper repos' file manifests on Hugging Face:

```
mlx-community/whisper-large-v3-turbo      → config.json, weights.safetensors   ❌ no processor
mlx-community/whisper-large-v3-turbo-q4   → config.json, weights.npz           ❌ no processor
mlx-community/whisper-large-v3-mlx        → config.json, weights.npz           ❌ no processor
mlx-community/whisper-small-mlx           → config.json, weights.npz           ❌ no processor
mlx-community/whisper-base-mlx            → config.json, weights.npz           ❌ no processor
mlx-community/whisper-tiny                → config.json, weights.npz           ❌ no processor
```

**None of them bundle the HF processor** (`preprocessor_config.json`, tokenizer, vocab). The full `whisper-large-v3-turbo` has the exact same problem as the q4 — downloading it would have hit the identical error after 1.6 GB. The error is universal, not q4-specific.

### Root cause

mlx-audio's whisper `post_load_hook` runs `WhisperProcessor.from_pretrained(<local snapshot>)`. Since the mlx-community repos don't ship processor files, that call fails, `model._processor` is left `None`, and `get_tokenizer()` raises "Processor not found" at transcribe time.

### Fix

mlx-audio computes the mel spectrogram **itself** from the model's own config (`log_mel_spectrogram(audio, n_mels=self.dims.n_mels)`) and uses the processor **only** for its tokenizer. So `_get_model()` now attaches a tokenizer-providing `WhisperProcessor` from the model's **base OpenAI repo** (which *do* ship the processor) whenever the loaded model has none:

```python
_PROCESSOR_BASE = {
    "mlx-community/whisper-large-v3-turbo":    "openai/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-turbo-q4": "openai/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-mlx":      "openai/whisper-large-v3",
    "mlx-community/whisper-small-mlx":         "openai/whisper-small",
    "mlx-community/whisper-base-mlx":          "openai/whisper-base",
    "mlx-community/whisper-tiny":              "openai/whisper-tiny",
}
# in _get_model, after load_model:
if getattr(model, "_processor", None) is None:
    model._processor = WhisperProcessor.from_pretrained(_PROCESSOR_BASE[repo])
```

The processor is ~2 MB of JSON/vocab (not model weights), fetched once and cached in `HF_HOME`. This makes **every** Whisper model work — including the 0.5 GB q4 you already downloaded. **You do not need to download the 1.6 GB version.**

All six OpenAI base repos were confirmed to ship the processor before wiring this.

### Notes

- PATCH bump (1.4.2 → 1.4.3) — backend fix in `transcription.py`. No new deps. **Stop → Start** the server (the new model-load path is read at import).
- First transcription with each model does a one-time ~2 MB processor fetch (needs network); cached thereafter. If the modal is offline on first run, you get a clean error explaining the fetch is needed — not a cryptic "Processor not found."
- The `whisper-large-v3-turbo-q4` is still the right pick for your 8 GB M1 — this fix unblocks it.

### Changed — Subtitles tab moved next to Generate + Whisper models surfaced in Models tab

Two bits of feedback after v1.4.1:

1. **"I couldn't find the Whisper models in the Models tab."** Correct — the
   Whisper models live in their own registry (`WHISPER_MODELS` in
   `transcription.py`), separate from the TTS `catalog.py` that drives the Models
   grid. They were only downloadable from the Subtitles tab. Now they're surfaced
   in the Models tab too, where users expect all downloads to live.
2. **"Subtitles should be next to Generate, before Models."** Moved.

**Tab reorder:** `Generate · Subtitles · Models · Downloads · Import · Voices · API · Settings` (Subtitles was last, now second).

**Whisper models in the Models tab:** new "🎬 Subtitle models (Whisper · speech-to-text)" section at the top of the Models page, above the TTS family grid. It's a separate card block (not mixed into the TTS family filter system — they're STT, not TTS) showing each Whisper model's label, repo, size, note, cache state (`✓ ready` / `not downloaded`), and a one-click orange Download button for uncached ones. Driven by the same `/api/transcribe/availability` data as the Subtitles tab, so download state stays in sync between the two surfaces.

**Loaded at startup:** `refreshTranscribe()` now runs in `init()` (after catalog + voices), so the Models-tab Whisper section is populated no matter which tab you open first — not just after visiting Subtitles.

**Minor:** `downloadWhisperModel()` now sets `stt.model = repo` so the per-card "Downloading…" label tracks the right card, and the Subtitles-tab dropdown auto-selects whatever you just downloaded.

### Notes

- PATCH bump (1.4.1 → 1.4.2) — UI placement + discoverability. No backend change, no new deps. `Update` → reload (the v1.3.6 cache-busting picks up the new assets automatically).
- **Reminder:** the STT API routes (`/api/transcribe*`) shipped in v1.4.0 require a server **Stop → Start** to be live. If `/api/transcribe/availability` 404s, the Models-tab Whisper section + Subtitles tab will be empty until you restart the Voice Studio server.
- Whisper still downloads through the existing generic `/api/downloads` — the Models-tab button and the Subtitles-tab button both hit it. Nothing new on the backend.

---

## [1.4.1] — 2026-05-27

### Added — Subtitles UI tab (transcribe tester + Whisper model download)

v1.4.0 shipped the STT/subtitle API but was API-only (the consumer is Story Studio over the network). This adds a **Subtitles** tab to the Voice Studio web UI so you can transcribe and download Whisper models directly, without curl or a second app.

**The tab (`tab==='subtitles'`):**
- **Whisper model picker** — dropdown of all 6 registry models with size, cache state (`✓ ready` / `— not downloaded`), and the recommended marker. Shows the model's note below.
- **One-click download** — if the selected model isn't cached, an orange Download button POSTs to the existing `/api/downloads` and then polls `/api/transcribe/availability` every 4s until it flips to cached (re-enabling Transcribe automatically). Progress also shows in the Downloads tab.
- **Drag-drop / click-to-pick audio** — reuses the existing `.voice-dropzone` styling. Accepts WAV/MP3/M4A/FLAC/OGG.
- **Options** — optional language code (blank = auto-detect) + word-level-timestamps checkbox.
- **Result panel** — Text / SRT / VTT view toggle, with Copy and (for SRT/VTT) a Download button that builds a blob from the current view. Header shows detected language, duration, line count, and elapsed transcription time.

**Wiring (`app.js`):**
- New `stt` state object + `sttSelectedModel` getter.
- Handlers: `refreshTranscribe`, `downloadWhisperModel` (with cache-state polling), `onSubtitlePick` / `onSubtitleDrop` / `_setSubtitleFile`, `runTranscribe` (multipart POST with a live elapsed counter), `subtitleBlobUrl` (for the download link).
- `subtitles` added to the hash-route whitelist (`#subtitles` deep-links + auto-loads availability). Also fixed: `voices` was missing from that whitelist — added it too.
- 409 ("model not downloaded") surfaces a clear "Model not downloaded yet" hint pointing at the download button.

**Nav + CSS:**
- New **Subtitles** tab button between Voices and API.
- Subtitle-specific CSS (two-column grid, format tabs, monospace output box). Reuses the existing dropzone + `download-btn` (orange) classes.

### Notes

- PATCH bump (1.4.0 → 1.4.1) — pure UI surface for the already-shipped v1.4.0 STT API. No backend change, no new deps. `Update` → Stop → Start. (Thanks to v1.3.6's `__APP_VERSION__` cache-busting, the new JS/CSS load automatically — no manual hard-refresh needed this time.)
- The API contract is unchanged — Story Studio's integration (per `docs/SUBTITLES.md`) is unaffected. This tab just gives you a local way to test transcription and pre-download Whisper models.

---

## [1.4.0] — 2026-05-27

### Added — Speech-to-text / subtitle API (Whisper)

Voice Studio now does STT, not just TTS. Story Studio (the YouTube-asset app that
already calls our TTS endpoints) needs timestamped subtitles for the narration it
generates. Rather than stand up a separate service, this adds Whisper-based
transcription to the existing server.

**Why here and not a separate app:** `mlx-audio` (already a dependency for the MLX
TTS engines) ships a complete STT subsystem — Whisper + a dozen other ASR models.
So this was wiring, not a new install. `whisper-tiny` was even already in the HF
cache. One service, one Tailscale endpoint, one thing to keep alive. And TTS audio
is pristine, so Whisper transcription of our own output is near-perfect.

Full integration guide for the consuming app: **`docs/SUBTITLES.md`**.

### New module: `app/backend/transcription.py`

- `TranscriptionManager` — lazy-loads + caches one Whisper model, transcribes
  audio → text + timestamped segments. Follows every standard from this release
  cycle:
  - **Explicit-path loading (v1.3.5):** passes the local snapshot `Path` to
    `mlx_audio.stt.load_model`, never a repo ID — immune to cache-layout drift.
  - **Shared `_GEN_LOCK` (from generation.py):** STT and TTS serialize on one GPU
    lock so two MLX models can't both spike Metal memory → OOM.
  - **MLX cache release (v1.2.7):** frees buffers on model switch + after each job.
  - **No silent downloads:** if the requested model isn't cached, raises cleanly
    (surfaced as HTTP 409) instead of pulling 1.6 GB mid-request.
- `WHISPER_MODELS` registry — 6 verified mlx-community repos (turbo /
  turbo-q4 / large-v3 / small / base / tiny), all confirmed live with real sizes.
- `segments_to_srt()` / `segments_to_vtt()` — hand-written formatters, full control
  over the cue format. Returns ready-to-write SRT + VTT strings.

### New endpoints (in `main.py`)

- **`GET /api/transcribe/availability`** — STT readiness + per-model cache state +
  the recommended default. Mirrors `/api/generate/availability`.
- **`POST /api/transcribe`** (multipart) — supply audio via either a `file` upload
  (universal) **or** a `job_id` (transcribe a previous TTS output with no
  re-upload — efficient same-machine path). Optional `model`, `language`,
  `word_timestamps`. Returns `{ text, language, duration, model, segments, srt,
  vtt }`. Clean error codes: 404 (job/file missing), 400 (bad params), 409 (model
  not downloaded — caller should download + retry).

### Downloading Whisper models

Reuses the **existing generic** `POST /api/downloads {repo}` — no new download
path. `mlx-community/whisper-large-v3-turbo` (~1.6 GB) is the recommended first
download; `...-turbo-q4` (~0.5 GB) for 8 GB Macs. The availability endpoint reports
which are cached.

### Notes

- MINOR bump (1.3.6 → 1.4.0) — new capability (STT) + new endpoints. **No new
  Python deps** — `mlx-audio` already provides the STT stack, so a plain `Update`
  → Stop → Start is enough (no need to re-run Install Generation, though it's
  harmless if you do).
- **What we did NOT use:** `whisperx` — it pins heavy torch/pyannote deps, the same
  trap that made us skip Coqui XTTS. Plain mlx-audio Whisper is clean + native.
- **Upgrade path noted:** `mlx-audio` also ships `qwen3_forced_aligner`, which
  aligns *known text* to audio for perfect word timestamps — relevant because
  Story Studio already has the script text. Not wired yet; flagged for later.
- No UI tab yet — this release is API-first since the consumer is Story Studio over
  the network. A "Subtitles" tab (drag-drop tester + click-to-download Whisper
  models) is an easy follow-up if wanted.

---

## [1.3.6] — 2026-05-27

### Fixed — Voice library Edit button + orange Download button invisible due to stale browser cache

User restarted the server after v1.3.3 (which added the ✏️ Edit button and the orange Download button), but the Edit button "doesn't work." Server logs were clean. The actual cause:

The HTML `<script>` and `<link>` tags had **manually-set cache-bust query strings** (`?v=phase2-repo-persist-1`, `?v=phase2-logo-1`) that **hadn't been bumped since v1.1.8**. Pinokio's embedded webview (and any modern browser) caches assets based on URL — so with the URL unchanged across 5 patch releases, the browser kept serving the cached v1.1.8 `app.js` that has no `openVoiceEditor` function. The `✏️` button rendered but its `@click="openVoiceEditor(v)"` resolved to `undefined` and silently did nothing.

The `NoCacheStaticMiddleware` (which sets `Cache-Control: no-store, no-cache, must-revalidate`) is in place but Pinokio's WKWebView ignores it. Cache-busting query strings are the bulletproof signal.

### Fixed (proper structural fix, not just a one-off bump)

Rather than manually bumping the cache-bust strings every release and hoping I don't forget next time, the `/` route now reads `index.html` and **substitutes `__APP_VERSION__` tokens with the current `APP_VERSION`** at request time:

```python
@app.get("/", response_class=Response)
def index() -> Response:
    html = (FRONTEND_DIR / "index.html").read_text()
    html = html.replace("__APP_VERSION__", APP_VERSION)
    return Response(content=html, media_type="text/html")
```

And the HTML now uses sentinel tokens:

```html
<link rel="stylesheet" href="/assets/style.css?v=__APP_VERSION__" />
<script defer src="/assets/prompts.js?v=__APP_VERSION__"></script>
<script defer src="/assets/app.js?v=__APP_VERSION__"></script>
<script defer src="/assets/alpine.min.js?v=__APP_VERSION__"></script>
```

Every VERSION bump now auto-busts all browser caches. Never have to remember to manually bump a cache-bust string again.

### Notes

- PATCH bump (1.3.5 → 1.3.6) — 2-line addition to `main.py`, 4-line edit to `index.html`. No new deps, no schema change. Run `Update` → Stop → Start.
- **One special instruction for this update**: after restarting, do a **hard refresh of the Voice Studio page** (⌘⇧R in most browsers, or click Pinokio's refresh button while holding ⇧). The current cached HTML still has the old `?v=phase2-...` URLs — once you hard-refresh, you get the new HTML with `?v=1.3.6` URLs, which will then auto-bust every future release.
- After v1.3.6, all of v1.3.3's UI changes (Edit button, orange Download button) become visible. v1.3.4's F5-TTS fix and v1.3.5's path-standard refactors were backend-only and were never affected.

### Lesson archived

The lesson "always bump cache-bust strings on frontend changes" is now structurally enforced — there's nothing to remember. Added to my cross-session memory notes for this project.

---

## [1.3.5] — 2026-05-27

### Codified — Worker model-loading standard (defense-in-depth across all workers)

Following the F5-TTS re-download bug (v1.3.4), establishing a project-wide standard so this class of bug doesn't recur in future workers.

**The rule:** every worker in `app/backend/generation.py` must resolve the local HF Hub snapshot path and pass it **explicitly** to the loader. Never pass a HF repo ID string when the loader will accept an absolute path.

**Why:** different upstream libraries use different cache backends. The standard `huggingface_hub` cache lives at `${HF_HOME}/hub/models--<org>--<repo>/...`, but some libraries — notably `cached_path` (used by F5-TTS) — have their own cache layout. When a worker passes a repo string and the library internally uses `cached_path`, it looks in the wrong directory and silently re-downloads. Passing an explicit absolute path bypasses the library's cache lookup entirely.

### Refactored — `_voxcpm_get_model` and `_bark_get_model`

Both workers previously passed the HF repo ID:

```python
# Before (works today via huggingface_hub, but one upstream change away from the F5-TTS bug)
voxcpm.VoxCPM.from_pretrained(repo, local_files_only=True, ...)
BarkModel.from_pretrained(repo)
```

Now they resolve the snapshot path via the existing `_mlx_audio_snapshot_path()` walker (which is generic — works for any HF Hub repo, not just mlx-audio ones) and pass it explicitly:

```python
# After
snapshot_path = self._mlx_audio_snapshot_path(repo)
voxcpm.VoxCPM.from_pretrained(str(snapshot_path), local_files_only=True, ...)
BarkModel.from_pretrained(str(snapshot_path), local_files_only=True)
AutoProcessor.from_pretrained(str(snapshot_path), local_files_only=True)
```

Both transformers' `from_pretrained` and voxcpm's `from_pretrained` accept absolute local paths interchangeably with repo IDs. The behavior is identical when the cache is healthy; the difference is **what happens when something goes wrong** — repo IDs can trigger surprise downloads, local paths can't.

### Documented — `voicestudio-mac/CLAUDE.md`

Added a new section: **"Worker Model-Loading Standard (added v1.3.5)"** that codifies the rule, explains why, shows the pattern, and lists every existing worker's compliance status:

| Worker | Pattern | Status |
|---|---|---|
| `_generate_mlx_audio` | `load_model(snapshot_path)` (Path, not str — v1.2.8) | ✅ |
| `_generate_omnivoice` | `OmniVoiceMLX.from_pretrained(str(snapshot_path))` | ✅ |
| `_generate_f5_tts` | `F5TTS(ckpt_file=…, vocab_file=…)` (v1.3.4) | ✅ |
| `_generate_voxcpm` | `voxcpm.VoxCPM.from_pretrained(str(snapshot_path), local_files_only=True)` (v1.3.5) | ✅ |
| `_generate_bark` | `BarkModel.from_pretrained(str(snapshot_path), local_files_only=True)` (v1.3.5) | ✅ |
| `_generate_kokoro` | `KPipeline(lang_code=…)` — no path API, trusts HF_HOME | 🔒 limitation |

Kokoro is the only exception — KPipeline doesn't accept a path argument, so it must trust HF_HOME via env var. Documented in the worker comment.

### Notes

- PATCH bump (1.3.4 → 1.3.5) — defensive refactor of two existing workers + documentation. No new deps, no schema change, no behavior change when cache is healthy. Run `Update` → Stop → Start.
- Workers behave identically when everything is in order; the change matters when an upstream library updates and starts using a different cache backend. We're now insulated from that.
- New workers in the future MUST follow this pattern — see `CLAUDE.md` for the boilerplate. Adding a `🔒 limitation` row to the table is fine if the loader genuinely doesn't take a path; silently passing a repo ID is not.

---

## [1.3.4] — 2026-05-27

### Fixed — F5-TTS re-downloading the 1.35 GB checkpoint even when already cached

User noticed the terminal log showed F5-TTS downloading `F5TTS_v1_Base/model_1250000.safetensors` (1.35 GB) after the v1.3.3 generate attempt — even though `SWivid/F5-TTS` was already in the HF cache via the Models-tab download. Two cache copies ended up on disk, wasting ~1.3 GB.

### Root cause

F5-TTS's `F5TTS.__init__` uses **`cached_path`** (a separate library from `huggingface_hub`) to fetch its main checkpoint:

```python
# f5_tts/api.py:80
cached_path(f"hf://SWivid/{repo_name}/{model}/model_{ckpt_step}.{ckpt_type}", cache_dir=hf_cache_dir)
```

`cached_path` has **its own cache layout** that's incompatible with the standard HF Hub format:

| Cache type | Layout |
|---|---|
| Standard HF Hub (what `snapshot_download` uses) | `{HF_HOME}/`**`hub/`**`models--<org>--<repo>/snapshots/<hash>/...` |
| `cached_path` (what F5-TTS uses) | `{cache_dir}/models--<org>--<repo>/snapshots/<hash>/...` (no `hub/` segment) |

So when v1.3.0 passed `hf_cache_dir={HF_HOME}` to `F5TTS()`, `cached_path` looked for `{HF_HOME}/models--SWivid--F5-TTS/...` (no `hub/`), didn't find it, downloaded fresh. The existing files at `{HF_HOME}/hub/models--SWivid--F5-TTS/...` were invisible to `cached_path` because of the layout mismatch.

This wasn't a regression — F5-TTS has always had this behavior. v1.3.0 just didn't account for it.

### Fix

In `_f5_tts_get_model()`, locate the checkpoint + vocab files in our standard HF Hub cache (via the existing `_mlx_audio_snapshot_path()` walker) and pass them **explicitly** to F5TTS via `ckpt_file=` and `vocab_file=`. F5TTS skips `cached_path` entirely when these are non-empty:

```python
snapshot_path = self._mlx_audio_snapshot_path(repo)
ckpt_file = snapshot_path / "F5TTS_v1_Base" / "model_1250000.safetensors"
vocab_file = snapshot_path / "F5TTS_v1_Base" / "vocab.txt"
# ... validate they exist, raise clean RuntimeError if not ...
F5TTS(model="F5TTS_v1_Base", ckpt_file=str(ckpt_file), vocab_file=str(vocab_file), ...)
```

The VoCoS vocoder (~50 MB) still auto-downloads on first load via `hf_hub_download`, which **does** respect `HF_HOME` correctly — small enough to leave alone.

### Cleanup task for users

If you generated with F5-TTS on v1.3.0 / v1.3.1 / v1.3.2 / v1.3.3, your cache likely has **two copies of the checkpoint**:

```
cache/HF_HOME/hub/models--SWivid--F5-TTS/     ← original (1.3 GB), keep this
cache/HF_HOME/models--SWivid--F5-TTS/         ← duplicate (1.3 GB), safe to delete
```

After updating to v1.3.4, you can reclaim ~1.3 GB with:

```bash
rm -rf cache/HF_HOME/models--SWivid--F5-TTS/
```

(Note: NO `hub/` in that path — that's the duplicate from `cached_path`.) The original at `cache/HF_HOME/hub/...` is what v1.3.4 uses.

### Notes

- PATCH bump (1.3.3 → 1.3.4) — one function rewrite in `generation.py`. No new deps, no schema change. Run `Update` → Stop → Start.
- Verified the fix doesn't break first-time-install flow: if the user runs `F5-TTS` without having downloaded `SWivid/F5-TTS` first, the explicit path check raises a clean `RuntimeError("F5-TTS checkpoint missing at ... — Re-download SWivid/F5-TTS from the Models tab")` instead of silently triggering a 1.35 GB out-of-band download. Forcing the through-the-Models-tab flow makes downloads visible, resumable, and cancellable.

---

## [1.3.3] — 2026-05-27

### Added — Voice library edit + orange Download button

User feedback after F5-TTS landed:

1. **No way to retrofit a transcript onto an existing voice.** F5-TTS requires a transcript per reference clip. Voices uploaded before v1.3.0 typically don't have one — and the only fix was deleting and re-uploading. Now there's an Edit button.
2. **The Download button on each voice card was unreadable on dark mode.** It used `btn ghost small` styling — basically transparent. Now it's a real orange button.

### Added — `PATCH /api/voices/{voice_id}` endpoint

- New `VoiceLibrary.update()` method in `voices.py` (alongside the existing `add()` / `delete()` / `get()`). Accepts any subset of: `name`, `language`, `gender`, `license`, `notes`, `source_url`, `transcript`. Fields not in the request are left unchanged; empty string clears clearable fields (notes / source_url / transcript).
- `update_voice()` route in `main.py` with an `UpdateVoiceBody` pydantic model. Returns 400 on validation errors (bad license/gender enum, name too long, etc.) and 404 if the voice_id doesn't exist.
- Audio file is **never** touched. Only `metadata.json` + `transcript.txt` on disk get rewritten. Voice ID, audio_extension, duration_seconds, sample_rate, channels, created_at, and permission_acknowledged all stay frozen — by design.

### Added — Edit UI on each voice card

- New ✏️ button next to the existing ✕ delete button in the card header.
- Click opens a modal pre-populated with the voice's current metadata (name, language, gender, license, notes, transcript).
- Transcript field is the big win — the modal fetches the current transcript via `GET /api/voices/{id}` on open so users can edit instead of retype.
- Save calls `PATCH /api/voices/{voice_id}`, replaces the local entry with the server response, and toasts confirmation.

### Changed — Voice card "Download" button is now orange

- Was: `<a class="btn ghost small" ...>⬇ Download</a>` — basically invisible on dark mode.
- Now: `<a class="btn download-btn" ...>⬇ Download WAV</a>` with dedicated CSS using `--warn` (`#f3b562` orange) as the background. Dark text on bright background for ≥AA contrast. Real button affordance.

### Notes

- PATCH bump (1.3.2 → 1.3.3) — backend addition + frontend addition, no schema breakage, no new deps. Run `Update` → Stop → Start (server restart picks up the new PATCH route).
- The Edit modal intentionally doesn't let you change the audio file. Audio changes mean a new reference clip with different waveform characteristics — should be a new library entry, not an in-place update. If a clip is bad, delete + re-add.
- The transcript file lives at `cache/voices/<voice_id>/transcript.txt` (separate from `metadata.json`). Editing to an empty string deletes the file and sets `has_transcript=false`; engines that require a transcript (F5-TTS) will then reject the voice.

---

## [1.3.2] — 2026-05-27

### Fixed — Diagnostics page falsely reporting F5-TTS as `Missing: f5_tts vocos`

User ran Install Generation after the v1.3.0 update, the install completed successfully (`f5-tts==1.1.20`, `vocos==0.1.0`, `cached-path==1.8.10`, etc. all installed per the pip log), but the Generate-tab diagnostics page still showed:

> ⛔ **f5-tts** · Missing: `f5_tts vocos` · Requires: `f5_tts torch vocos soundfile`

while every other engine was Ready.

**Root cause:** the diagnostics endpoint has two separate data structures:

1. `_PACKAGE_CHECKLIST` — the list of packages to actually probe with `_probe_package` (i.e. try importing).
2. `_ENGINE_REQUIREMENTS` — what packages each engine needs.

The "missing" check (`generation.py:506`) does `if not pkg_status.get(p)` — a package not in the **checklist** returns `None` from `pkg_status.get()`, which is falsy → falsely flagged as missing. When I added F5-TTS in v1.3.0, I added `f5_tts` and `vocos` to `_ENGINE_REQUIREMENTS["f5-tts"]` but **forgot to add them to `_PACKAGE_CHECKLIST`**. The diagnostics never actually probed them, just defaulted them to "missing."

Same bug for **3 other engines that were entirely invisible** in the diagnostics table: `kittentts`, `vibevoice`, `omnivoice`. They work fine (anyone can use them via the model picker), but they had no entry in `_ENGINE_REQUIREMENTS` at all, so the engine-readiness table just didn't include them. v1.2.0 (omnivoice) and v1.2.1 (kittentts + vibevoice) added the families and dispatch but skipped the diagnostics-side bookkeeping.

### Changes (both in `app/backend/generation.py`)

**`_PACKAGE_CHECKLIST`** — added 3 entries so the probe actually runs against them:

```python
("f5_tts",    "F5-TTS flow-matching TTS engine"),
("vocos",     "VoCoS vocoder used by F5-TTS"),
("omnivoice", "OmniVoice diffusion-LM TTS (ailuntx/OmniVoice-MLX)"),
```

**`_ENGINE_REQUIREMENTS`** — added 3 rows:

```python
"kittentts":  ["mlx", "mlx_audio", "soundfile", "numpy"],
"vibevoice":  ["mlx", "mlx_audio", "soundfile", "numpy"],
"omnivoice":  ["omnivoice", "torch", "transformers", "soundfile", "numpy"],
```

### Verification

Running `diagnostics()` inside the conda env now reports:

```
engines: 13, ready: 13/13
  kokoro             ✅ READY
  voxcpm             ✅ READY
  voxcpm-mlx         ✅ READY
  bark               ✅ READY
  qwen3-tts          ✅ READY
  kokoro-mlx         ✅ READY
  chatterbox-mlx     ✅ READY
  spark-tts-mlx      ✅ READY
  orpheus            ✅ READY
  kittentts          ✅ READY
  vibevoice          ✅ READY
  omnivoice          ✅ READY
  f5-tts             ✅ READY
```

**All 13 engines fully ready.** Was 10 visible engines, 9 ready in the user's screenshot before the fix.

### Notes

- PATCH bump (1.3.1 → 1.3.2) — pure bookkeeping fix in `generation.py`. No catalog change, no schema change, no new deps. `Update` → Stop → Start (server restart needed to reload `_PACKAGE_CHECKLIST` and `_ENGINE_REQUIREMENTS` at module load).
- F5-TTS was actually working all along since v1.3.0 + the user's Install Generation succeeded — only the diagnostics view was lying. Same for omnivoice / kittentts / vibevoice: they just weren't being reported.
- A nicer long-term fix would be auto-deriving `_PACKAGE_CHECKLIST` from `_ENGINE_REQUIREMENTS.values()` (union of all packages mentioned). Would have prevented this bug in the first place. Not done in this patch — out of scope, but flagged.

---

## [1.3.1] — 2026-05-26

### Removed — Dead `chatterbox`, `spark-tts`, `xtts` family stubs

The catalog had 3 families that have never had a working worker — they always raised `NotImplementedError` when picked. Cleaning them out so the catalog reflects only what actually works.

**Dropped families + their single ModelEntry each:**

- `chatterbox` (`ResembleAI/chatterbox`) — PyTorch original of Chatterbox. Fully covered by the `chatterbox-mlx` family (7 entries: chatterbox-mlx-4bit / -8bit, chatterbox-4bit / -8bit / -fp16, chatterbox-turbo-4bit / -8bit). On Apple Silicon the MLX variants are smaller, faster, same MIT license, and offer the exact same voice-cloning + exaggeration knob. No reason to keep the PyTorch stub around.
- `spark-tts` (`SparkAudio/Spark-TTS-0.5B`) — PyTorch original of Spark-TTS. Fully covered by the `spark-tts-mlx` family (4 entries: 4-6bit, 6bit, 8bit, bf16). Same reasoning as Chatterbox.
- `xtts` (`coqui/XTTS-v2`) — Coqui multilingual voice cloning. **The license isn't the deciding factor** (F5-TTS is also CPML / non-commercial and we just wired it in v1.3.0). The deciding factor is the `TTS` pip package: it **pins old torch versions** that would break the existing voxcpm / qwen3 / etc. stack. Re-adding it would mean a separate venv, vendored inference code, or both. Not worth the maintenance for a single non-commercial family when VoxCPM2 covers most of the same multilingual ground.

### Code cleanup

- Removed 3 `Family(...)` entries from `FAMILIES` dict in `catalog.py`.
- Removed 3 `ModelEntry(...)` rows from `CATALOG` tuple.
- Removed the `elif family in ("chatterbox", "spark-tts"):` and `elif family == "xtts":` branches from `_dispatch_txt2speech` in `generation.py`.
- Removed dead entries from `_ENGINE_REQUIREMENTS` dict (the `chatterbox` / `spark-tts` / `xtts` requirements were used to display "needs these packages" UI hints — useless for families that don't exist).
- Updated the module-level docstring to reflect the new wired list (13 families) + an explicit "Removed in v1.3.1" section so future devs don't accidentally re-add them.

### Audit

`audit_truth.py`: **NO DRIFT.** 13 families, **13 wired**, **0 unwired**. First time the catalog is 100% wired since the project started.

### Notes

- PATCH bump (1.3.0 → 1.3.1) — pure catalog cleanup. No functionality lost since these stubs never worked. No new deps, no schema change. Run `Update` from the Pinokio sidebar, then Stop → Start.
- If anyone had localStorage prefs (per-model presets from v1.1.8) pointing at the removed repos, those entries become orphaned but harmless — the frontend's `_initGenPersistence()` validates the stored `lastRepo` against the live catalog before restoring, and unknown repos just fall back to the default-selected model.
- The HF cache (if you ever downloaded `ResembleAI/chatterbox`, `SparkAudio/Spark-TTS-0.5B`, or `coqui/XTTS-v2`) is left on disk. Catalog removal doesn't delete files. You can manually purge them from `cache/HF_HOME/hub/` to reclaim disk space — they'd be wasted otherwise.

---

## [1.3.0] — 2026-05-26

### Added — F5-TTS family wired (Phase 2.2)

User reported all unwired engines they had downloaded — turned out F5-TTS was the only one they actually had cached (`SWivid/F5-TTS`). The other three unwired families (`chatterbox` PyTorch, `spark-tts` PyTorch, `xtts`) had no downloads and are covered by either their MLX siblings (chatterbox-mlx, spark-tts-mlx) or have license restrictions (XTTS). So this release focuses on F5-TTS only.

**What's new:**
- `_have_f5_tts()` import probe (`generation.py:198`) — checks for `f5_tts.api.F5TTS`.
- `_f5_tts_get_model()` — lazy-load + cache an `F5TTS` instance per repo with proper eviction on switch. F5-TTS auto-resolves checkpoint files from `HF_HOME`, so no manual path wiring needed — the user's pre-downloaded `SWivid/F5-TTS` snapshot just works.
- `_generate_f5_tts()` — full voice-cloning worker. Maps existing UI controls onto F5-TTS knobs (`inference_timesteps → nfe_step`, `cfg_value → cfg_strength`, `speed → speed`). Reuses the same voice-library + transcript loading pattern as other clone-capable engines.
- Dispatch in `_dispatch_txt2speech` (`generation.py:780`) replaces the prior `NotImplementedError`.
- `_WIRED_FAMILIES` now includes `f5-tts` — audit_truth.py: **NO DRIFT**, 16 families, 13 wired, 0 commission/omission lies.
- `/api/generate/availability` now reports `f5_tts_available`.

**Frontend:**
- `isF5TTS(repo)` helper in `app.js`.
- F5-TTS folded into `passesLibraryVoice` so the submit payload includes `voice_library_id` + `ref_transcript`.
- `canSubmit` gates the Generate button when F5-TTS is selected without a library voice (engine has no zero-shot mode).
- Dedicated UI block in `index.html` between the chatterbox-mlx/spark-mlx clone section and the spark style hint: voice picker + transcript override field. Voice options show `✓ transcript` / `⚠ no transcript` per entry so users know whether F5-TTS will accept it.
- Speed slider folded in.
- Catalog entry's `use_cases` updated to remove the "worker not yet wired" line and add: "Auto-chunks long text at ~135 chars + 0.15s crossfade — no manual splitting needed."

### New dependency

`requirements-generation.txt` adds:

```
f5-tts>=1.1.0
```

This transitively pulls in `vocos`, `cached_path`, `torchdiffeq`, `x_transformers`, `ema_pytorch`, `librosa`, `pydub`, and a handful of other deps. Most are small. `f5-tts` itself is actively maintained and modern-torch-compatible — no version pin conflicts expected with the existing torch 2.12 + transformers 5.9 + diffusers 0.37 stack.

### How to use

1. **Update from sidebar** → **Stop → Install Generation** (picks up `f5-tts` + transitive deps) → **Start**.
2. The cached `SWivid/F5-TTS` snapshot (already on disk) is auto-found via `HF_HOME` — no re-download needed.
3. In the Generate tab, pick `F5-TTS v1 Base` from the model dropdown.
4. **Mandatory**: pick a voice from the Voices library. F5-TTS has no zero-shot mode — it MUST have a reference clip.
5. **Mandatory**: that voice must have a transcript (either stored in the library OR provided as override in the Reference transcript field). Generation will fail with a clear error if both are missing.
6. Hit Generate. Long text auto-chunks internally at ~135 chars with 0.15s crossfade.

### Coverage update

Catalog: 16 families. Wired: 13 (added f5-tts). Still-unwired NotImplementedError stubs: 3 (`chatterbox` PyTorch, `spark-tts` PyTorch, `xtts`). For the first two, MLX siblings (`chatterbox-mlx`, `spark-tts-mlx`) cover the use case at higher quality-per-byte. XTTS is intentionally not wired — Coqui's `TTS` package pins old torch versions and would break voxcpm/qwen3/etc.

### Notes

- MINOR bump (1.2.8 → 1.3.0) — new engine family + new Python dep, per `README.md` versioning rules. Requires re-running Install Generation.
- F5-TTS `text_guidance.soft_max_chars` stays `null` (unlimited) — engine auto-chunks transparently per the v1.2.4 audit. No change to chip text or UI hint.
- If `Install Generation` fails on `f5-tts` install, log the pip error and we'll add a constraint or git+ install. Most likely cause would be a transitive dep (e.g. `gradio>=6.0.0` if a newer gradio breaks something), but our env doesn't use gradio so it should install side-by-side without issues.

---

## [1.2.8] — 2026-05-26

### Fixed — Spark-TTS dispatch (`ValueError: Model type qwen2 not supported for tts`)

User downloaded `mlx-community/Spark-TTS-0.5B-6bit`, tried to generate, got:

```
ValueError: Model type qwen2 not supported for tts.
ModuleNotFoundError: No module named 'mlx_audio.tts.models.qwen2'
```

Bug was in **our** `_mlx_audio_get_model()`. It called `load_model(str(snapshot_path))` — stringified the Path. mlx-audio's `get_model_name_parts()` behaves differently for `str` vs `Path`:

- **`Path`**: walks `.parts`, finds the `models--mlx-community--Spark-TTS-0.5B-6bit` segment, parses → `["spark", "tts", "0.5b", "6bit", ...]`. Dispatch sees `"spark"` in available models → routes to `mlx_audio.tts.models.spark`. ✅
- **`str`**: just lowercases and takes the last `/` segment. For our cache layout, that's the snapshot hash → `["be15d8bf101a4a400c568b387fb69dce0d37239b"]`. Dispatch falls back to `config.json`'s `model_type`. ❌

Spark-TTS uniquely depends on the name-parts fallback because its `config.json` reports `model_type: "qwen2"` (just the LM backbone — Spark wraps Qwen2.5-0.5B). All other mlx-audio families work because their `config.json` reports a recognized model_type directly (e.g. `voxcpm2`, `qwen3_tts`, `kokoro`).

Fix: **drop the `str()` wrapper** — pass `snapshot_path` directly. One-line change in `generation.py:952`, plus an explanatory comment so this doesn't regress.

Verified empirically by reproducing mlx-audio's `get_model_name_parts()` against the actual cached snapshot path — Path form returns `["spark", "tts", "0.5b", "05b", "6bit", "spark_tts", ...]` and dispatch correctly resolves `model_type="spark"`.

### Affects

All 4 mlx-community Spark-TTS variants in our catalog were broken by this:

- `mlx-community/Spark-TTS-0.5B-4-6bit`
- `mlx-community/Spark-TTS-0.5B-6bit`
- `mlx-community/Spark-TTS-0.5B-8bit`
- `mlx-community/Spark-TTS-0.5B-bf16`

After v1.2.8 + restart, all should dispatch correctly. No re-download needed — the cached snapshots are fine; only the loader was wrong.

### Notes

- PATCH bump (1.2.7 → 1.2.8) — one-line `generation.py` fix + 9-line explanatory comment. No schema, no new deps. Run `Update` → Stop → Start.
- The `str()` wrapper has been there since the initial commit. It went undetected because every other mlx-audio family happens to have a recognized `model_type` in its `config.json`, so the name-parts fallback was never the deciding factor. Spark-TTS is the only one in our catalog that needed it.

---

## [1.2.7] — 2026-05-26

### Fixed — MLX cache leak between sequential mlx-audio jobs (real root cause of the OOM)

Story studio's follow-up test exposed the actual root cause behind the v1.2.6 OOM, not just a "the cap was too high" symptom:

**The data point that broke v1.2.6's assumption:**
- Story studio submitted two sequential requests, both UNDER the v1.2.6 cap of 1500 chars:
  - Job `2181b6a957f1` — 1330 chars → ✅ Done (the 1 WAV the user got)
  - Job `ee3ec2687a51` — 1450 chars → 💀 **Metal OOM mid-gen** (`alloc 11.89 GB > 9.5 GB cap`)
- Same machine, same engine, same precision. The cap should have protected both. It didn't, because the cap isn't what's actually constraining things.

**Root cause: MLX has its own allocation cache that survives across `generate_audio()` calls.** Each sequential VoxCPM2-mlx voice-cloning call stacks fresh activation tensors on top of the previous call's residue. Job 1 leaves ~7 GB of buffers cached; job 2 adds ~5 GB of its own; total exceeds the M4's 9.5 GB per-Metal-buffer cap → process aborts.

**`_release_device_memory()` already existed but didn't help here** — it only cleared PyTorch's MPS cache (`torch.mps.empty_cache()`). MLX's cache is a separate allocator and was never being cleared. And it was only called on *repo switch* (in `_mlx_audio_get_model` when loading a different model), not between successive calls to the same repo.

**The fix (two parts):**

1. **`_release_device_memory()` now also clears MLX's cache.** Best-effort import of `mlx.core` and call `mx.metal.clear_cache()` (or `mx.clear_cache()` for older MLX versions). Silently no-ops if MLX isn't installed. ~10 LOC at `generation.py:514`.

2. **`_generate_mlx_audio()` calls `_release_device_memory("mps")` in its `finally` block** so memory is released after every job, not just on repo switch. The cached `self._mlx_audio_model` stays loaded (model weights aren't the OOM trigger; activation buffers are). Only the per-generation buffers get freed. ~3 LOC at `generation.py:1024`.

### Changed — `voxcpm` + `voxcpm-mlx` soft cap 1500 → 800 (quality cliff, not just memory)

User listened to the 1330-char output that DID succeed and reported the voice **becomes jibberish past ~30 sec of generated audio**. So the practical per-call ceiling isn't the Metal cap — it's voice consistency. ~30 sec audio @ ~13 chars/sec speech ≈ ~400 chars; soft cap set to 800 (~60 sec) as a reasonable upper bound (slight quality degradation but still usable for most content). Users who care about consistency should target ~400-500 chars per chunk.

Updated notes accordingly:

> **Best at ~800 chars (~60 sec audio) per call. Past ~30 sec, voice tends to drift / become jibberish — split into multiple shorter requests.**

Source comments in catalog.py distinguish **engine ceiling** (4096 tokens / 11 min audio per OpenBMB), **hardware ceiling** (Metal per-buffer cap on M4 16 GB), and **quality ceiling** (~30 sec audio empirical from user testing) so future audits don't conflate these three.

### What's still NOT fixed

API callers can still bypass the soft cap (story studio's chunking ignores chip text — it just hits `/api/generate/txt2speech` with whatever it has). The proper structural fix is still the **runtime memory gate**: a per-family `estimate_memory_bytes(input_chars)` that raises `RuntimeError` BEFORE `generate_audio()` even attempts the alloc, so one bad request fails its own job instead of crashing the server. Still flagged as P1 TODO.

The v1.2.7 cache-clearing makes that gate less urgent — sequential calls now start clean. Combined with the lower cap, story studio's chunked workflow should now work end-to-end without crashing. If you hit another OOM, paste the new log line — the math (alloc-bytes-requested vs Metal-cap) will tell us what number to use for the runtime gate.

### Notes

- PATCH bump (1.2.6 → 1.2.7) — adds 2 small code blocks to `generation.py` + catalog cap drop. No new deps, no schema. Run `Update` from the Pinokio sidebar, then Stop → Start (server restart is required to load the new `_release_device_memory` + finally block).
- Other mlx-audio families (kokoro-mlx, chatterbox-mlx, spark-tts-mlx, qwen3-tts, orpheus, kittentts, vibevoice) ALL benefit from the cache-clear since they share `_generate_mlx_audio` — they just weren't triggering the OOM because their activation footprints are smaller. The fix is universal across the family.

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
