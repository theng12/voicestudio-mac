# LongCat and Offline Fleet SSD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LongCat as a qualified internal Voice Studio candidate and make the TerraNash SSD an idempotent source for models, saved voices, and legacy-folder-safe installation.

**Architecture:** LongCat is another declarative family on Voice Studio's existing MLX worker. Studio Hub's existing SSD tools remain the single installation/copy path and gain identity-aware skip/conflict behavior rather than a new copying framework.

**Tech Stack:** Python 3.12, FastAPI catalog contracts, mlx-audio/MLX, pytest, macOS APFS/Hugging Face caches, Pinokio pterm bootstrap.

## Global Constraints

- No new runtime dependency or cloud API.
- LongCat is eligible on 16/24 GB Apple-silicon Macs only and remains non-routable until owner qualification.
- Existing `.git` and non-`.git` Studio folder names must both work without resetting a Mac.
- SSD model/voice operations are additive by default and never overwrite a voice identity conflict.
- Voice Studio release is 2.1.0; Studio Hub release is 2.7.0.

---

### Task 1: Voice Studio LongCat contract

**Files:**
- Modify: `app/backend/catalog.py`
- Modify: `app/backend/generation.py`
- Modify: `app/backend/long_form_policy.py`
- Modify: `app/frontend/app.js`
- Modify: `app/frontend/index.html`
- Test: `app/tests/test_priority_mlx_models.py`
- Test: `app/tests/test_long_form_policy.py`

**Interfaces:**
- Consumes: existing `ModelEntry`, `MLX_AUDIO_FAMILIES`, `_inject_voice_clone`, and `_generate_mlx_long_form_sections`.
- Produces: family `longcat-audiodit`, model repo `mlx-community/LongCat-AudioDiT-1B-4bit`, mode `longcat_clone`.

- [ ] Write failing tests proving the family is catalogued, MLX-wired, 16 GB minimum, clone-only, and publishes 280-character/180 ms long-form delivery.
- [ ] Run the focused tests and confirm they fail because LongCat is absent.
- [ ] Add the minimal family/model/config rows and a clone kwarg resolver using APG, CFG 4.0, 16 steps, reference audio, transcript, and seed.
- [ ] Add LongCat to the generic frontend cloning predicate without a new model-specific control panel.
- [ ] Re-run focused tests and frontend syntax checks.

### Task 2: Voice Studio candidate evidence and release

**Files:**
- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Modify: `app/frontend/index.html`
- Modify: `README.md`
- Test: existing model-audit, generation, catalog, and release suites.

**Interfaces:**
- Consumes: the Task 1 public catalog and generation contract.
- Produces: installable Voice Studio 2.1.0 with truthful internal-candidate status.

- [ ] Run an offline real-runtime smoke using the exact cached LongCat revision and one saved reference voice.
- [ ] Run sustained/multi-voice qualification evidence without marking GenStudio routable.
- [ ] Update version and release notes, explicitly stating that owner listening is still required.
- [ ] Run focused tests, full pytest, compile checks, dependency checks, launcher syntax, and `release_metadata_check.py`.
- [ ] Commit and push the Voice Studio release.

### Task 3: Studio checkout identity and duplicate prevention

**Files:**
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/tools/fleet_bootstrap.py`
- Test: `/Users/thengmacmini/pinokio/api/studiohub-mac/app/tests/test_fleet_bootstrap.py`

**Interfaces:**
- Consumes: expected Git URL and `<PINOKIO_HOME>/api`.
- Produces: one detected checkout path and its exact Pinokio app reference.

- [ ] Write failing tests for canonical-only, legacy-only, both-present, wrong-origin, and arbitrary username/home paths.
- [ ] Confirm legacy-only currently downloads a duplicate canonical checkout.
- [ ] Make checkout discovery accept `.git` suffixes and route install/start through the detected folder name.
- [ ] Keep both-present behavior non-destructive and visible.
- [ ] Run the focused bootstrap tests.

### Task 4: Additive models and stable saved voices

**Files:**
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/tools/studio_models.py`
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/tools/fleet_bootstrap.py`
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/SSD-COPY-README.md`
- Test: `/Users/thengmacmini/pinokio/api/studiohub-mac/app/tests/test_fleet_bootstrap.py`

**Interfaces:**
- Consumes: Voice Studio catalog/cache and `app/voices/<id>` fleet-managed records.
- Produces: manifest schema 2 with model packages and stable voice ID/hash entries.

- [ ] Write failing tests for skip-on-match, additive staging, offline-Studio preservation, saved-voice copy/skip/conflict, and RAM-floor restore.
- [ ] Replace destructive stage-by-default behavior with copy-or-skip and preserve previously staged packages.
- [ ] Stage all locally cached catalog models and companions without clone-family filtering.
- [ ] Stage and restore fleet-managed voices atomically by ID and audio SHA-256.
- [ ] Keep `--prune` explicit and memory-floor-based; never prune saved voices.
- [ ] Run focused tests and a temporary-directory end-to-end dry run.

### Task 5: Studio Hub release and physical SSD refresh

**Files:**
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/VERSION`
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/CHANGELOG.md`
- Modify: `/Users/thengmacmini/pinokio/api/studiohub-mac/app/frontend/index.html`
- Update: `/Volumes/ugreen-terranash/terranash-bootstrap/**`
- Update: `/Volumes/ugreen-terranash/studio-models/**`

**Interfaces:**
- Consumes: verified Studio Hub source tools and Voice Studio 2.1.0 catalog/cache.
- Produces: Studio Hub 2.7.0 plus a directly usable connected SSD.

- [ ] Update Studio Hub metadata and operator release notes.
- [ ] Run focused and full Studio Hub tests, compile checks, release checks, and diff checks.
- [ ] Commit and push Studio Hub 2.7.0.
- [ ] Run `studio_models.py stage --plan`, inspect exact additions/skips, then run the real stage.
- [ ] Validate the SSD manifest, bootstrap file hashes/modes, LongCat package, UMT5 companion, and saved voice records.
- [ ] Run the SSD model-copy flow in `--plan` mode against a temporary arbitrary-username Pinokio home and confirm a second run is a no-op.
