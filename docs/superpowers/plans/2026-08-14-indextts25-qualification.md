# IndexTTS 2.5 MLX Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download and verify all three IndexTTS 2.5 MLX variants, then produce a safe 16 GB baseline and a reproducible handoff for later isolated 8 GB testing.

**Architecture:** Candidate weights stay in Voice Studio's ignored cache while the pinned upstream runtime and evidence stay in a separate qualification workspace. The experiment uses the existing Aiden reference, creates a revision-bound speaker cache, and measures the real end-to-end footprint without modifying the production Voice Studio environment.

**Tech Stack:** Hugging Face immutable snapshots, `vanch007/mlx-indextts2` MLX runtime, Python 3.12, MLX, PyTorch preprocessing, SoundFile, psutil, and Voice Studio resource telemetry conventions.

## Global Constraints

- Production Voice Studio remains live, idle, and unchanged at version `2.1.1`.
- Runtime source is pinned to `a7666367b8551656a2029ad75f259cb5e4936b3b`.
- Model revisions are the exact three hashes recorded in the design.
- Candidate assets are not added to the catalog, Hub, GenStudio, or automatic SSD staging.
- 8 GB tests use a precomputed speaker cache and never enable Qwen-derived emotion.
- Test audio and evidence are disposable; saved voices and production outputs are not touched.
- A failed machine or candidate does not block later fleet work.

---

### Task 1: Fetch and verify candidate assets

**Files:**
- Create: `cache/candidate-models/indextts2-2.5/8bit/` (ignored model data)
- Create: `cache/candidate-models/indextts2-2.5/fp16/` (ignored model data)
- Create: `cache/candidate-models/indextts2-2.5/fp32/` (ignored model data)
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/asset-verification.json`

**Interfaces:**
- Consumes: the three Hugging Face repository IDs and immutable revisions.
- Produces: complete local directories whose file names, sizes, and SHA-256
  digests match the Hugging Face LFS metadata.

- [ ] Check local disk space; require at least 20 GB free before downloading.
- [ ] Download each repository with `hf download --revision <sha> --local-dir <directory>`.
- [ ] Fetch Hugging Face `?blobs=true` metadata and compare every local file's
  byte count and SHA-256 with its published LFS object ID.
- [ ] Confirm each directory includes `LICENSE`, `model_manifest.json`,
  `conversion_report.json`, all four safetensors components, tokenizer, config,
  and feature/statistics files.
- [ ] Record the immutable verification result outside the product repository.

### Task 2: Build the isolated qualification runtime

**Files:**
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/runtime/`
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/runtime/.venv/`

**Interfaces:**
- Consumes: upstream commit `a7666367b8551656a2029ad75f259cb5e4936b3b`.
- Produces: an isolated `mlx-indextts` CLI/API environment that cannot alter
  Voice Studio's `conda_env`.

- [ ] Clone the runtime at the pinned commit.
- [ ] Run its focused 2.5 model, tokenizer, manifest, runtime, and speaker-cache
  tests before installing or loading weights.
- [ ] Create the isolated environment from the upstream lock with the `v25`
  extra only; do not install WebUI, API, Qwen, conversion, or library extras.
- [ ] Re-run focused tests and `pip check` inside the isolated environment.

### Task 3: Create the reusable Aiden speaker cache

**Files:**
- Read: `app/voices/a9aedc5c6bd3/reference.mp3`
- Read: `app/voices/a9aedc5c6bd3/transcript.txt`
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/voices/aiden-v25.npz`
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/voices/aiden-v25.json`

**Interfaces:**
- Consumes: authorized Aiden reference audio and the 8-bit model revision.
- Produces: a strict 2.5 speaker cache bound to the model revision, plus source
  audio/transcript hashes for later copy verification.

- [ ] Resolve/download only the manifest-declared W2V-BERT and CampPlus
  preprocessing assets on the 16 GB Mac.
- [ ] Generate the speaker cache with the pinned runtime and 8-bit model.
- [ ] Validate cache schema, model revision, tensor names/shapes, and source hash.
- [ ] Prove a second generation can use the `.npz` without initializing raw
  reference preprocessing.

### Task 4: Run the 16 GB baseline

**Files:**
- Read: `bench-results/sustained-16gb-candidates/source.txt`
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/outputs/`
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/results-16gb.json`

**Interfaces:**
- Consumes: verified 8-bit weights, Aiden speaker cache, and fixed texts.
- Produces: neutral, calm, expressive, and sustained WAVs with per-attempt
  resource evidence and unload recovery.

- [ ] Ensure Voice Studio is idle and unload its model cache without stopping
  the service.
- [ ] Render a short neutral sample at 16 diffusion steps.
- [ ] Render calm and expressive manual-emotion samples without Qwen emotion.
- [ ] Render the 3,033-character sustained narration using upstream safe text
  segmentation and one final joined artifact.
- [ ] Validate finite mono 22,050 Hz WAV output, clipping, duration, exact source
  coverage by local transcription, and absence of extra terminal speech.
- [ ] Record pressure, minimum available memory, swap delta, process RSS, MLX
  peak, wall/audio time, RTF, and post-unload recovery.
- [ ] Stop immediately if pressure becomes critical or the OS reports a memory
  failure; retain the terminal evidence and do not retry blindly.

### Task 5: Prepare the owner-controlled 8 GB handoff

**Files:**
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/8GB-TEST-README.md`
- Create: `/Users/thengmacmini/pinokio/qualification/indextts25-2026-08-14/8gb-test-manifest.json`

**Interfaces:**
- Consumes: verified 8-bit assets, Aiden cache, fixed prompts, and 16 GB evidence.
- Produces: exact files/checksums and staged escalation instructions for one M2
  8 GB Mac followed by one M1 8 GB Mac.

- [ ] Include only 8-bit weights, runtime revision, Aiden `.npz`, license,
  fixed prompts, and verification hashes.
- [ ] Specify sentence, 500-character, and 3,033-character stages with the exact
  rejection gates from the design.
- [ ] State that Image/Voice model caches must be released before each isolated
  run and restored only after telemetry is saved.
- [ ] Do not register or advertise IndexTTS2 as fleet supply during testing.

### Task 6: Decide whether integration work exists

**Files:**
- No product files unless the owner accepts quality, hardware, and license gates.

**Interfaces:**
- Consumes: owner listening, 16 GB evidence, and later M1/M2 8 GB evidence.
- Produces: one of `reject`, `internal-16gb`, `internal-8gb`, or a separately
  approved Voice Studio integration specification.

- [ ] Reject 8 GB eligibility on any memory, stability, integrity, or unload gate.
- [ ] Keep FP16/FP32 as comparisons only if their quality justifies their cost.
- [ ] Require explicit owner license acceptance before proposing commercial routing.
- [ ] If all gates pass, write a new integration design; do not silently turn
  qualification code into production code.
