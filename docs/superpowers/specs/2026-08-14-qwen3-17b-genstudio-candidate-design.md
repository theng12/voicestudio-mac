# Qwen3-TTS 1.7B GenStudio Candidate Design

## Decision

`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` is a Voice Studio candidate for
GenStudio Multilingual V3, not a passed or routable candidate yet. Its audit
must stay red until remote qualification provides measured limits, reference
evidence, and owner approval. OmniVoice remains installed, catalogued, and
available as an operator-selected backup; Voice Studio does not delete it or
automatically retry an accepted Qwen request through it.

The execution boundary remains GenStudio -> Studio Hub -> Voice Studio. Studio
Hub owns eligible-worker selection and must require authoritative unified-memory
evidence. Qwen 1.7B is eligible on 16 GB and larger Apple Silicon machines, with
24 GB preferred; 8 GB machines remain ineligible.

## Exact Candidate

- Runtime repository: `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`
- Immutable revision: `e7dd0585652209fa0d7783659aad4e8a324de11c`
- Operation: `voice.tts`
- Output: atomic mono 24 kHz PCM16 WAV
- Capacity: one generation per worker
- Clone input: reference audio plus its exact transcript; no x-vector-only fallback
- Languages: Chinese, English, Japanese, Korean, German, French, Russian,
  Portuguese, Spanish, Italian. Arabic is not supported.

## Long-form Contract

Callers submit one complete script. Voice Studio performs sentence-safe private
sectioning, reuses the same reference audio and transcript for every section,
reports progress, honors cancellation between sections, joins the sections, and
applies final pitch-preserving speed once.

Voice Studio 2.1.2 publishes a hash-bound **conditional** bootstrap audit so
the 1.7B runtime can prepare the bounded reference input needed for exactly one
eligible canary. The record exposes only code-grounded execution facts: the
immutable checkpoint and runtime, 3/8/8–12/15-second 24 kHz mono reference
profile with the exact transcript, the existing 288-character runtime-default
section budget, and the private 300/600/180 lossless assembly policy. Its
40,000-character API acceptance field is not a qualified model ceiling; no
final whole-request ceiling, listening score, commercial approval, or passed
canary result is claimed. A qualification-only `section_max_characters`
override permits a transcribe-back sweep without changing the bootstrap
contract before evidence is accepted.

The owner-approved boundary pacing is shared with the replaced production
route:

- 300 ms after a sentence;
- 600 ms across a paragraph boundary;
- 180 ms after an internal soft split.

Every generated frame is retained. The Qwen assembly path performs no
energy-based trimming, speech crossfade, or other destructive edge cleanup.

## Qualification and Promotion

A future passed hash-bound audit must record the exact checkpoint revision,
adapter version, contract hash, measured 16 GB memory/runtime evidence,
section sweep, whole-request evidence, owner listening approval, reference
window, pacing, and word-safe assembly rule. Until then, Voice Studio exposes
only the conditional, `candidate_for_genstudio: false` bootstrap summary;
Studio Hub keeps it blocked and remains the approval and supply authority.

GenStudio's own approval triggers its independent fixed-text auto-canary. Voice
Studio does not bypass or duplicate that canary.

## Compatibility

No customer product ID, price, voice identity, or prior job evidence changes.
Saved reference voices remain reusable because Qwen prepares the existing local
source plus exact transcript into the same bounded execution copy and hash
evidence used for private uploads. OmniVoice and the other installed models
remain untouched as non-primary backups.
