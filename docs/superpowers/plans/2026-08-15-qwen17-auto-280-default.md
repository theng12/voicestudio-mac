# Qwen3-TTS 1.7B Auto 280 Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Release Voice Studio 2.2.1 so Qwen3-TTS 1.7B Base resolves Auto and omitted section-size requests to 280 characters, while preserving Custom 230–400.

**Architecture:** The hash-bound production-v2 audit is the source of truth for Qwen 1.7B Auto 280 and safe Custom maximum 400. A Qwen-specific fail-closed audit accessor feeds catalog, HTTP, and direct queue resolution, so an absent, malformed, mismatched, or stale audit cannot revive the old 400 Auto behavior. Auto continues to omit section_max_characters at the public boundary and queue only _resolved_section_max_characters.

**Tech Stack:** Python 3, FastAPI/Pydantic, pytest, vanilla JavaScript/Alpine markup, static model-audit JSON, Studio Hub maintenance APIs, Git.

## Global Constraints

- Scope only mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit; all other models retain their present policies and have no editable section-size control.
- Auto/omitted and JSON null resolve to **280**. Custom accepts exact int values **230–400 inclusive**. Boolean, float, string, non-finite, 229, and 401 values retain stable 422 codes.
- Preserve model-audits/2026-08-14-qwen3-17b-production/mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json byte-for-byte, including v1 ID voicestudio-20260814-qwen3-tts-1.7b-base-production-v1 and hash sha256:c9be3368abdb8817369cc09a01231c8f1f5a7d68b936a0494920a918b3b8a38a.
- Add v2 ID voicestudio-20260815-qwen3-tts-1.7b-base-production-v2. Retain model revision e7dd0585652209fa0d7783659aad4e8a324de11c, adapter voicestudio.mlx-audio.qwen3-tts-base 1.4, and all present evidence except approved default/evidence changes.
- V2 contract and duplicated candidate limits contain private_section_max_characters: 400 and default_private_section_max_characters: 280. Candidate hash equals model_audits.contract_hash(record["contract"]).
- Retry stays **230** (min(resolved_budget, 230)); sentence/paragraph/soft join pacing stays **300/600/180 ms**; all-frame assembly, no destructive trim, and no speech crossfade stay unchanged.
- No dependency, launcher, installation marker, cache, model, public GenStudio parameter, price, hardware eligibility, or inference change.
- This control/development Mac is never a generation, model-qualification, transcription, or production-worker target.
- Ship patch version **2.2.1** with a truthful top CHANGELOG.md entry and pass python3 release_metadata_check.py.

---

## File Structure

- Modify: app/backend/model_audits.py — validate and retrieve only the exact Qwen v2 contract, without v1/family fallback.
- Modify: app/backend/long_form_policy.py — use audit default for Qwen Auto and retain distinct audit maximum.
- Modify: app/backend/catalog.py — publish and resolve the 230/400/1/280/280 capability.
- Modify: app/backend/main.py and app/backend/generation.py — preserve HTTP and direct-queue canonicalization.
- Modify: audit_contract_runtime.py — check default 280 separately from maximum 400.
- Create: model-audits/2026-08-15-qwen3-17b-production-v2/mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json — immutable v2 audit.
- Modify: app/tests/test_model_audit_contract.py, app/tests/test_audit_contract_runtime.py, app/tests/test_long_form_policy.py, app/tests/test_section_size_control.py, app/tests/test_qwen_quality_guardrails.py.
- Modify: app/frontend/index.html, app/frontend/app.js, README.md, VERSION, and CHANGELOG.md.
- Create after successful canary: /Users/thengmacmini/Developer/_handoffs/2026-08-15_to-claude-genstudio_from-gpt-studiofleet_qwen17-auto-280-default.md.

### Task 1: Production-v2 audit and fail-closed selection

**Files:**
- Create: model-audits/2026-08-15-qwen3-17b-production-v2/mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json
- Modify: app/backend/model_audits.py:34-116
- Modify: audit_contract_runtime.py:751-807, 899-1011
- Test: app/tests/test_model_audit_contract.py:225-344
- Test: app/tests/test_audit_contract_runtime.py:232-279

**Interfaces:**
- Consumes: model_audits.contract_hash(contract: dict[str, Any]) -> str and the exact Qwen repository ID.
- Produces: model_audits.qwen_17b_production_v2_limits(model_id: str) -> dict[str, Any]. It returns detached private_section_max_characters and default_private_section_max_characters only for the exact valid v2 record; otherwise it returns {}.
- Produces: audit_contract_runtime.check_section_budget(contract: dict[str, Any], model_id: str, policy) -> dict[str, Any], checking both 400 maximum and 280 Auto default.

- [ ] **Step 1: Write failing v2 selection and immutability tests**

~~~python
def test_qwen_v1_is_byte_stable_and_v2_is_the_runtime_source() -> None:
    assert hashlib.sha256(QWEN_17B_V1.read_bytes()).hexdigest() == (
        "b45e061379df0d8ee9e2d8dc0754108b280db5293f9c2fe7d5b4cab2a5b74e76"
    )
    record = model_audits.audit_record(QWEN_17B_BASE)
    assert record["audit_id"] == "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2"
    assert model_audits.qwen_17b_production_v2_limits(QWEN_17B_BASE) == {
        "private_section_max_characters": 400,
        "default_private_section_max_characters": 280,
    }


@pytest.mark.parametrize("default", [None, True, 229, 401, 400.0])
def test_invalid_v2_default_fails_closed(default, monkeypatch, tmp_path) -> None:
    record = json.loads(QWEN_17B_V2.read_text(encoding="utf-8"))
    record["contract"]["input_limits"]["default_private_section_max_characters"] = default
    record["genstudio_candidate"]["input_limits"] = record["contract"]["input_limits"]
    record["genstudio_candidate"]["contract_hash"] = model_audits.contract_hash(
        record["contract"]
    )
    root = tmp_path / "2026-08-15-qwen3-17b-production-v2"
    root.mkdir(parents=True)
    (root / QWEN_17B_V2.name).write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(model_audits, "AUDIT_ROOT", tmp_path)
    assert model_audits.qwen_17b_production_v2_limits(QWEN_17B_BASE) == {}
~~~

- [ ] **Step 2: Run the tests to verify they fail**

Run: python3 -m pytest app/tests/test_model_audit_contract.py app/tests/test_audit_contract_runtime.py -q

Expected: FAIL because v2 and its fail-closed accessor do not exist, while prior tests expect v1 as latest.

- [ ] **Step 3: Add the v2 audit and audit accessor**

Copy v1 to v2, retaining original facts except the following explicit additions:

~~~json
{
  "audit_id": "voicestudio-20260815-qwen3-tts-1.7b-base-production-v2",
  "contract": {
    "input_limits": {
      "private_section_max_characters": 400,
      "default_private_section_max_characters": 280
    }
  },
  "evidence": {
    "supersedes_audit_id": "voicestudio-20260814-qwen3-tts-1.7b-base-production-v1",
    "v1_retained": "passed historical evidence; not revoked",
    "section_policy": {
      "auto_default_private_section_max_characters": 280,
      "custom_private_section_max_characters": {"minimum": 230, "maximum": 400},
      "retry_section_max_characters": 230,
      "owner_approved_configuration": true
    }
  }
}
~~~

Duplicate the complete contract.input_limits object under genstudio_candidate.input_limits. Compute, do not hand-type, the candidate hash:

~~~python
record["genstudio_candidate"]["contract_hash"] = model_audits.contract_hash(
    record["contract"]
)
~~~

Implement qwen_17b_production_v2_limits() to read only the fixed v2 record. Require exact repo and audit IDs, valid schema/hash/duplicated candidate fields, exact integer maximum 400, exact integer default 280, and 230 <= default <= maximum. Missing, unreadable, malformed, hash-invalid, or duplicate-mismatched v2 returns {}; it never uses v1, another directory, or QWEN_CLONE_SECTION_MAX_CHARACTERS.

Extend contract-runtime section-budget validation to reject missing/non-int/out-of-range v2 default and compare runtime Auto to 280 separately from maximum 400.

- [ ] **Step 4: Run the focused audit tests**

Run: python3 -m pytest app/tests/test_model_audit_contract.py app/tests/test_audit_contract_runtime.py -q

Expected: PASS; v1 is byte-stable, v2 selected, invalid/defaultless v2 exposes no limits, and runtime validation recognizes 280 default plus 400 maximum.

- [ ] **Step 5: Commit**

~~~bash
git add app/backend/model_audits.py audit_contract_runtime.py model-audits/2026-08-15-qwen3-17b-production-v2 app/tests/test_model_audit_contract.py app/tests/test_audit_contract_runtime.py
git commit -m "feat: bind Qwen Auto default to v2 audit"
~~~

### Task 2: Catalog, HTTP, and queue resolution

**Files:**
- Modify: app/backend/long_form_policy.py:149-310
- Modify: app/backend/catalog.py:518-535, 1546-1619, 1770-1794
- Modify: app/backend/main.py:187-199, 1100-1134, 1137-1225
- Modify: app/backend/generation.py:1923-1957
- Test: app/tests/test_long_form_policy.py:10-59
- Test: app/tests/test_section_size_control.py:1-554

**Interfaces:**
- Consumes: qwen_17b_production_v2_limits(repo) -> dict[str, Any].
- Produces: long_form_policy.policy_for(family: str, repo: str, *, audited_section_max_characters: object = None, audited_default_section_max_characters: object = None) -> dict | None; v2 Qwen policy has section_max_characters == 280.
- Produces: catalog.section_size_control_for(repo: str) -> dict[str, int | str] | None; v2 Qwen serializes exactly {"minimum": 230, "maximum": 400, "step": 1, "default_custom": 280, "runtime_default": 280, "source": "qwen3-17b-production-v2-audit"}.
- Produces: catalog.resolve_section_budget(family: str, repo: str, requested: object, capability: dict[str, int | str] | None = None) -> dict[str, object].

- [ ] **Step 1: Write failing resolver and canonicalization tests**

~~~python
@pytest.mark.parametrize("requested, expected, source", [
    (None, 280, "audit"), (230, 230, "caller_override"),
    (280, 280, "caller_override"), (400, 400, "caller_override"),
])
def test_qwen_v2_resolves_auto_and_custom(requested, expected, source) -> None:
    result = catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, requested)
    assert result["section_max_characters"] == expected
    assert result["source"] == source


def test_genstudio_shaped_omission_resolves_before_queueing(queued_txt2speech_params) -> None:
    response = _client().post("/api/generate/txt2speech", json={
        "repo": QWEN_17B_BASE, "text": "Voice Studio owns Auto."
    })
    assert response.status_code == 200
    assert queued_txt2speech_params[0]["_resolved_section_max_characters"] == 280
    assert "section_max_characters" not in queued_txt2speech_params[0]


def test_missing_v2_never_falls_back_to_400(monkeypatch) -> None:
    monkeypatch.setattr(catalog.model_audits, "qwen_17b_production_v2_limits", lambda _: {})
    assert catalog.section_size_control_for(QWEN_17B_BASE) is None
    with pytest.raises(catalog.SectionSizeControlError) as error:
        catalog.resolve_section_budget("qwen3-tts", QWEN_17B_BASE, 280)
    assert error.value.code == "SECTION_MAX_CHARACTERS_UNSUPPORTED"
~~~

- [ ] **Step 2: Run the resolver tests to verify they fail**

Run: python3 -m pytest app/tests/test_section_size_control.py app/tests/test_long_form_policy.py -q

Expected: FAIL because Auto remains 400, source remains production-v1, Custom 400 becomes invalid if the old request > resolved guard remains, and missing audit still falls back.

- [ ] **Step 3: Implement separate default and maximum handling**

Extend policy_for() with audited_default_section_max_characters. For exact Qwen 1.7B only, accept policy only if maximum/default are exact ints and 230 <= default <= maximum == 400, then use default 280 for LongFormPolicy.section_max_characters. Do not apply either field to Qwen 0.6B or other families.

Use the v2 accessor in catalog callers. Keep generic model_audits.input_limits() for non-Qwen data. Build Qwen control exactly:

~~~python
SectionSizeControl(
    minimum=230,
    maximum=400,
    step=1,
    default_custom=280,
    runtime_default=280,
    source="qwen3-17b-production-v2-audit",
).serialize()
~~~

When requested is None, require derived v2 control and return runtime_default. For Custom, validate exact int against minimum and maximum only; remove old requested > resolved comparison because 400 is valid Custom despite Auto 280. Preserve SECTION_MAX_CHARACTERS_INVALID, SECTION_MAX_CHARACTERS_OUT_OF_RANGE, and SECTION_MAX_CHARACTERS_UNSUPPORTED.

Keep main._resolve_section_budget() routes and GenerationManager.start_txt2speech() as independent canonicalization boundaries. They remove raw section_max_characters and store only _resolved_section_max_characters; forged private values revalidate against current v2 capability. Non-Qwen omission stays unchanged.

- [ ] **Step 4: Run resolver tests**

Run: python3 -m pytest app/tests/test_section_size_control.py app/tests/test_long_form_policy.py -q

Expected: PASS; omitted/null resolves 280, Custom 230/280/400 resolves exactly, invalid values retain codes, endpoint/queue store private value only, and v2 failure has no 400 fallback.

- [ ] **Step 5: Commit**

~~~bash
git add app/backend/long_form_policy.py app/backend/catalog.py app/backend/main.py app/backend/generation.py app/tests/test_long_form_policy.py app/tests/test_section_size_control.py
git commit -m "feat: resolve Qwen Auto sections at 280"
~~~

### Task 3: Quality regression coverage, UI, documentation, and release

**Files:**
- Modify: app/tests/test_qwen_quality_guardrails.py:436-540
- Modify: app/frontend/index.html:957-985
- Modify: app/frontend/app.js:84-90, 817-824, 968-1105, 3114-3116
- Modify: README.md, VERSION, CHANGELOG.md

**Interfaces:**
- Consumes: catalog section control minimum, maximum, step, default_custom, runtime_default.
- Produces: Auto help stating 280, Custom range 230–400, and a request body omitting the field while Auto is selected.
- Produces: version 2.2.1 and matching changelog heading.

- [ ] **Step 1: Write failing quality and UI-source tests**

~~~python
# Keep the existing test_rejected_local_qwen_output_retries_once_with_safer_settings
# parameter set [400, 280, 230] and its dispatch capture. After _run_txt2speech:
assert attempts == [(41, initial_budget), (42, 230)]


def test_qwen_section_control_copy_and_bounds_are_v2_truthful() -> None:
    markup = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert "Auto uses the audited 280-character policy" in markup
    assert "this.sectionSizeValue <= c.maximum" in script
    assert "this.sectionSizeValue <= c.runtime_default" not in script
~~~

- [ ] **Step 2: Run quality/UI tests to verify they fail**

Run: python3 -m pytest app/tests/test_qwen_quality_guardrails.py app/tests/test_section_size_control.py app/tests/test_long_form_policy.py -q

Expected: FAIL because UI says Auto 400 and Custom validation caps at runtime_default.

- [ ] **Step 3: Make smallest UI/docs/release update**

Keep Auto request-body behavior: only Custom sends section_max_characters. Replace validation with:

~~~javascript
return !c || this.gen.section_size_mode === "auto" || (
  Number.isInteger(this.sectionSizeValue)
  && this.sectionSizeValue >= c.minimum
  && this.sectionSizeValue <= c.maximum
);
~~~

Change visible help to: Auto uses the audited 280-character policy. Custom accepts 230–400 characters per private section. The 300/600/180 ms pauses remain automatic. Preserve x-model.number, disabled Custom input under Auto, ARIA status, keyboard submit guard, Reset to Auto, and per-repository remembered Custom value. Seed Custom from default_custom 280, but never send it while Auto is selected.

Update README to distinguish Auto 280, Custom 230–400, safety max 400, retry 230, unchanged pacing, and Auto omission. Set VERSION to 2.2.1 and add a top 2.2.1 CHANGELOG Changed entry without claiming model/dependency/pacing changes.

- [ ] **Step 4: Run focused tests and visual check**

Run: python3 -m pytest app/tests/test_qwen_quality_guardrails.py app/tests/test_section_size_control.py app/tests/test_long_form_policy.py -q

Expected: PASS; retry remains 230, 400 is valid Custom, Auto stays omission, UI/docs say 280, and pacing remains unchanged.

Launch local app only as UI server; do not generate audio. Inspect desktop and 375 px Generate views. Confirm Auto default, visible disabled Custom input, Custom 230–400, invalid range announcement, Reset behavior, usable focus, and no horizontal overflow.

- [ ] **Step 5: Commit**

~~~bash
git add app/frontend/index.html app/frontend/app.js README.md VERSION CHANGELOG.md app/tests/test_qwen_quality_guardrails.py app/tests/test_section_size_control.py app/tests/test_long_form_policy.py
git commit -m "release: Voice Studio 2.2.1"
~~~

### Task 4: Verification, release, rolling rollout, and GenStudio handoff

**Files:**
- Create after passed canary: /Users/thengmacmini/Developer/_handoffs/2026-08-15_to-claude-genstudio_from-gpt-studiofleet_qwen17-auto-280-default.md
- Move only after explicit GenStudio v2 acknowledgement: /Users/thengmacmini/Developer/_handoffs/2026-08-14_to-gpt-studiofleet_from-claude-genstudio_qwen3-17b-swap-readiness.md to /Users/thengmacmini/Developer/_handoffs/_handoff-trash/

**Interfaces:**
- Consumes: version 2.2.1, pushed SHA, v2 candidate hash, Studio Hub status/update output.
- Produces: passed 0201 no-generation canary, sequential worker maintenance records, and GenStudio handoff awaiting exact v2 approval.

- [ ] **Step 1: Run complete release verification before push**

~~~bash
python3 -m pytest -q
python3 -m compileall -q app audit_contract_runtime.py
python3 release_metadata_check.py
python3 audit_contract_runtime.py
node --check app/frontend/app.js
bash -n install_service.sh restart_service.sh status_service.sh uninstall_service.sh voicestudio-serve.sh voicestudio-watchdog.sh
git diff --check
git status --short --branch
~~~

Expected: every command exits zero. Do not push, update workers, or hand off on a failure.

- [ ] **Step 2: Push release**

~~~bash
git push origin main
git rev-parse HEAD
git status --short --branch
~~~

Expected: origin/main contains 2.2.1, SHA recorded for rollout, worktree clean and synchronized.

- [ ] **Step 3: Run no-generation canary on voice@terranash-0201**

In Studio Hub select only voice@terranash-0201. Preflight: healthy, idle, no active job/download/maintenance, no memory recovery, cached Qwen 1.7B. Update to pushed SHA; wait for terminal healthy result. Then verify without generating: version 2.2.1, SHA, v2 audit ID/hash/revision, capability exactly 230/400/1/280/280, Auto omission resolution 280, Custom 230/280/400 acceptance, retry 230, and 300/600/180 assembly invariants. A reconnect is not success; final healthy postflight is required.

- [ ] **Step 4: Roll eligible Voice workers one at a time**

After only passed 0201 canary, Studio Hub updates one healthy idle eligible Voice worker at a time. Repeat preflight/postflight. Record an individual failed, unreachable, busy, unhealthy, or unexpectedly restarted worker and continue to the next eligible worker; one node never blocks the fleet-wide release. Stop only for a release-wide truth failure reproduced across healthy workers, such as the pushed release advertising the wrong audit/hash/default or the updater accepting active customer work. Do not update a controller serving active orchestration and never schedule the development Mac as a worker.

- [ ] **Step 5: Send exact GenStudio handoff after canary passes**

Create named handoff after Step 3. Include final version/SHA, repo/revision, v2 ID, JSON-derived hash, adapter 1.4, reference-audio facts, and exact semantic rule: GenStudio continues omitting section_max_characters; Voice Studio resolves omission 280; Voice-only Custom is 230–400; 400 safety max; retry 230 and 300/600/180 unchanged. Ask GenStudio to replace v1 approval only after validating the exact v2 pair. Do not change product ID, pricing, language gates, or the independent auto-canary in this handoff, and do not restate or override the separate owner ruling about OmniVoice retirement.

Leave incoming readiness letter pending until GenStudio explicitly acknowledges v2 ID/hash and its approval reflects that pair. Then move only that letter to _handoff-trash; do not touch Story Studio letters or separate OmniVoice-removal ruling.

## Plan Self-Review

- **Spec coverage:** Task 1 preserves v1 and creates/validates v2. Task 2 separates 280 Auto from 400 Custom max across policy/catalog/HTTP/queue. Task 3 locks retry/pacing and delivers accessible truthful UI/docs/release. Task 4 verifies, pushes, canaries, rolls sequentially, and sends required GenStudio contract.
- **Placeholder scan:** No TBD, TODO, implement later, or unspecified test remains. SHA and candidate hash are derived from pushed repo and v2 JSON at execution time.
- **Type consistency:** qwen_17b_production_v2_limits() feeds policy_for(), section_size_control_for(), resolve_section_budget(), UI, HTTP, and queueing. Auto uses runtime_default 280; Custom validates through maximum 400.

Plan complete and saved to docs/superpowers/plans/2026-08-15-qwen17-auto-280-default.md. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
