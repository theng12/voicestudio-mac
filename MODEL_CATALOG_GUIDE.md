# Voice Studio Model Catalog Guide

The Models tab is family-first. A **family** explains the voice technology and
shared workflow; a **model entry** is one downloadable option within that
family, such as 4-bit, 8-bit, full precision, Base, CustomVoice, or VoiceDesign.

## Taxonomy

- `family`: Stable engine/product identity, for example `qwen3-tts` or `kokoro-mlx`.
- `capabilities`: User outcomes. Use existing values where possible: `tts`,
  `voice-cloning`, `multilingual`, `expressive`, and `streaming`.
- `apple_optimized`: Derived in `serialize_model()`. Keep `_MLX_AUDIO_FAMILIES`
  synchronized with the generation worker registry.
- `min_unified_memory_gb`: Realistic runtime floor, not just model file size.
- `size_gb`: Decimal download size after `ignore_patterns` are applied.
- `label`: Family name plus a concise option name. Include precision when it
  matters and use `recommended` only for the preferred option in a family.

## Add A New Family

1. Add one `Family` to `app/backend/catalog.py` with a stable id, plain-language
   summary, usage guidance, and accurate `TextGuidance`.
2. Add one or more `ModelEntry` rows using that family id.
3. Wire the family in `app/backend/generation.py` and its diagnostics registry.
4. If it uses mlx-audio, add the id to `_MLX_AUDIO_FAMILIES` in
   `serialize_model()` and the matching generation registry.
5. Add dependency requirements to `app/requirements-generation.txt` when needed.

## Add An Option To A Family

Add one `ModelEntry`; no frontend edit is required. The Models tab automatically
places it below its family and derives runtime, precision, fit, status, and
download actions from catalog fields.

Use `ignore_patterns` when a Hugging Face repository contains unused checkpoints.
Keep `best_for` short and decisive. Put concrete strengths and limitations in
`use_cases` using `good`, `weak`, or `avoid`.

## Verification

1. Run `python -m compileall -q app/backend`.
2. Run the server and inspect `GET /api/catalog`.
3. Confirm the family count, option label, decimal size, capabilities, cache
   state, and hardware fit.
4. Open `#/models`: verify default view shows the full catalog, the family opens,
   Download works, cached models show Use model, and Details explains tradeoffs.
5. Test at desktop and mobile widths and run `git diff --check`.

Never add a frontend-only model list. `app/backend/catalog.py` is the single
source of truth.

## Add A Transcription Model

Transcription models use the separate `TRANSCRIPTION_MODELS` registry in
`app/backend/transcription.py`; the frontend consumes that registry through
`GET /api/transcribe/availability`. Record the engine, decimal download size,
language scope, minimum unified-memory candidate, timing support, long-form
support, and whether it is an internal candidate. Do not invent a
`genstudio_candidate` record: that evidence appears only after a real model
audit exists.

New engines must dispatch through the existing `TranscriptionManager`, Hugging
Face cache, download manager, and global generation lock. Normalize their output
into the existing text/segments/SRT/VTT response rather than adding a second
transcription API. Whisper processor companions belong only to Whisper rows.

For internal candidates, verify selection and capability truth in the operator
UI at desktop and mobile widths. Appearance in Voice Studio is not fleet
qualification or GenStudio publication; those remain separate decisions.
