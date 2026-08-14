# Qwen3-TTS 1.7B GenStudio Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a truthful, hash-bound Qwen3-TTS 1.7B Base conditional canary
bootstrap in Voice Studio 2.1.2, then promote only from a distinct measured
and passed Voice Studio 2.1.3 audit after the new-runtime canary succeeds.

**Architecture:** Reuse the existing Qwen Base clone adapter, quality
guardrails, audit loader, and Studio Hub boundary. First implement the
bounded-reference, ordered-terminal-gate, and boundary-aware assembly runtime,
then publish a 2.1.2 **conditional** audit that supplies those execution facts
but is unroutable. After that exact new runtime is installed on one eligible
canary, collect remote measurement and owner evidence and create a **new**
2.1.3 hash-bound passed audit. Never turn the 2.1.2 bootstrap record into the
passed record, and do not create a second route or fallback engine inside Voice
Studio.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, mlx-audio, soundfile, pytest, JSON model-audit records.

## Global Constraints

- Runtime repository is `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` at immutable revision `e7dd0585652209fa0d7783659aad4e8a324de11c`.
- Minimum unified memory is 16 GB; 24 GB is preferred; 8 GB is ineligible.
- Qwen remains transcript-assisted reference cloning with no x-vector-only fallback.
- Join pacing is 300 ms sentence, 600 ms paragraph, and 180 ms soft split.
- Assembly retains every generated frame and performs no destructive edge trim or speech crossfade.
- OmniVoice and every other model remain installed and catalogued.
- No paid or cloud generation is permitted.

---

### Task 1: Implement the 2.1.2 Qwen runtime contract

**Files:**
- Modify: `app/tests/test_long_form_policy.py`
- Modify: `app/backend/generation.py`
- Modify: `app/backend/long_form_policy.py`
- Modify: `app/backend/reference_audio.py`
- Modify: `app/backend/qwen_quality.py`

**Interfaces:**
- Consumes: sentence-safe Qwen sections, the original request text, and either
  a private or saved reference with its exact transcript.
- Produces: bounded reference preparation/evidence, a per-boundary pause
  sequence passed to `_join_long_form_wavs`, and the additive ordered terminal
  validation required by the conditional audit.

- [ ] Add a failing behavior test using three literal boundaries and assert the rendered pause sequence is `[0.3, 0.6, 0.18]` at speed 1.0 and scales before the final tempo pass.
- [ ] Run the focused test and confirm it fails because Qwen currently emits one fixed 180 ms pause.
- [ ] Generalize the existing boundary classifier so Qwen and OmniVoice share
  the 300/600/180 policy without changing other families, preserve every
  generated frame, and use no destructive trim or speech crossfade.
- [ ] Prepare saved and private 1.7B references through the same bounded,
  exact-transcript path; add the ordered 24-word terminal gate only to the
  existing long-form branch, retaining Qwen validator v1 as the top-level
  validator.
- [ ] Run focused long-form, reference, Qwen guardrail, and artifact tests.

### Task 2: Publish and locally verify the conditional 2.1.2 bootstrap

**Files:**
- Create: `model-audits/2026-08-14-qwen3-17b/mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json`
- Modify: `app/tests/test_model_audit_contract.py`
- Modify: `app/tests/test_audit_contract_runtime.py`
- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Create: `.superpowers/sdd/2026-08-14-qwen3-17b-genstudio-candidate/bootstrap-release-report.md`

**Interfaces:**
- Consumes: Task 1 runtime policy and the bounded reference-preparation
  contract. Preliminary pre-release memory evidence is retained only as
  preliminary evidence, not qualification.
- Produces: a valid conditional `studio.model-audit` record surfaced by
  `/api/catalog` for runtime preparation, while Studio Hub keeps it blocked
  because it is not passed and `candidate_for_genstudio` is false.

- [ ] Add a failing contract test asserting the exact model/revision,
  conditional false-candidate status, adapter/runtime identity, 16/24/8 GB
  hardware policy, grounded reference profile, runtime-default section budget,
  additive terminal guard, lossless assembly, and canonical contract hash.
- [ ] Run the focused audit tests and confirm failure because no 1.7B audit exists.
- [ ] Create the conditional audit JSON with duplicated contract/candidate
  fields exactly matching the schema and compute its canonical SHA-256 using
  `model_audits.contract_hash`.
- [ ] Bump Voice Studio from 2.1.1 to 2.1.2 and describe the conditional
  bootstrap, bounded reference preparation, terminal guard, pacing, hardware,
  managed media tools, and explicitly non-routable status in the top changelog
  entry.
- [ ] Run focused tests, full pytest, `audit_truth.py --strict`, `audit_contract_runtime.py --strict`, `release_metadata_check.py`, compileall, dependency integrity, launcher syntax, and `git diff --check`.
- [ ] Write the bootstrap release report. Do not commit, push, update a canary,
  mutate services/fleet, create a handoff, or claim final qualification.

### Task 3: Measure the installed 2.1.2 runtime on exactly one canary

**Files:**
- Create: `bench-results/qwen-17b-genstudio-candidate/section-sweep.json`
- Create: `bench-results/qwen-17b-genstudio-candidate/README.md`

**Interfaces:**
- Consumes: the pinned, installed 2.1.2 runtime and its conditional audit on
  one eligible canary, through the authenticated operator/Studio Hub path.
- Produces: the remote transcript, runtime, memory, and owner-listening
  evidence that feeds the distinct 2.1.3 passed audit. Existing pre-release
  benchmark artifacts remain preserved preliminary evidence and must not be
  presented as this post-2.1.2 canary.

- [ ] Confirm the canary reports Voice Studio 2.1.2, the exact checkpoint
  revision and bootstrap hash, 16 GB-or-larger eligibility, and blocked Hub
  exposure before submitting qualification work.
- [ ] Run the same reference voice and narration at literal section ceilings
  230, 288, 350, and 400; transcribe every returned WAV with Whisper Large v3
  Turbo and retain coverage, tail, runtime, MLX, pressure, free-memory, and
  swap evidence.
- [ ] Run the selected ceiling against the whole-request candidate limit and
  require a complete atomic WAV, transcript coverage, and owner listening
  evidence. Preserve every result, including failures.

### Task 4: Publish the distinct measured/passed 2.1.3 promotion

- [ ] Run exactly one eligible 16 GB-or-larger canary on the pinned 2.1.2
  runtime only as described in Task 3; do not reuse pre-release observations as
  qualification.
- [ ] Publish a **new** hash-bound **passed** audit with
  `candidate_for_genstudio: true` only after Task 3 evidence is accepted; keep
  the 2.1.2 conditional audit as superseded bootstrap evidence.
- [ ] Release Voice Studio 2.1.3, update the canary first, obtain the separate
  GenStudio approval, then use its independent auto-canary before any broader
  rollout or handoff.
