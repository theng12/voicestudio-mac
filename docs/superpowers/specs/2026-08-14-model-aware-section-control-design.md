# Model-Aware Long-Form Section Control Design

## Decision

Add one model-aware **Long-form delivery** control to the Generate tab. The
control is a collapsed block immediately after Speed and is rendered only when
the selected catalog row declares the exact, verified capability for
`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`. It offers:

- **Auto** (the default): Voice Studio sends no `section_max_characters` field;
  the audited model policy remains authoritative. The current audited default
  is 400 characters.
- **Custom**: an integer section size from 230 through 400 inclusive, including
  280. The selected value is sent as `section_max_characters`.

The UI stores the mode and custom value per repository. Selecting **Reset to
Auto** changes only the persisted mode; the last custom value remains available
if the user switches back to Custom. Unsupported models hide the block and the
server rejects any non-null override for them.

The existing 300 ms sentence, 600 ms paragraph, and 180 ms soft pauses remain
automatic. They are not exposed as controls and are not changed by this
feature.

## Existing evidence and boundary

Voice Studio currently publishes `long_form_delivery` from
`app/backend/long_form_policy.py` through `app/backend/catalog.py`. The exact
Qwen 1.7B Base production audit at
`model-audits/2026-08-14-qwen3-17b-production/mlx-community--Qwen3-TTS-12Hz-1.7B-Base-8bit.audit.json`
records a 400-character private section maximum, the 300/600/180 ms assembly,
and one retry at 230 characters. The runtime already resolves the audited
section budget before private chunking, while the request schema still labels
`section_max_characters` as a general qualification-only override. This design
turns that existing field into a deliberately narrow, catalog-gated local
control.

The normal GenStudio request contract is unchanged. GenStudio continues to
submit a complete script and omit `section_max_characters`; Voice Studio owns
private sectioning, joins, validation, and the final pitch-preserving speed
pass. No GenStudio integration module, product identifier, price, voice
identity, or Hub route changes.

## Catalog capability

Add an optional exact-model capability to `catalog.ModelEntry` and publish it
inside the existing `long_form_delivery` object:

```json
{
  "section_size_control": {
    "minimum": 230,
    "maximum": 400,
    "step": 1,
    "default_custom": 280,
    "runtime_default": 400,
    "source": "qwen3-17b-production-audit"
  }
}
```

Only the exact Qwen 1.7B Base repository receives this object. Other catalog
rows serialize `section_size_control: null` and do not imply that their
runtime defaults are user-editable. `catalog.section_size_control_for(repo)`
returns the capability or `None` for backend validation.

Serialization must fail closed if the model's resolved audited policy does not
equal the capability's `runtime_default`; in that case the UI receives no
editable capability. This prevents a stale catalog declaration from exposing
a value that the current audit does not support.

## Backend resolution and request contract

Keep `Txt2SpeechBody.section_max_characters` optional, but remove the current
generic 40–20,000 range as the source of truth. The shared resolver owns the
model-aware rules:

```python
resolve_section_budget(
    family: str,
    repo: str,
    requested: object,
    capability: dict | None,
) -> dict
```

The return value contains the resolved integer budget, its source (`"audit"`
or `"caller_override"`), and the capability used for the decision. A null or
omitted request resolves to the model-owned audited policy. A non-null request
is accepted only when:

1. the exact catalog capability exists;
2. the request is an integer;
3. it is within the explicit 230–400 inclusive capability range; and
4. it does not exceed the resolved audited runtime default.

The fourth rule is the tightening-only guard. It prevents a caller from
expanding a model's audited budget even if a future catalog range is broader.
The resolver must also reject a capability whose declared `runtime_default`
disagrees with the resolved audited policy rather than silently choosing one.

Use stable error codes in a 422 response for HTTP requests:

- `SECTION_MAX_CHARACTERS_UNSUPPORTED` for a non-null override on any model
  without the exact capability;
- `SECTION_MAX_CHARACTERS_INVALID` for a non-integer or non-finite value; and
- `SECTION_MAX_CHARACTERS_OUT_OF_RANGE` for a value outside 230–400 or above
  the resolved audited default.

Validate in both `POST /api/generate/txt2speech` and
`POST /api/generate/txt2speech/reference`, before queueing a job. Re-resolve in
`GenerationManager.start_txt2speech` as a defense for internal callers. Store
the result in the job's private `_resolved_section_max_characters` field; do
not turn it into a public request field or send it to GenStudio.

When Auto is selected, the browser must omit `section_max_characters` entirely
from the JSON body. A body containing `section_max_characters: null` is treated
as omitted by the backend for compatibility with direct API callers.

## Generation, validation, and retry

Use `_resolved_section_max_characters` for private Qwen chunking instead of
reading an unrestricted caller field. Keep the 300/600/180 boundary classifier
and pause sequence unchanged and independent from section size.

The Qwen duration validator must calculate its budget from the resolved caller
section size. A custom 280 request therefore validates the 280-character
sections, while Auto validates the audited 400-character sections. It must not
fall back to the old family constant or to an unvalidated raw request field.

On the existing single quality retry, use:

```python
retry_budget = min(resolved_budget, qwen_quality.RETRY_SECTION_MAX_CHARACTERS)
```

With the current retry constant this is `min(resolved, 230)`. A smaller caller
request is never expanded by retry, and Auto still retries at 230. The retry
budget must update both chunking and the duration validator for that attempt.

The final output remains atomic. No pause controls, reference-audio behavior,
model loading, memory policy, speed processing, or normal GenStudio path is
changed.

## WebUI behavior and accessibility

The new block uses incumbent control styles and no dependency:

```html
<details class="control-block" x-show="sectionSizeControlSupported" x-cloak>
  <summary>Long-form delivery</summary>
  <div class="advanced-inner">
    <fieldset>
      <legend>Section size</legend>
      <!-- Auto / Custom choices and the numeric Custom field -->
    </fieldset>
  </div>
</details>
```

The fieldset has a visible legend, the numeric input has an explicit label,
`min="230"`, `max="400"`, `step="1"`, `aria-invalid`, and
`aria-describedby`. Validation text is in an `aria-live="polite"` region. The
Generate button remains disabled while the Custom value is empty, non-integer,
outside the range, or greater than the model's resolved runtime default. The
Reset to Auto action is keyboard reachable and restores a valid submit state.

The state fields are `gen.section_size_mode` (`"auto"` or `"custom"`) and
`gen.section_max_characters` (the remembered integer value). Add both to
`_GEN_PRESET_FIELDS`, so the existing per-repository localStorage map persists
them without a second storage format. The request builder conditionally adds
`section_max_characters` only for a supported model in Custom mode.

Use a single-column `.section-size-grid` at the existing mobile breakpoint;
desktop may use the incumbent compact two-column control layout. Do not make
the fixed pause values editable or add a second advanced-control system.

## Verification and release

Backend tests cover catalog capability publication, Auto resolution, accepted
230/280/400 values, unsupported-model rejection, out-of-range rejection,
tightening-only rejection, audit/capability mismatch fail-closed behavior,
resolved duration budgets, and retry budgets of 230/230/230 for resolved
budgets 400/280/230. Frontend source tests cover conditional visibility,
per-repository persistence, Auto omission, Custom request inclusion, invalid
submit blocking, fieldset/legend/labels/ARIA, and mobile single-column CSS.

Run focused tests first, then the full pytest suite, Python compile checks,
launcher syntax checks, strict truth/audit checks, release metadata validation,
and `git diff --check`. Perform a visual Generate-tab check at desktop and
mobile widths: the block is collapsed after Speed, appears only for exact Qwen
1.7B Base, invalid input announces an error and disables Generate, and Auto
restores the default request shape.

Release metadata is Voice Studio **2.2.0** with a changelog entry and README
documentation describing the exact model scope, Auto behavior, Custom range,
automatic pauses, and direct API omission/inclusion rules. No dependency or
system change is permitted. Commit the scoped implementation and release
metadata, push `origin main`, then run one post-release canary on worker
`0201` only after its health/idle preflight passes. The canary verifies the
installed version, catalog capability, UI behavior, and API Auto/Custom
request shapes; it performs no generation and does not involve any other
worker. Broader rollout remains out of scope.
