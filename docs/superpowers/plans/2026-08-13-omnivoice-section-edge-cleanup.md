# OmniVoice Section Edge Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove clearly low-energy OmniVoice section-edge artifacts while preserving words, non-crossfaded delivery, and the existing 300/600/180 ms pacing.

**Architecture:** Add one private WAV cleanup helper beside the existing long-form joiner in `generation.py`. The helper uses an adaptive 10 ms RMS envelope, bounded 300 ms trim decisions, a 20 ms speech pad, and speed-compensated 10 ms half-cosine fades; the long-form renderer invokes it only for OmniVoice before the unchanged joiner inserts silence.

**Tech Stack:** Python 3.12, NumPy, SoundFile, pytest, existing Voice Studio model-audit JSON.

## Global Constraints

- Preserve speech whenever an edge is ambiguous; an uncertain artifact may remain.
- Never remove a fixed duration or more than 300 ms from either edge.
- Preserve 20 ms before/after a detected sustained speech boundary.
- Apply approximately 10 ms fades without overlapping adjacent sections.
- Preserve 300 ms sentence, 600 ms paragraph, and 180 ms soft joins.
- Apply the behavior only to OmniVoice; add no dependency or public API field.
- Do not restart the live Pinokio-managed Voice Studio service during development.

---

### Task 1: Specify the real WAV behavior with failing tests

**Files:**
- Modify: `app/tests/test_generation_artifact_contract.py`
- Modify: `app/tests/test_priority_mlx_models.py`

**Interfaces:**
- Consumes: existing SoundFile/NumPy WAV fixtures and `_generate_mlx_long_form_sections()`.
- Produces: behavioral requirements for `_clean_omnivoice_section_edges(path: Path, speed: float) -> tuple[float, float]`.

- [ ] **Step 1: Add a low-energy edge-artifact regression**

Create a real WAV containing a 270 ms low-energy prefix, quiet separation,
sustained speech, and a 260 ms low-energy suffix. Assert that the helper removes
only the bounded prefix/suffix, retains a 20 ms pad, and returns the removed
durations.

- [ ] **Step 2: Add word-preservation and fade regressions**

Use immediate-onset mono speech, stereo speech, and a too-short/ambiguous sample.
Assert that their frame counts are unchanged, stereo geometry survives, and the
first/last approximately 10 ms receive a half-cosine fade rather than deletion.

- [ ] **Step 3: Strengthen the long-form integration regression**

Make the generated OmniVoice sections long enough for edge processing, then
assert exact section lengths plus speed-pre-scaled 300/600/180 ms zero gaps. The
test must fail if speech is crossfaded or if cleanup changes gap duration.

- [ ] **Step 4: Run the focused tests and confirm RED**

Run:

```bash
conda_env/bin/python -m pytest -q \
  app/tests/test_generation_artifact_contract.py \
  app/tests/test_priority_mlx_models.py::test_omnivoice_long_form_join_uses_boundary_aware_speed_compensated_gaps
```

Expected: failures because `_clean_omnivoice_section_edges` does not exist and
raw OmniVoice sections still reach the joiner.

### Task 2: Implement conservative OmniVoice edge cleanup

**Files:**
- Modify: `app/backend/generation.py`
- Test: `app/tests/test_generation_artifact_contract.py`
- Test: `app/tests/test_priority_mlx_models.py`

**Interfaces:**
- Consumes: a temporary section WAV and public speed clamped to 0.5–2.0.
- Produces: `_clean_omnivoice_section_edges(path: Path, speed: float) -> tuple[float, float]`, returning leading/trailing seconds removed.

- [ ] **Step 1: Add the minimal detector and atomic rewrite**

Use 10 ms all-channel RMS frames. Derive the threshold as the larger of a
0.0015 absolute floor and 10% of the section's 90th-percentile frame RMS. A
sustained boundary requires at least six active frames in an eight-frame (80 ms)
window. Bound each removal to 300 ms, retain a 20 ms pad, and leave that edge
untrimmed when above-threshold activity before/after the sustained boundary
makes it ambiguous. Reject non-finite input. If no safe boundary exists, retain
all frames.

Rewrite through a sibling temporary WAV and `os.replace()`. Preserve sample
rate, channel count, WAV format, and subtype.

- [ ] **Step 2: Add non-crossfaded micro-fades**

Clamp speed to 0.5–2.0 and pre-scale a 10 ms fade by that speed. Apply a
half-cosine gain independently to the retained section's first and last fade
windows; never mix samples from two sections.

- [ ] **Step 3: Wire only the OmniVoice long-form path**

After a generated section passes existing terminal-silence handling, invoke the
helper only when `family == "omnivoice"`. Log non-zero leading/trailing removal
durations, append the cleaned temporary section, and leave `_join_long_form_wavs`
and every other model family unchanged.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Task 1 command. Expected: all selected tests pass.

### Task 3: Advance the exact audited contract and release metadata

**Files:**
- Modify: `model-audits/2026-08-08-omnivoice/mlx-community--OmniVoice-bfloat16.audit.json`
- Modify: `app/tests/test_model_audit_contract.py`
- Modify: `app/tests/test_audit_contract_runtime.py`
- Modify: `VERSION`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `model_audits.contract_hash()` canonical contract hashing.
- Produces: Voice Studio 2.0.5 and a new auditable OmniVoice exact candidate.

- [ ] **Step 1: Add failing contract expectations**

Require adapter version `1.3`, audit ID
`voicestudio-20260813-omnivoice-6119f707-edge-cleanup-v3`, and private limits
`private_edge_trim_window_milliseconds: 300`,
`private_edge_speech_pad_milliseconds: 20`, and
`private_edge_fade_milliseconds: 10`. Confirm the test fails against v1.2.

- [ ] **Step 2: Update and re-hash the audit record**

Apply those fields to both the top-level contract and `genstudio_candidate`,
record the measured 17–270 ms evidence and conservative fail-open policy, and
replace `contract_hash` with the value returned by
`model_audits.contract_hash(record["contract"])`.

- [ ] **Step 3: Bump the patch release**

Set `VERSION` to `2.0.5`. Add a 2026-08-13 changelog entry naming the raw-section
root cause, bounded energy trim, 10 ms fades, unchanged pacing, unchanged model
weights/runtime, no new dependency, and verification evidence.

- [ ] **Step 4: Run contract and release tests**

Run:

```bash
conda_env/bin/python -m pytest -q \
  app/tests/test_model_audit_contract.py \
  app/tests/test_audit_contract_runtime.py \
  app/tests/test_long_form_policy.py
```

Expected: all selected tests pass with the new canonical hash.

### Task 4: Verify and ship Voice Studio 2.0.5

**Files:**
- Verify all modified files.

**Interfaces:**
- Consumes: the complete repository and established release workflow.
- Produces: one pushed Voice Studio 2.0.5 release commit after the design/plan checkpoints.

- [ ] **Step 1: Run the complete repository suite**

```bash
conda_env/bin/python -m pytest -q
```

Expected: all tests pass; only the existing third-party deprecation warnings may
remain.

- [ ] **Step 2: Run release integrity checks**

```bash
conda_env/bin/python -m compileall -q app/backend app/tests
conda_env/bin/python -m pip check
node --check pinokio.js
node --check start.js
node --check update.js
git diff --check
```

Expected: every command exits zero.

- [ ] **Step 3: Review the exact release diff**

Confirm only OmniVoice edge processing, its behavioral tests, its exact audited
contract, documentation, `VERSION`, and `CHANGELOG.md` changed. Confirm no
launcher behavior, dependency, public request schema, or existing pause constant
changed.

- [ ] **Step 4: Commit and push**

Stage only the named files, commit with `fix: clean OmniVoice section edges`,
then push `main` to `origin`. Do not restart the live service; fleet rollout is
a separate operational action.

