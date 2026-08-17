# Internal Moonshine and Nemotron ASR Pilot Design

## Outcome

Voice Studio adds two operator-only transcription choices for local evaluation
on Apple Silicon:

- Moonshine Base for lightweight English short-form transcription.
- Nemotron 3.5 ASR Streaming 0.6B 8-bit for multilingual long-form
  transcription with timed output.

Whisper large-v3 turbo remains the default. Qwen output and reference quality
checks continue to use that unchanged default. Neither new model is exposed to
GenStudio or approved for customer routing.

## Evidence and 8 GB Decision

### Moonshine Base

- Repository: `moonshine-ai/moonshine-base`
- Observed upstream revision during design:
  `7a73d8d55ac0ba2ef3ae761593f6784b51f96dcf`
- Model size: 246,079,928-byte weights; about 248 MB including configuration
  and tokenizer.
- Architecture: 58 million parameters, English, MIT licensed.
- Apple path: the existing `mlx-audio==0.4.7` dependency contains a Moonshine
  loader, so the pilot requires no new Python or native dependency.
- Hardware classification: 8 GB candidate. Its weight size is comfortably
  below the existing 8 GB Whisper options, but the label is evidence-based
  eligibility rather than a claim of completed fleet qualification.

The current MLX Moonshine adapter returns text but no meaningful segment or
word timestamps. Voice Studio therefore treats it as short-form and
transcript-first. It may publish one honest segment spanning the known input
duration so existing text/SRT/VTT response shapes remain stable, but it must
not claim word-level timing or long-form subtitle quality.

### Nemotron 3.5 ASR Streaming 0.6B 8-bit

- Repository: `mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit`
- Observed upstream revision during design:
  `7279359e4481b5e9e185a318bd618e429c6d86cd`
- Model size: 755,598,923-byte weights; about 756 MB including configuration,
  tokenizer, and vocabulary.
- Architecture: cache-aware streaming FastConformer-RNNT, about 0.6B
  parameters before quantization, multilingual prompt dictionary.
- Apple path: the installed `mlx-audio==0.4.7` dependency already contains the
  MLX Nemotron loader, chunked inference, and aligned sentence/token output.
- Hardware classification: 8 GB candidate, explicitly unqualified until a
  later owner-run worker benchmark records peak unified-memory evidence.

Nemotron produces aligned sentence and token objects. Voice Studio converts
them into its existing segment and optional word timing response without
changing the public `/api/transcribe` response schema.

## Architecture

### Model registry

Rename the Whisper-only registry concept to a transcription-model registry.
Each entry carries only the fields runtime and UI need:

- repository, label, size, and explanatory note;
- engine: `whisper`, `moonshine`, or `nemotron`;
- minimum unified memory;
- language summary;
- whether segment timing, word timing, and long-form input are supported;
- `internal_candidate`, true only for Moonshine and Nemotron;
- `recommended`, which remains true only for Whisper large-v3 turbo.

The backend may retain a compatibility alias for `WHISPER_MODELS` only if an
existing internal consumer still needs the exact Whisper subset. No duplicate
model list may be introduced.

### Loading and inference

The existing transcription manager remains the single owner of the loaded ASR
model and the shared generation lock. It continues to:

- require a complete local Hugging Face snapshot before loading;
- pass an explicit snapshot path to `mlx-audio`;
- evict the previous transcription model before switching;
- serialize transcription against local TTS generation;
- record existing resource telemetry and release Metal activation buffers.

Inference dispatch is deliberately small:

- Whisper keeps its current decode policy, tokenizer attachment, timestamps,
  and normalization.
- Moonshine receives only arguments supported by its MLX adapter. A non-empty
  transcript becomes one segment from zero to the measured audio duration.
  `word_timestamps=true` fails clearly before inference rather than silently
  returning invented precision.
- Nemotron receives its language prompt and bounded chunked inference. Its
  aligned sentences become Voice Studio segments; its aligned tokens become
  words only when requested.

Unknown models, incomplete caches, unsupported timing requests, and malformed
runtime results fail closed with actionable errors. A failed model load or
inference evicts the loaded model exactly as it does today.

## Operator UI and API

The Models and Subtitles surfaces use generic “Transcription” wording rather
than describing every option as Whisper. Each model exposes concise chips or
copy for:

- engine/family;
- languages;
- `8 GB candidate`;
- internal/experimental status;
- timed subtitles, word timestamps, and long-form support.

Selecting Moonshine disables the word-timestamp control and explains its
short-form transcript limitation. The run button remains available for a
downloaded Moonshine model when word timing is off. Nemotron behaves like a
timed subtitle model.

`GET /api/transcribe/availability` remains additive: existing fields keep
their meanings and model rows gain the capability fields above. `POST
/api/transcribe` keeps the same request and response shape.

## GenStudio and Fleet Boundary

- Do not create a model-audit record for either pilot model.
- Do not emit `genstudio_candidate` for either model.
- Do not change Studio Hub or GenStudio source, contracts, routes, catalogs,
  pricing, or handoffs.
- Do not download either model, run transcription qualification, restart a
  service, or update a fleet machine from this development task.
- A later owner-run update and benchmark may qualify or reject each candidate
  independently. Until then, both labels remain internal and experimental.

## Storage and Downloads

Both selected variants are ordinary Hugging Face repositories. They reuse
Voice Studio's existing resumable download manager, immutable snapshot cache,
storage inventory, safe-removal rules, and progress UI. No separate Moonshine
cache, downloader, native service, or new dependency is introduced.

Storage grouping changes from a Whisper-only family description to a generic
transcription family while preserving the tokenizer dependency relationship
for Whisper models.

## Release and Verification

This is a new model-family/runtime feature and ships as Voice Studio `2.4.0`.
VERSION, CHANGELOG, README, and installed What's New evidence must state:

- the exact internal pilot scope;
- 8 GB is a candidate classification, not fleet qualification;
- Whisper remains default;
- Moonshine's timing/short-form limitation;
- no GenStudio exposure, model download, or fleet rollout occurred.

Implementation follows TDD. Focused coverage must prove registry truth,
availability capability fields, explicit-path loading, engine-specific
arguments, Moonshine timing refusal/fallback, Nemotron aligned-result
normalization, default Whisper preservation, storage grouping, and frontend
capability behavior. Final verification includes release metadata, the full app
test suite, compile/import checks, inline JavaScript syntax, dependency health,
and diff checks. Rendered desktop and narrow-width QA uses an offline fixture
only and must confirm capability copy, disabled word timing, focus, and no
overflow.
