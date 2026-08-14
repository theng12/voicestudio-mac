# Qwen3-TTS 1.7B GenStudio Candidate Design

## Decision

`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` has a prepared Voice Studio
2.1.3 **passed production-candidate audit**, grounded in the exact installed
2.1.2 canary evidence and owner review. It is not live or GenStudio-routable
until the 2.1.3 post-release canary verifies the running audit and managed media
tools, followed by separate GenStudio approval and its independent auto-canary.
OmniVoice remains installed, catalogued, and available as an operator-selected
backup; Voice Studio does not delete it or automatically retry an accepted Qwen
request through it.

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

The immutable Voice Studio 2.1.2 conditional bootstrap audit remains
superseded evidence: it records the 288-character runtime default and its
40,000-character API acceptance field, not a qualified request ceiling. The
separate 2.1.3 passed audit records the evidence-supported 5,000-character
request maximum and 400-character private section maximum. Both records bind
the same immutable checkpoint/runtime, 3/8/8–12/15-second 24 kHz mono reference
profile with the exact transcript, and the existing private 300/600/180
lossless assembly policy; no runtime inference behavior changes in 2.1.3.

The owner-approved boundary pacing is shared with the replaced production
route:

- 300 ms after a sentence;
- 600 ms across a paragraph boundary;
- 180 ms after an internal soft split.

Every generated frame is retained. The Qwen assembly path performs no
energy-based trimming, speech crossfade, or other destructive edge cleanup.

## Qualification and Promotion

The prepared passed audit records the exact checkpoint revision, adapter
version, contract hash, 16 GB memory/runtime evidence, section sweep,
5,000-character whole-request evidence, owner listening approval, reference
window, pacing, and word-safe assembly rule. The 10,000-character negative
boundary, 25,000-character fixtures, and malformed fixtures remain rejected or
informative evidence, never promotion evidence. Its published status does not
itself approve a route: Studio Hub remains the approval and supply authority
until the 2.1.3 canary passes. GenStudio's own approval then triggers its
independent fixed-text auto-canary; Voice Studio does not bypass or duplicate it.

### Release state — 2.1.3 prepared, rollout pending

The 2.1.3 release is prepared but not deployed. Its FFmpeg repair hop relies
on a worker already at 2.1.2 loading that current `update.js`, which installs
and verifies FFmpeg/FFprobe while the worker moves to 2.1.3. A 2.0.7 worker
must take the explicit pinned sequence `2.0.7 -> 2.1.2 -> 2.1.3`; direct legacy
updates do not execute the newer provision step. Do not claim either FFmpeg or
the final audit live until the post-release canary verifies them.

## Compatibility

No customer product ID, price, voice identity, or prior job evidence changes.
Saved reference voices remain reusable because Qwen prepares the existing local
source plus exact transcript into the same bounded execution copy and hash
evidence used for private uploads. OmniVoice and the other installed models
remain untouched as non-primary backups.
