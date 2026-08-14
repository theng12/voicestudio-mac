# Model-Aware Long-Form Section Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Voice Studio users select an audited 230–400 character private
section budget for the exact Qwen3-TTS 1.7B Base model, while Auto continues to
use its audited 400-character runtime policy and all other models remain
non-editable.

**Architecture:** Put the capability and resolver in `catalog.py`, which
already joins exact catalog rows with audited `long_form_policy` data. Both HTTP
entry points validate there before queuing, and `GenerationManager` resolves a
second time for internal callers before persisting a private resolved budget.
The Alpine UI consumes the catalog capability, persists the two supported
values with the existing per-repository preset map, and sends an override only
for a valid Custom choice.

**Tech Stack:** Python 3.12, FastAPI/Pydantic v2, Alpine.js, HTML/CSS,
pytest, existing model-audit records.

## Global Constraints

- Scope is only `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`.
- Auto omits `section_max_characters`; its audited runtime default remains 400.
- Custom accepts whole integers from 230 through 400 inclusive; 280 is a valid default Custom value.
- The 300 ms sentence, 600 ms paragraph, and 180 ms soft pauses stay automatic and uneditable.
- A retry uses `min(resolved_budget, 230)` for both chunking and duration validation.
- Unsupported models hide the control and reject a non-null override with a 422 error.
- GenStudio continues to send one complete script and never receives a section-budget field.
- Add no dependency, alternate storage format, model route, model audit, or launcher change.
- Release is Voice Studio `2.2.0`; use task-scoped commits, push the final release commit to `origin main`, and do not change a launcher or perform a broad fleet rollout.
- The sole post-release fleet action is a health/idle-gated canary on worker `0201`; it verifies installed UI/API/catalog/version state without generation or any other worker.

---

### Task 1: Publish a fail-closed catalog capability and shared resolver

**Files:**
- Modify: `app/backend/catalog.py:519-548,1509-1735`
- Modify: `app/tests/test_long_form_policy.py`
- Create: `app/tests/test_section_size_control.py`

**Interfaces:**
- Consumes: `ModelEntry`, `model_audits.input_limits(repo)`, and
  `long_form_policy.policy_for(family, repo, audited_section_max_characters=model_audits.input_limits(repo).get("private_section_max_characters"))`.
- Produces: `SectionSizeControl`, `section_size_control_for(repo)`, and
  `resolve_section_budget(family, repo, requested, capability=None)` for the
  web handlers and generation manager.

- [ ] **Step 1: Write catalog and resolver regressions first**

  In `app/tests/test_section_size_control.py`, add these assertions using
  `QWEN_17B_BASE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"`:

  ```python
  def test_catalog_publishes_only_the_audited_qwen_17b_control() -> None:
      payload = catalog.serialize_model(catalog.get_model(QWEN_17B_BASE))
      assert payload["long_form_delivery"]["section_size_control"] == {
          "minimum": 230, "maximum": 400, "step": 1,
          "default_custom": 280, "runtime_default": 400,
          "source": "qwen3-17b-production-audit",
      }
      other = catalog.serialize_model(catalog.get_model(
          "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"))
      assert other["long_form_delivery"]["section_size_control"] is None

  @pytest.mark.parametrize("requested", [None, 230, 280, 400])
  def test_resolve_section_budget_accepts_only_auto_and_audited_values(requested):
      result = catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, requested)
      assert result["section_max_characters"] == (400 if requested is None else requested)
      assert result["source"] == ("audit" if requested is None else "caller_override")
  ```

  Add parameterized rejections for `229`, `401`, `True`, `280.0`, `"280"`,
  `float("inf")`, and a 0.6B Base override. Assert the exact codes
  `SECTION_MAX_CHARACTERS_INVALID`, `SECTION_MAX_CHARACTERS_OUT_OF_RANGE`, or
  `SECTION_MAX_CHARACTERS_UNSUPPORTED`. Monkeypatch the audited Qwen policy to
  399 and assert `section_size_control_for(QWEN_17B_BASE) is None` and any
  override fails unsupported; this proves the catalog fails closed on an
  audit/capability mismatch.

- [ ] **Step 2: Run the focused tests and confirm RED**

  Run:

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_section_size_control.py \
    app/tests/test_long_form_policy.py
  ```

  Expected: FAIL because no catalog capability, resolver, or
  `long_form_delivery.section_size_control` serialization exists.

- [ ] **Step 3: Add the smallest typed capability representation**

  In `app/backend/catalog.py`, add this immutable value object before
  `ModelEntry`, then add `section_size_control: SectionSizeControl | None = None`
  as the final `ModelEntry` field so all existing rows preserve their defaults:

  ```python
  @dataclass(frozen=True)
  class SectionSizeControl:
      minimum: int
      maximum: int
      step: int
      default_custom: int
      runtime_default: int
      source: str

      def serialize(self) -> dict[str, int | str]:
          return {
              "minimum": self.minimum,
              "maximum": self.maximum,
              "step": self.step,
              "default_custom": self.default_custom,
              "runtime_default": self.runtime_default,
              "source": self.source,
          }
  ```

  Assign exactly one `SectionSizeControl(230, 400, 1, 280, 400,
  "qwen3-17b-production-audit")` to the existing Qwen 1.7B Base `ModelEntry`.
  Do not add the field to a family, a second model, or an audit JSON.

- [ ] **Step 4: Implement capability lookup and resolution**

  Add this error type, then implement the exact interfaces below in `catalog.py`:

  ```python
  class SectionSizeControlError(ValueError):
      def __init__(self, code: str, detail: str) -> None:
          super().__init__(detail)
          self.code = code
  ```

  ```python
  def section_size_control_for(repo: str) -> dict[str, int | str] | None:
      entry = get_model(repo)
      if entry is None or entry.section_size_control is None:
          return None
      policy = long_form_policy.policy_for(
          entry.family,
          entry.repo,
          audited_section_max_characters=model_audits.input_limits(entry.repo).get(
              "private_section_max_characters"
          ),
      )
      if policy is None:
          return None
      control = entry.section_size_control.serialize()
      if policy["section_max_characters"] != control["runtime_default"]:
          return None
      return control

  def resolve_section_budget(
      family: str,
      repo: str,
      requested: object,
      capability: dict[str, int | str] | None = None,
  ) -> dict[str, object]:
      control = capability if capability is not None else section_size_control_for(repo)
      policy = long_form_policy.policy_for(
          family,
          repo,
          audited_section_max_characters=model_audits.input_limits(repo).get(
              "private_section_max_characters"
          ),
      )
      if policy is None:
          raise SectionSizeControlError(
              "SECTION_MAX_CHARACTERS_UNSUPPORTED",
              f"Model {repo} has no section-size control.",
          )
      resolved = int(policy["section_max_characters"])
      if requested is None:
          return {"section_max_characters": resolved, "source": "audit", "capability": control}
      if type(requested) is not int:
          raise SectionSizeControlError("SECTION_MAX_CHARACTERS_INVALID", "Section size must be a whole number.")
      if control is None:
          raise SectionSizeControlError("SECTION_MAX_CHARACTERS_UNSUPPORTED", f"Model {repo} has no section-size control.")
      if requested < control["minimum"] or requested > control["maximum"] or requested > resolved:
          raise SectionSizeControlError("SECTION_MAX_CHARACTERS_OUT_OF_RANGE", "Section size must be within the audited range.")
      return {"section_max_characters": requested, "source": "caller_override", "capability": control}
  ```

  `section_size_control_for` must obtain the exact model row, resolve the same
  audited long-form policy used by `serialize_model`, return `None` if no
  capability exists or its `runtime_default` differs from the resolved policy,
  and otherwise return the detached serialized capability. `serialize_model`
  must add `section_size_control` to every non-null
  `long_form_delivery` dictionary, using that helper; an unsupported model
  therefore publishes `null` rather than an implied editable default.

  `resolve_section_budget` must return
  `{"section_max_characters": int, "source": "audit" | "caller_override",
  "capability": dict | None}`. `requested is None` returns the audited policy
  limit and source `audit`. For a non-null request, reject before coercion when
  `type(requested) is not int`, reject no-capability or mismatched-capability
  calls with `SECTION_MAX_CHARACTERS_UNSUPPORTED`, and reject a value below
  230, above 400, or above the resolved audit maximum with
  `SECTION_MAX_CHARACTERS_OUT_OF_RANGE`. Never use the former 40–20,000 range.

- [ ] **Step 5: Run the focused tests and confirm GREEN**

  Run the Step 2 command. Expected: PASS, including null serialization for
  every other managed long-form model and fail-closed mismatch behavior.

- [ ] **Step 6: Commit the catalog contract**

  Stage only `app/backend/catalog.py`, `app/tests/test_long_form_policy.py`, and
  `app/tests/test_section_size_control.py`, then create this local checkpoint:

  ```bash
  git add app/backend/catalog.py app/tests/test_long_form_policy.py app/tests/test_section_size_control.py
  git commit -m "feat: add audited section size control contract"
  ```

  Expected: one commit containing only catalog capability/resolution behavior
  and its tests. Do not push until Task 5.

### Task 2: Enforce the resolved budget before queueing and throughout Qwen execution

**Files:**
- Modify: `app/backend/main.py:190-216,1092-1222`
- Modify: `app/backend/generation.py:997-1024,1923-1953,2092-2109,2300-2336,2774-2785`
- Modify: `app/tests/test_section_size_control.py`
- Modify: `app/tests/test_qwen_quality_guardrails.py:429-564`

**Interfaces:**
- Consumes: `catalog.resolve_section_budget(family, repo, requested, capability=None)`
  and an optional `section_max_characters` request value.
- Produces: private job parameter `_resolved_section_max_characters: int`; the
  Qwen duration validator and retry consume only that resolved value.

- [ ] **Step 1: Add HTTP and internal-caller failing regressions**

  Extend `app/tests/test_section_size_control.py` with a TestClient fixture that
  monkeypatches `main.gen_manager.is_available` to `True`, `main.cache.cache_state`
  to `"cached"`, and `main.gen_manager.start_txt2speech` to capture `params`.
  Test the normal endpoint with `230`, `280`, and `400`, then assert the captured
  payload contains `_resolved_section_max_characters` and no public
  `section_max_characters` key. Test `None` and omission similarly resolve to
  400. For an unsupported 0.6B Base override and Qwen values 229/401, assert
  HTTP 422 and exact `response.json()["detail"]["code"]` values.

  Exercise `/api/generate/txt2speech/reference` with a tiny WAV upload and
  JSON `request_json`; monkeypatch `reference_audio.prepare` to return a fixed
  prepared object. Assert the same 422 codes occur before `prepare` is called
  for invalid/unsupported overrides, and that valid Custom passes the private
  resolved value to `start_txt2speech`.

  Add direct `GenerationManager.start_txt2speech` tests using an inert manager
  and monkeypatched thread start: a raw internal Qwen 280 request receives
  `_resolved_section_max_characters == 280`; an internal 401 request raises
  `catalog.SectionSizeControlError` rather than creating a job.

- [ ] **Step 2: Add duration and retry RED cases**

  Add this parameterized duration test in
  `app/tests/test_qwen_quality_guardrails.py`:

  ```python
  @pytest.mark.parametrize("budget", [400, 280, 230])
  def test_qwen_duration_validation_uses_resolved_section_budget(budget):
      job = generation.GenerationJob(
          job_id=f"duration-{budget}", mode="txt2speech",
          params={"repo": QWEN_17B_BASE, "text": LONG_TEXT,
                  "speed": 1.0, "_resolved_section_max_characters": budget},
      )
      chunks = generation._internal_mlx_text_chunks(
          "qwen3-tts", QWEN_17B_BASE, LONG_TEXT, max_chars_override=budget)
      expected = round(sum(qwen_quality.automatic_duration_limit(chunk, 1.0)
                           for chunk in chunks) + (len(chunks) - 1) * 0.3, 3)
      assert generation.GenerationManager._qwen_job_duration_limit(job) == expected
  ```

  Update the existing retry test to begin with each resolved budget 400, 280,
  and 230 and assert attempts have retry section limits `[230, 230, 230]`.
  These must fail before implementation because the runtime reads a raw public
  override and the retry unconditionally writes 230.

- [ ] **Step 3: Remove schema-level generic bounds and centralize endpoint conversion**

  In `Txt2SpeechBody`, replace the current bounded `section_max_characters`
  declaration (the one carrying `ge=40` and `le=20_000`) with
  `section_max_characters: object | None = None`; this deliberately preserves
  the raw JSON type so the shared resolver can reject booleans, floats, and
  strings rather than Pydantic coercing them. Add one private `main.py` helper
  that calls `catalog.resolve_section_budget(model.family, body.repo,
  body.section_max_characters)` and maps `SectionSizeControlError` to:

  ```python
  raise HTTPException(
      status_code=422,
      detail={"code": exc.code, "detail": str(exc)},
  ) from exc
  ```

  Call it after the catalog/model capability checks and before the cache/engine
  checks or reference preparation in both POST routes. Build the queued params
  with `body.model_dump(exclude={"section_max_characters"})`, then add only
  `_resolved_section_max_characters` from the resolver. This keeps both job
  serialization and the GenStudio request contract free of a public control.

- [ ] **Step 4: Defend internal queueing and replace every raw override read**

  At the start of `GenerationManager.start_txt2speech`, obtain the catalog
  model, call the same resolver on `params.get("section_max_characters")`,
  remove `section_max_characters`, and set
  `_resolved_section_max_characters`. Preserve idempotency by resolving before
  constructing `client_request_params` so two semantically identical requests
  compare on their canonical private form.

  Replace `_qwen_section_max_characters` in `_qwen_job_duration_limit` with
  `_resolved_section_max_characters`; pass that same value to
  `_internal_mlx_text_chunks`. In `_generate_mlx_audio`, pass only
  `_resolved_section_max_characters` to the section chunker. On retry, overwrite
  `_resolved_section_max_characters` with:

  ```python
  min(
      int(job.params["_resolved_section_max_characters"]),
      qwen_quality.RETRY_SECTION_MAX_CHARACTERS,
  )
  ```

  Do not alter `_production_join_pauses_s`, final tempo processing, reference
  preparation, the retry count, or the atomic output flow.

- [ ] **Step 5: Run the backend tests and confirm GREEN**

  Run:

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_section_size_control.py \
    app/tests/test_long_form_policy.py \
    app/tests/test_qwen_quality_guardrails.py \
    app/tests/test_reference_audio_contract.py
  ```

  Expected: PASS. The duration regression must prove each custom budget changes
  chunking and validation together, while the retry never enlarges a request.

- [ ] **Step 6: Commit the backend enforcement**

  Stage only `app/backend/main.py`, `app/backend/generation.py`,
  `app/tests/test_section_size_control.py`, and
  `app/tests/test_qwen_quality_guardrails.py`, then create this local
  checkpoint:

  ```bash
  git add app/backend/main.py app/backend/generation.py app/tests/test_section_size_control.py app/tests/test_qwen_quality_guardrails.py
  git commit -m "feat: enforce model-aware section budgets"
  ```

  Expected: one commit that makes both HTTP entry points and internal callers
  obey the resolved private budget. Do not push until Task 5.

### Task 3: Add the catalog-driven Advanced UI with persistence and accessibility

**Files:**
- Modify: `app/frontend/app.js:75-145,770-850,1035-1080,2955-3075`
- Modify: `app/frontend/index.html:940-955`
- Modify: `app/frontend/style.css:543-579,1248-1266,2804-2825`
- Modify: `app/tests/test_long_form_policy.py`
- Modify: `app/tests/test_frontend_readability.py`

**Interfaces:**
- Consumes: `selectedModel.long_form_delivery.section_size_control` and the
  existing `voicestudio.gen.presets` repository-keyed localStorage object.
- Produces: `gen.section_size_mode: "auto" | "custom"`,
  `gen.section_max_characters: number`, a valid/invalid state for `canSubmit`,
  and an outbound JSON body that omits Auto.

- [ ] **Step 1: Add source-level UI regressions before editing markup**

  In `test_long_form_policy.py`, assert the UI uses the catalog capability and
  does not hard-code a repository name in visibility logic:

  ```python
  assert "sectionSizeControl" in script
  assert "selectedModel?.long_form_delivery?.section_size_control" in script
  assert '"section_size_mode", "section_max_characters"' in script
  assert "section_max_characters" in markup
  ```

  Assert the request builder uses conditional assignment rather than an
  unconditional JSON field:

  ```python
  assert "if (this.sectionSizeControlSupported && this.gen.section_size_mode === \"custom\")" in script
  assert "body.section_max_characters = this.sectionSizeValue" in script
  ```

  In `test_frontend_readability.py`, assert the markup contains a `fieldset`,
  visible `legend`, numeric input `min="230" max="400" step="1"`, a label
  connected with `for=`, `aria-invalid`, `aria-describedby`, and one
  `aria-live="polite"` validation node. Assert CSS defines
  `.section-size-grid` and its mobile rule selects `grid-template-columns: 1fr`.

- [ ] **Step 2: Run the UI source checks and confirm RED**

  Run:

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_long_form_policy.py \
    app/tests/test_frontend_readability.py
  ```

  Expected: FAIL because the state, semantics, persistence fields, and grid do
  not exist.

- [ ] **Step 3: Add minimal derived state and preserve it per model**

  Add `section_size_mode: "auto"` and `section_max_characters: 280` to `gen`.
  Append both exact field names to `_GEN_PRESET_FIELDS`, retaining the current
  localStorage key and watcher logic. Add these helpers/getters to `app.js`:

  ```javascript
  get sectionSizeControl() {
    return this.selectedModel?.long_form_delivery?.section_size_control || null;
  },
  get sectionSizeControlSupported() { return !!this.sectionSizeControl; },
  get sectionSizeValue() { return Number(this.gen.section_max_characters); },
  get sectionSizeIsValid() {
    const c = this.sectionSizeControl;
    return !c || this.gen.section_size_mode === "auto" || (
      Number.isInteger(this.sectionSizeValue) &&
      this.sectionSizeValue >= c.minimum && this.sectionSizeValue <= c.maximum &&
      this.sectionSizeValue <= c.runtime_default
    );
  },
  resetSectionSizeToAuto() { this.gen.section_size_mode = "auto"; },
  ```

  Extend `canSubmit` and `submitHint` only when Custom is selected and the
  capability is present. On a repository change, keep that repository's stored
  mode/value; a new/no-preset Qwen row starts Auto/280. Unsupported rows neither
  submit nor reset a field and never get the block.

- [ ] **Step 4: Build the collapsed, keyboard-accessible control and request shape**

  Insert immediately after the existing Speed section:

  ```html
  <details class="control-block" x-show="sectionSizeControlSupported" x-cloak>
    <summary>Long-form delivery</summary>
    <div class="advanced-inner">
      <fieldset>
        <legend>Section size</legend>
        <label><input type="radio" value="auto" x-model="gen.section_size_mode"> Auto</label>
        <label><input type="radio" value="custom" x-model="gen.section_size_mode"> Custom</label>
        <label for="section-max-characters">Characters per section</label>
        <input id="section-max-characters" type="number" x-model.number="gen.section_max_characters">
      </fieldset>
    </div>
  </details>
  ```

  Implement the radio labels, an explicit `for="section-max-characters"`
  number label, `x-model.number="gen.section_max_characters"`, capability-bound
  `:min`, `:max`, and `:step`, `:aria-invalid="!sectionSizeIsValid"`, and an
  `aria-describedby` link to a concise help/error block. Put the error text in
  a stable `role="status" aria-live="polite"` element. Add a standard button
  labelled `Reset to Auto` wired to `resetSectionSizeToAuto()`. The help must
  state that Auto uses the audited 400-character policy and that the existing
  300/600/180 ms pauses remain automatic.

  In `buildBody`, first create the existing `body` object, then conditionally
  execute `body.section_max_characters = this.sectionSizeValue` only when the
  supported control is Custom and valid. Auto must omit the key rather than
  send `null`. Add compact `.section-size-grid`, radio row, invalid-state, and
  live-error styles that reuse the current control colors; at the existing
  `max-width: 900px` breakpoint collapse `.section-size-grid` to one column.

- [ ] **Step 5: Run source checks and perform the visual interaction check**

  Run the Step 2 command and then start the normal local UI without restarting
  any existing service. At desktop and 375 px mobile widths, inspect the
  Generate tab and verify: the block is collapsed immediately after Speed;
  it appears only for Qwen 1.7B Base; Auto enables Generate and omits the
  field; Custom 230/280/400 enables Generate; 229, 400.5, and 401 disable it
  and announce the error; Reset to Auto is keyboard reachable and restores
  validity; switching repos retains each repository's own mode/value.

- [ ] **Step 6: Commit the supported-model UI**

  Stage only `app/frontend/app.js`, `app/frontend/index.html`,
  `app/frontend/style.css`, `app/tests/test_long_form_policy.py`, and
  `app/tests/test_frontend_readability.py`, then create this local checkpoint:

  ```bash
  git add app/frontend/app.js app/frontend/index.html app/frontend/style.css app/tests/test_long_form_policy.py app/tests/test_frontend_readability.py
  git commit -m "feat: add section size control UI"
  ```

  Expected: one commit containing catalog-driven UI state, persistence,
  responsive styles, and accessibility regressions. Do not push until Task 5.

### Task 4: Document and verify the 2.2.0 feature release

**Files:**
- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Verify: all files from Tasks 1–3

**Interfaces:**
- Consumes: the finished catalog/API/UI behavior and current release metadata
  guard.
- Produces: a truthful `2.2.0` release commit ready for final root verification
  and the limited Task 5 push/canary procedure.

- [ ] **Step 1: Add the release/documentation RED checks**

  In `app/tests/test_release_metadata.py`, add an assertion that the current
  release remains a valid semantic version/changelog pair after setting the
  intended version to 2.2.0. In `README.md`, add a concise Generate-tab/API
  subsection stating the exact Qwen 1.7B Base scope, Auto=400, Custom=230–400,
  automatic 300/600/180 pauses, and that direct callers omit the field for
  Auto or send an integer for Custom. Add source assertions for those literals
  in `test_section_size_control.py`.

- [ ] **Step 2: Run the documentation checks and confirm RED**

  Run:

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_section_size_control.py \
    app/tests/test_release_metadata.py
  ```

  Expected: FAIL until the feature docs and 2.2.0 release metadata exist.

- [ ] **Step 3: Publish only truthful release metadata**

  Set `VERSION` to `2.2.0`. Add the first `CHANGELOG.md` release section dated
  `2026-08-14` with an `### Added` heading and bullets covering catalog-gated
  Qwen-only Custom size, Auto preserving the audited 400 default, rejected
  unsupported/raw values, the unchanged pauses, per-model persistence, and no
  GenStudio contract change. Do not state that all Qwen models, other engines,
  or pause controls are configurable.

- [ ] **Step 4: Run focused and full verification**

  Run these commands in order:

  ```bash
  conda_env/bin/python -m pytest -q \
    app/tests/test_section_size_control.py \
    app/tests/test_long_form_policy.py \
    app/tests/test_qwen_quality_guardrails.py \
    app/tests/test_reference_audio_contract.py \
    app/tests/test_frontend_readability.py \
    app/tests/test_release_metadata.py
  conda_env/bin/python -m pytest -q
  conda_env/bin/python -m compileall -q app/backend app/tests
  conda_env/bin/python -m pip check
  python3 audit_truth.py --strict
  python3 audit_contract_runtime.py --strict
  python3 release_metadata_check.py
  node --check pinokio.js
  node --check start.js
  node --check update.js
  node --check install_generation.js
  bash -n voicestudio-serve.sh voicestudio-watchdog.sh
  git diff --check
  ```

  Expected: every command exits zero. Re-run the Task 3 desktop/mobile visual
  checklist after the full suite; it is the required rendered UI confirmation.

- [ ] **Step 5: Review and commit the release scope**

  Run `git diff -- VERSION CHANGELOG.md README.md app/backend/catalog.py
  app/backend/main.py app/backend/generation.py app/frontend/app.js
  app/frontend/index.html app/frontend/style.css app/tests` and confirm the
  diff contains only the audited Qwen 1.7B section control, its tests, and its
  2.2.0 documentation. Preserve unrelated untracked/dirty work. Stage only
  `VERSION`, `CHANGELOG.md`, `README.md`, `app/tests/test_release_metadata.py`,
  `app/tests/test_section_size_control.py`, and these two planning documents,
  then commit:

  ```bash
  git add VERSION CHANGELOG.md README.md app/tests/test_release_metadata.py app/tests/test_section_size_control.py \
    docs/superpowers/specs/2026-08-14-model-aware-section-control-design.md \
    docs/superpowers/plans/2026-08-14-model-aware-section-control.md
  git commit -m "release: Voice Studio 2.2.0 section control"
  ```

  Expected: the final local release commit contains the 2.2.0 metadata,
  documentation, release regression, and approved design/plan. Do not push
  until Task 5's root verification has passed.

### Task 5: Integrate, push, and run the sole 0201 post-release canary

**Files:**
- Verify: committed files from Tasks 1–4
- Create: `/Users/thengmacmini/Developer/_handoffs/voicestudio-0201-2.2.0-section-control.md`

**Interfaces:**
- Consumes: the completed `main` branch, the committed `2.2.0` release, and
  authenticated worker `0201` health/status endpoints.
- Produces: a pushed `origin/main` release and one bounded, no-generation
  `0201` canary evidence handoff; all other workers remain untouched.

- [ ] **Step 1: Perform final root verification on the committed release**

  From the repository root, verify that `HEAD` contains the expected release,
  that the worktree is clean, and that the full release suite still passes:

  ```bash
  git log -1 --oneline
  git status --short
  conda_env/bin/python -m pytest -q
  conda_env/bin/python -m compileall -q app/backend app/tests
  conda_env/bin/python -m pip check
  python3 audit_truth.py --strict
  python3 audit_contract_runtime.py --strict
  python3 release_metadata_check.py
  node --check pinokio.js
  node --check start.js
  node --check update.js
  node --check install_generation.js
  bash -n voicestudio-serve.sh voicestudio-watchdog.sh
  git diff --check HEAD~1..HEAD
  ```

  Expected: `VERSION` is 2.2.0, each command exits zero, and `git status
  --short` is empty. If a pre-existing unrelated change prevents a clean
  worktree, preserve it and stop for owner direction rather than staging it.

- [ ] **Step 2: Push only the reviewed release branch**

  Confirm the tracked branch is `main`, then push the exact reviewed commit:

  ```bash
  test "$(git branch --show-current)" = main
  git push origin main
  ```

  Expected: `origin/main` advances to the reviewed 2.2.0 release commit. Do
  not tag, deploy a broad rollout, or modify any launcher.

- [ ] **Step 3: Gate the single 0201 canary on health and idleness**

  Use the authenticated worker-0201 Voice Studio endpoints supplied by the
  fleet inventory. Read `GET /api/health` and `GET /api/generate/diagnostics`.
  Proceed only when health reports `app_version: "2.2.0"`, no active
  generation/transcription/download work, and diagnostics reports the Qwen
  engine ready. If any condition is false, record the observed state in the
  handoff and stop; do not restart, update, submit a job, or contact another
  worker.

- [ ] **Step 4: Verify the installed 0201 surface without generation**

  Read `GET /api/catalog` and assert the exact Qwen 1.7B Base row publishes
  `long_form_delivery.section_size_control` with 230/400/1/280/400 values and
  all other rows publish `null`. Open worker 0201's Generate tab at desktop and
  375 px widths; select that model and verify the collapsed Long-form delivery
  block follows Speed, Auto omits the request key, Custom 280 includes integer
  `section_max_characters: 280`, and invalid input disables Generate. Use the
  browser network inspector or the UI request builder only; do not submit a
  generation. Confirm 0.6B Base hides the block. Do not access any other
  worker.

- [ ] **Step 5: Write the canary handoff and stop**

  Write `/Users/thengmacmini/Developer/_handoffs/voicestudio-0201-2.2.0-section-control.md`
  with the release commit, `origin/main` push result, health/diagnostic
  timestamps, observed version, catalog capability JSON, desktop/mobile UI
  result, Auto/Custom request-shape result, and an explicit `generation_run:
  false`. Address it to the primary agent/owner and state that no other worker
  was contacted. Do not authorize or perform a broader rollout.

## Plan Self-Review

- **Spec coverage:** Task 1 covers exact catalog gating and audit mismatch;
  Task 2 covers both API entry points, private job state, chunking, duration,
  and retry; Task 3 covers visibility, Auto/Custom request shape, persistence,
  keyboard/accessibility, responsive layout, and fixed pauses; Task 4 covers
  2.2.0 metadata, README, visual inspection, and all required checks; Task 5
  covers final root verification, reviewed push, one idle 0201 canary, and the
  bounded handoff with no generation or broader rollout.
- **Placeholder scan:** This plan contains no TBD/TODO/future-work steps and
  every test, interface, error code, file, and command is named explicitly.
- **Type consistency:** `SectionSizeControl` serializes the capability used by
  `section_size_control_for`; `resolve_section_budget` returns
  `_resolved_section_max_characters`; the backend and frontend both use
  `section_max_characters` only as the public Custom request key; retry writes
  the same private resolved field consumed by chunking and duration validation.

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-08-14-model-aware-section-control.md`.

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task and
   review between tasks.
2. **Inline Execution** — execute tasks in this session with checkpoints.
