# Internal Moonshine and Nemotron ASR Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Moonshine Base and Nemotron 3.5 ASR Streaming 0.6B 8-bit as truthful, operator-only Voice Studio transcription candidates without changing Whisper defaults, GenStudio, or the fleet.

**Architecture:** Replace the Whisper-only metadata registry with one transcription registry while keeping the existing manager, cache, global generation lock, API, and download pipeline. Dispatch inference by a three-value engine field and normalize Moonshine and Nemotron outputs into Voice Studio's existing transcript/segment/SRT/VTT response.

**Tech Stack:** Python 3.12, FastAPI, `mlx-audio==0.4.7`, Alpine.js, pytest, Hugging Face cache.

## Global Constraints

- Add exactly `moonshine-ai/moonshine-base` and `mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit`.
- Classify both as internal, experimental 8 GB candidates; do not claim completed fleet qualification.
- Keep Whisper large-v3 turbo recommended and the implicit default for `/api/transcribe` and Qwen validation.
- Use the existing MLX runtime and Hugging Face downloader; add no dependency, native service, or separate cache.
- Moonshine is short-form/transcript-first, has no word timing, and may emit one segment spanning the measured source duration.
- Nemotron supports long-form chunked inference plus segment and optional word timing.
- Do not create model-audit records or emit `genstudio_candidate` for the two pilot models.
- Do not modify Studio Hub, GenStudio, launcher scripts, dependency manifests, fleet state, caches, services, or installed models.
- Ship one Voice Studio `2.4.0` product commit after all task checkpoints are reviewed; intermediate product commits are forbidden by the repository release discipline.

---

### Task 1: General transcription registry and availability truth

**Files:**
- Modify: `app/backend/transcription.py:54-234`
- Create: `app/tests/test_transcription_model_registry.py`

**Interfaces:**
- Produces: `TranscriptionModel`, `TRANSCRIPTION_MODELS`, `WHISPER_MODELS`, `model_for_repo(repo)`, and additive availability model fields.
- Consumes: `cache.status_snapshot()`, `candidate_summary()`, and the unchanged recommended-model contract.

- [ ] **Step 1: Write registry and availability tests first**

  Add literal assertions proving:

  ```python
  def test_internal_asr_registry_preserves_whisper_default():
      assert transcription.recommended_model() == "mlx-community/whisper-large-v3-turbo"
      assert transcription.model_for_repo("moonshine-ai/moonshine-base").engine == "moonshine"
      assert transcription.model_for_repo(
          "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"
      ).engine == "nemotron"

  def test_internal_candidates_publish_truth_without_genstudio_evidence(monkeypatch):
      monkeypatch.setattr(transcription.cache, "status_snapshot", cached_snapshot)
      payload = transcription.availability()
      moonshine = by_repo(payload)["moonshine-ai/moonshine-base"]
      nemotron = by_repo(payload)["mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"]
      assert moonshine == moonshine | {
          "engine": "moonshine",
          "min_unified_memory_gb": 8,
          "internal_candidate": True,
          "supports_segment_timestamps": False,
          "supports_word_timestamps": False,
          "supports_long_form": False,
      }
      assert nemotron["supports_segment_timestamps"] is True
      assert nemotron["supports_word_timestamps"] is True
      assert nemotron["supports_long_form"] is True
      assert "genstudio_candidate" not in moonshine
      assert "genstudio_candidate" not in nemotron
  ```

  Include exact sizes `0.25` and `0.76`, language summaries `English` and
  `Multilingual`, and prove `WHISPER_MODELS` contains only engine `whisper`.

- [ ] **Step 2: Run the new tests and capture RED**

  Run:

  ```bash
  conda_env/bin/python -m pytest -q app/tests/test_transcription_model_registry.py
  ```

  Expected: collection or assertion failures because the generic registry and
  the two candidates do not exist.

- [ ] **Step 3: Implement the minimal registry**

  Replace `WhisperModel` with:

  ```python
  @dataclass(frozen=True)
  class TranscriptionModel:
      repo: str
      label: str
      size_gb: float
      note: str
      engine: str = "whisper"
      min_unified_memory_gb: int = 8
      languages: str = "Multilingual"
      supports_segment_timestamps: bool = True
      supports_word_timestamps: bool = True
      supports_long_form: bool = True
      internal_candidate: bool = False
      recommended: bool = False
  ```

  Define `TRANSCRIPTION_MODELS` as the five unchanged Whisper entries followed
  by the two exact pilot entries. Derive:

  ```python
  WHISPER_MODELS = tuple(m for m in TRANSCRIPTION_MODELS if m.engine == "whisper")
  _BY_REPO = {m.repo: m for m in TRANSCRIPTION_MODELS}

  def model_for_repo(repo: str) -> TranscriptionModel:
      return _BY_REPO[repo]
  ```

  Iterate `TRANSCRIPTION_MODELS` in `availability()` and add the capability
  fields. Preserve `candidate_summary()` behavior unchanged so only a real
  audit can add candidate evidence.

- [ ] **Step 4: Run focused registry and existing availability regressions**

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_transcription_model_registry.py \
    app/tests/test_managed_media_tools.py \
    app/tests/test_release_observability.py
  ```

  Expected: PASS.

---

### Task 2: Engine dispatch and result normalization

**Files:**
- Modify: `app/backend/transcription.py:378-640`
- Create: `app/tests/test_transcription_engines.py`
- Modify: `app/tests/test_transcription_decode_options.py`
- Modify: `app/tests/test_transcription_resource_telemetry.py`

**Interfaces:**
- Consumes: `model_for_repo(repo) -> TranscriptionModel` from Task 1.
- Produces: `_generate_for_engine(model, path, language, word_timestamps)`, `_segments_from_nemotron(result, word_timestamps)`, and the unchanged public `TranscriptionManager.transcribe()` response.

- [ ] **Step 1: Write engine-specific argument tests**

  Use a real `TranscriptionManager` with the cache/path and model loader boundary
  replaced by narrow fakes. Assert:

  ```python
  def test_whisper_alone_receives_the_approved_decode_policy():
      manager.transcribe(audio, model_repo=WHISPER_REPO)
      assert fake.generate_kwargs["condition_on_previous_text"] is False

  def test_moonshine_rejects_word_timestamps_before_inference():
      with pytest.raises(ValueError, match="does not support word timestamps"):
          manager.transcribe(audio, model_repo=MOONSHINE_REPO, word_timestamps=True)
      assert fake.generate_calls == []

  def test_nemotron_receives_language_and_bounded_chunking():
      manager.transcribe(audio, model_repo=NEMOTRON_REPO, language="en", word_timestamps=True)
      assert fake.generate_kwargs == {"language": "en", "chunk_duration": 30.0}
  ```

  Prove `_attach_processor()` runs only for the Whisper engine and that
  `loaded_model_key()` returns `(repo, "transcription-stt")` for every engine.

- [ ] **Step 2: Write output normalization tests**

  Construct literal result objects matching the installed `mlx-audio` shapes.
  Prove:

  - Moonshine text becomes exactly one segment `{start: 0.0, end: duration}`;
  - empty Moonshine text produces no segment and empty SRT/VTT;
  - Nemotron sentences preserve literal sentence start/end/text;
  - Nemotron tokens appear as words only when requested;
  - Whisper's current raw-segment normalization remains byte-for-byte stable.

- [ ] **Step 3: Run the focused tests and capture RED**

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_transcription_engines.py \
    app/tests/test_transcription_decode_options.py \
    app/tests/test_transcription_resource_telemetry.py
  ```

  Expected: failures show Whisper-only validation, processor attachment, kwargs,
  and result handling.

- [ ] **Step 4: Implement the minimum dispatch**

  Update loading to read the registry entry and attach a processor only for
  `engine == "whisper"`. In `transcribe()` validate timing support before model
  load, then dispatch:

  ```python
  if spec.engine == "whisper":
      result = model.generate(
          str(p), language=lang, word_timestamps=word_timestamps,
          return_timestamps=True,
          condition_on_previous_text=_CONDITION_ON_PREVIOUS_TEXT,
      )
  elif spec.engine == "moonshine":
      result = model.generate(str(p))
  else:
      result = model.generate(str(p), language=lang or "auto", chunk_duration=30.0)
  ```

  Normalize Moonshine from `result.text`. Normalize Nemotron from
  `result.sentences`, reading each token's `text`, `start`, and `end`. Keep the
  existing Whisper normalization path intact. Use measured media duration for
  the response and Moonshine's single full-duration segment.

- [ ] **Step 5: Run engine, quality, memory, and API regressions**

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_transcription_engines.py \
    app/tests/test_transcription_decode_options.py \
    app/tests/test_transcription_resource_telemetry.py \
    app/tests/test_qwen_quality_guardrails.py \
    app/tests/test_memory_policy.py \
    app/tests/test_api.py
  ```

  Expected: PASS with Qwen still resolving the Whisper default.

---

### Task 3: Generic transcription storage inventory

**Files:**
- Modify: `app/backend/model_storage.py:1-245`
- Modify: `app/tests/test_model_storage.py`

**Interfaces:**
- Consumes: `TRANSCRIPTION_MODELS`, `WHISPER_MODELS`, and `_PROCESSOR_BASE`.
- Produces: one `transcription-stt` storage family containing all supported ASR model packages and only the real Whisper processor dependencies.

- [ ] **Step 1: Write failing storage behavior tests**

  Assert the physical inventory groups both exact pilot repos under
  `transcription-stt`, labels the family `Transcription`, and describes it as
  local speech-to-text storage. Assert processor dependencies remain linked
  only to their Whisper parents and the two pilots gain no invented dependency.

- [ ] **Step 2: Run the storage test and capture RED**

  ```bash
  conda_env/bin/python -m pytest -q app/tests/test_model_storage.py
  ```

  Expected: failures because storage imports and groups only `WHISPER_MODELS`.

- [ ] **Step 3: Implement the generic family**

  Import `TRANSCRIPTION_MODELS`; use it for the supported model map and package
  list. Keep `_PROCESSOR_BASE` iteration unchanged. Replace `whisper-stt` family
  IDs and copy with `transcription-stt`, `Transcription`, and
  `Local speech-to-text models and their required tokenizer assets.`

- [ ] **Step 4: Run storage and cleanup regressions**

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_model_storage.py \
    app/tests/test_storage_policy.py
  ```

  Expected: PASS.

---

### Task 4: Internal capability UI and API wording

**Files:**
- Modify: `app/backend/main.py:1382-1465`
- Modify: `app/frontend/index.html:1303-1510,2115-2195`
- Modify: `app/frontend/app.js:160-175,1060-1070,1515-1550,3579-3665`
- Modify: `app/frontend/style.css`
- Create: `app/tests/test_frontend_transcription_candidates.py`
- Create: `app/tests/browser_fixtures/transcription_candidates_fixture.py`

**Interfaces:**
- Consumes: additive availability row fields from Task 1 and unchanged `/api/transcribe` request/response shapes from Task 2.
- Produces: generic transcription copy, capability badges, disabled unsupported timing control, and generic post-download polling.

- [ ] **Step 1: Run Impeccable once and read its hardening references**

  Run the repository-approved Impeccable context/detector exactly once for this
  UI change and record only findings that intersect the transcription surface.
  Do not repeat the detector after behavior-only fixes.

- [ ] **Step 2: Write frontend RED tests**

  Execute the relevant extracted Alpine component methods with complete literal
  availability rows. Prove:

  - selecting Moonshine makes `sttWordTimestampsSupported` false and clears a
    previously true `stt.wordTimestamps` value;
  - selecting Nemotron leaves word timing available;
  - download polling treats both new repos as transcription models;
  - the visible card text includes `Internal pilot`, `8 GB candidate`, language,
    and timing/long-form truth;
  - headings and form labels say `Transcription`, not `Whisper model`.

- [ ] **Step 3: Run the focused frontend test and capture RED**

  ```bash
  conda_env/bin/python -m pytest -q app/tests/test_frontend_transcription_candidates.py
  ```

  Expected: failures because the UI has no candidate capabilities and uses
  Whisper-only wording.

- [ ] **Step 4: Implement the minimal UI**

  Add getters:

  ```javascript
  get sttSelectedModel() {
    return (this.stt.models || []).find(m => m.repo === this.stt.model) || null;
  },
  get sttWordTimestampsSupported() {
    return !this.sttSelectedModel || this.sttSelectedModel.supports_word_timestamps !== false;
  },
  selectTranscriptionModel(repo) {
    this.stt.model = repo;
    if (!this.sttWordTimestampsSupported) this.stt.wordTimestamps = false;
  },
  ```

  Route the `<select>` change through `selectTranscriptionModel`, rename
  `_pollWhisperUntilCached` to `_pollTranscriptionUntilCached`, and use generic
  transcription wording in comments and visible copy. Disable the word timing
  checkbox when unsupported and show one adjacent explanation. Add only the CSS
  needed for readable wrapping and badges; reuse existing chip styles first.

- [ ] **Step 5: Run frontend tests and syntax checks**

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_frontend_transcription_candidates.py \
    app/tests/test_frontend_readability.py
  node --check app/frontend/app.js
  ```

  Expected: PASS.

- [ ] **Step 6: Perform offline rendered QA**

  Start only the loopback fixture. At desktop and 390 px widths, verify both
  candidates, badges, capability explanation, model selection, Moonshine timing
  disable/clear behavior, Nemotron timing enable behavior, keyboard operation,
  focus retention, 44 px controls, and zero page overflow. Stop the fixture and
  verify its listener is gone. Do not open a live Voice Studio or download a
  model.

---

### Task 5: Release 2.4.0, documentation, and final verification

**Files:**
- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `MODEL_CATALOG_GUIDE.md`
- Review all Task 1-4 files

**Interfaces:**
- Consumes: the complete internal pilot implementation.
- Produces: one truthful Voice Studio 2.4.0 release commit.

- [ ] **Step 1: Update release and operator documentation**

  Set VERSION to `2.4.0`. Add the first changelog entry dated `2026-08-17` and
  update README/model-catalog guidance with exact repos, sizes, 8 GB candidate
  wording, Whisper default preservation, Moonshine limitations, Nemotron timed
  output, and the no-GenStudio/no-fleet statement.

- [ ] **Step 2: Run focused release tests**

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_transcription_model_registry.py \
    app/tests/test_transcription_engines.py \
    app/tests/test_model_storage.py \
    app/tests/test_frontend_transcription_candidates.py \
    app/tests/test_release_metadata.py
  python3 release_metadata_check.py
  ```

  Expected: PASS.

- [ ] **Step 3: Run the full frozen-diff verification matrix**

  ```bash
  conda_env/bin/python -m pytest -q app/tests
  conda_env/bin/python -m compileall -q app
  conda_env/bin/python -m pip check
  node --check app/frontend/app.js
  python3 audit_truth.py --strict
  git diff --check
  ```

  Also run `bash -n` on every changed shell file if any appears unexpectedly;
  the intended diff contains none.

- [ ] **Step 4: Review the frozen diff**

  Perform one security/runtime review and one product-truth/UI review. Resolve
  every Critical or Important finding with a new RED test and rerun the affected
  focused suite plus the full matrix.

- [ ] **Step 5: Stage exact files and create one product commit**

  Stage only the files enumerated by Tasks 1-5. Run:

  ```bash
  git diff --cached --check
  python3 release_metadata_check.py
  git commit -m "feat: add internal Moonshine and Nemotron ASR pilots"
  git show --check --stat HEAD
  ```

  Do not push, update the fleet, download models, or restart services without a
  separate owner instruction.
