# Qwen3-TTS 1.7B Auto 280 Default Design

## Decision

For the exact `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` model only,
Voice Studio **Auto** and an omitted `section_max_characters` request resolve
to **280** private characters. **Custom** continues to accept only whole
integers from **230 through 400 inclusive**. The 400-character value remains
the audited safety maximum; it is not a default and must not be lowered in the
capability range.

This is a compatible patch release of Voice Studio after 2.2.0. It changes no
model, checkpoint revision, inference dependency, launcher, worker topology,
or public GenStudio request shape. Qwen's single quality retry remains 230;
the private 300 ms sentence, 600 ms paragraph, and 180 ms soft-split pacing
and all-frame-retained/no-destructive-trim assembly contract remain unchanged.

## Scope and invariants

The change applies only to the Qwen 1.7B Base repository above. Qwen 0.6B,
Qwen CustomVoice/VoiceDesign, and every other catalog model retain their
current policies and receive no editable section-size capability.

The following are invariants of the new contract:

- Auto is represented at the Voice Studio HTTP boundary by omitting
  `section_max_characters`; a JSON null remains equivalent to omission for
  direct callers.
- For the eligible Qwen row, omission resolves to 280 before a job is queued
  and is stored only as `_resolved_section_max_characters` on the private job.
- Custom accepts type-exact integers 230–400. Boolean, float, string,
  non-finite, below-minimum, and above-maximum values remain rejected before
  queueing.
- 400 is the upper safe private section ceiling. A Custom 400 request is still
  valid; it does not change the Auto default.
- The retry budget is always `min(resolved_budget, 230)`, making Auto retry at
  230 and preventing a smaller Custom value from expanding during retry.
- Section choice affects only private sectioning and the matching per-section
  duration validation budget. It does not affect the 5,000-character whole
  request ceiling, reference preparation, final pitch-preserving speed pass,
  joining, output atomicity, cancellation boundaries, or public job payload.

## Architecture and data flow

The source of truth remains the selected, valid, hash-bound audit rather than
the frontend or catalog constant. The intended flow is:

```text
Generate UI / direct caller
  Auto: omit section_max_characters        Custom: send integer 230..400
                     \                         /
                      POST txt2speech endpoint
                                  |
               catalog.resolve_section_budget()
                                  |
     selected production-v2 audit + exact Qwen capability validation
                                  |
          _resolved_section_max_characters = 280 or Custom value
                                  |
        Qwen private chunking + duration validator + quality retry
                                  |
      retry uses min(resolved value, 230); joining remains 300/600/180
```

`long_form_policy.policy_for()` must derive both the maximum and the Auto
default from the selected audit. For v2, its resolved normal policy is 280 and
its ceiling is 400. It must not retain a Qwen family fallback that can silently
reintroduce 400 when the audit is absent, malformed, mismatched, or not the
selected v2 record.

`catalog.section_size_control_for()` continues to publish a control only when
the exact catalog entry and selected audit agree. Its v2 serialization is:

```json
{
  "minimum": 230,
  "maximum": 400,
  "step": 1,
  "default_custom": 280,
  "runtime_default": 280,
  "source": "qwen3-17b-production-v2-audit"
}
```

`runtime_default` means the selected audit's Auto/omitted resolution value,
not the maximum accepted Custom value. The UI may continue to seed Custom with
`default_custom: 280`; switching between Auto and Custom must preserve the
remembered Custom value per repository. Auto must continue to omit the field,
not send 280. This preserves the GenStudio contract: GenStudio submits its
complete script and continues to omit `section_max_characters`; it observes
the Voice Studio-owned 280 policy through the approved audit rather than a new
parameter or product setting.

## Production-v2 audit and compatibility

The existing file
`model-audits/2026-08-14-qwen3-17b-production/mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json`
is immutable production-v1 evidence. Do not edit, rename, regenerate, or
replace it. Its audit ID
`voicestudio-20260814-qwen3-tts-1.7b-base-production-v1` and hash
`sha256:c9be3368abdb8817369cc09a01231c8f1f5a7d68b936a0494920a918b3b8a38a`
remain historical evidence for its 400-default contract.

Add a separate v2 record at:

```text
model-audits/2026-08-15-qwen3-17b-production-v2/
  mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json
```

Its immutable identifier is
`voicestudio-20260815-qwen3-tts-1.7b-base-production-v2`. It uses the existing
`studio.model-audit-record` / `studio.model-audit` schema version 1, retains
the exact current subject, checkpoint/runtime revision
`e7dd0585652209fa0d7783659aad4e8a324de11c`, adapter, operation, languages,
5,000-character request ceiling, 400-character private ceiling, reference
contract, quality guardrails, hardware limits, capacity, and output contract.
Only the following contract addition changes the new canonical hash:

```json
{
  "input_limits": {
    "private_section_max_characters": 400,
    "default_private_section_max_characters": 280
  }
}
```

`default_private_section_max_characters` is required on v2 and must be an
integer no smaller than 230 and no larger than
`private_section_max_characters`. It means the normal Auto/omitted private
section budget. It is deliberately distinct from the existing maximum so the
audit can express both facts without weakening the 400-character safety limit.
The duplicated `genstudio_candidate.input_limits` must exactly equal the
contract's `input_limits`, and its `contract_hash` must be recomputed using
`model_audits.contract_hash(record["contract"])`; no literal hash is designed
in advance.

The v2 evidence must state all of the following explicitly:

- `supersedes_audit_id` is the immutable production-v1 ID;
- v1 remains retained, passed historical evidence and is not revoked;
- the 280 Auto default is owner-approved configuration, while 400 remains the
  audited safety maximum and 230 remains the retry safety value;
- the prior 300/600/180 pacing and no-trim/no-speech-crossfade frame-retention
  evidence remains applicable unchanged; and
- GenStudio approval must move from the exact v1 ID/hash to the exact v2
  ID/hash before it relies on the changed default.

The audit loader's current sorted-directory selection must select v2 as the
newest valid record for this model. It must reject a v2 file whose default is
missing, non-integer, outside 230–400, above its private maximum, duplicated
candidate limits differ from the contract, or hash does not match. Rejection
must leave the model without an editable Qwen capability rather than falling
back to v1/400 or an unverified hard-coded default. Historical-audit tooling
may still read v1 by its explicit path/ID for evidence, but runtime and catalog
resolution use only the selected valid record.

## Fail-closed behavior

The following failures must be safe and observable:

| Condition | Required behavior |
| --- | --- |
| No selected valid v2 audit | Do not publish `section_size_control`; reject non-null Qwen overrides as `SECTION_MAX_CHARACTERS_UNSUPPORTED`; do not silently resolve Auto to 400. |
| v2 hash or duplicate-contract mismatch | Treat the record as invalid; same no-capability/no-fallback behavior. |
| v2 default absent, malformed, <230, or >400 | Treat the record as invalid; no editable control and no unverified default. |
| Catalog capability disagrees with audit default or maximum | Serialize `section_size_control: null` and reject Custom overrides; no mixed 280/400 policy. |
| Auto/omitted request with valid v2 | Resolve once to 280 and record that private value before queueing. |
| Custom 230–400 with valid v2 | Resolve to exactly the requested integer, bounded by the 400 audit maximum. |
| Invalid or unsupported Custom request | Preserve the existing stable 422 codes: `SECTION_MAX_CHARACTERS_INVALID`, `SECTION_MAX_CHARACTERS_OUT_OF_RANGE`, or `SECTION_MAX_CHARACTERS_UNSUPPORTED`. |
| Internal caller bypass attempt | Re-resolve in `GenerationManager.start_txt2speech`; raw public input must never reach Qwen chunking or validation. |

No fail-closed state may substitute a model-family default, alter generation
parameters, or expose a generic editable field. It may make Qwen unavailable
for a section-size override until the audit/install issue is corrected.

## Verification

Implementation must add focused regressions before changing runtime behavior:

- Assert byte/content immutability of the v1 record and retain its known v1
  audit ID/hash/default interpretation as historical evidence.
- Assert v2 is selected, its candidate is hash-valid, its candidate projection
  exactly duplicates the contract fields, and the new default field is 280
  while its maximum is 400.
- Assert malformed/defaultless/out-of-range/mismatched v2 records are rejected
  and do not expose the catalog control or a 400 fallback.
- Assert catalog serialization exactly emits 230/400/1/280/280 with source
  `qwen3-17b-production-v2-audit`; every other model remains null.
- Assert omitted and null Qwen requests resolve to 280; Custom 230, 280, and
  400 resolve exactly; 229, 401, `True`, `280.0`, `"280"`, and an unsupported
  model preserve the established error codes.
- Assert endpoint and internal queue paths store only
  `_resolved_section_max_characters`; Auto never forwards a public default
  field; GenStudio-shaped omission resolves to 280.
- Assert normal Qwen chunking and duration validation consume 280 for Auto,
  while retry budgets are 230 for resolved 400, 280, and 230 values.
- Assert the 300/600/180 pause classifier, no-trim/no-crossfade frame
  retention, final output validation, and cancellation behavior are unchanged.
- Update frontend source/UI tests for visible wording of Auto 280, Custom
  230–400, request omission, remembered Custom value, invalid-submit blocking,
  keyboard/ARIA behavior, and no mobile overflow.

Then run the affected section-control, long-form-policy, Qwen-quality,
model-audit-contract, catalog, frontend-source, strict truth/audit, and
release-metadata tests; run the full suite, Python compile checks, JS/Bash
syntax checks, `python3 release_metadata_check.py`, and `git diff --check`.
The release must also include one desktop and 375 px rendered Generate-tab
check, with no generation needed for UI verification.

## Release and controlled rollout

Release the implementation as the next patch version after 2.2.0, with a top
`CHANGELOG.md` entry and README wording that accurately distinguish **Auto
280**, **Custom 230–400**, and the audited **400 maximum**. The changelog must
say that GenStudio still omits `section_max_characters` and now requires the
new v2 audit/hash approval. No dependency, install-generation marker,
launcher, media-tool, model-cache, or inference-runtime change is permitted.

After the release is committed and pushed, first run a no-generation
post-release canary on `voice@terranash-0201` only after health, idle,
model-free, zero-active-download, and no-active-maintenance preflight checks.
Verify the installed version/commit, v2 audit ID/hash/revision, catalog's
230/400/1/280/280 capability, Auto omission resolution to 280, valid Custom
230/280/400 behavior, and unchanged retry/pacing evidence. A reconnect during
service restart is not success unless the maintenance result becomes terminal
healthy and the postflight checks pass.

Only after that canary passes may Studio Hub perform a rolling rollout to one
eligible, idle worker at a time. Each worker requires the same preflight and
postflight checks, must be healthy and idle before advancing, and must stop the
rollout on any audit/hash/catalog/default mismatch, unhealthy watchdog,
unexpected restart, active-work conflict, or failed maintenance result. This
control-plane Mac remains development-only and is never a generation target.

## GenStudio handoff and closure

Send GenStudio a new handoff only after the single-worker canary has passed.
It must contain the release version and commit, exact Qwen repo/revision,
production-v2 audit ID, newly computed canonical hash, adapter version, and
the precise semantic change: GenStudio continues to omit the field, which now
means Auto 280; Custom remains a Voice Studio-local 230–400 control; 400 is
still the safety maximum; retry and pacing are unchanged. Request explicit
approval of the v2 ID/hash before GenStudio updates its stored approval.

GenStudio must not treat the v1 approval/hash as approval for v2. Its existing
route, product identifier, price, language gates, independent auto-canary, and
OmniVoice backup remain unchanged. The handoff is closed only when GenStudio
acknowledges the exact v2 audit/hash and its approval state reflects that pair;
if it declines or cannot validate the pair, retain the prior approved contract
and do not claim v2 route approval.

## Deliberate non-goals

This design does not change Custom's upper bound to 280, raise the 5,000
character request ceiling, expose pacing controls, modify customer-facing
GenStudio settings, approve a new model/route, alter pricing/language policy,
download assets, or perform a broad fleet update by itself.
