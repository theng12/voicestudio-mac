# IndexTTS 2.5 MLX Qualification Design

## Goal

Determine whether `vanch007/mlx-indextts2-2.5-8bit` is safe and useful on the
8 GB M1/M2 Voice Studio tier without changing the production catalog or fleet.
Keep FP16 and FP32 locally as comparison candidates, but do not assume that
small checkpoint files imply a small runtime footprint.

## Decisions

- Download all three immutable model revisions on the current Mac.
- Run the first real generation on the current 16 GB Mac in an isolated
  upstream environment. Do not modify Voice Studio's pinned generation stack.
- Test 8-bit first. FP16 is a quality comparison only after the 8-bit baseline;
  FP32 is retained locally and tested only if FP16 shows a meaningful benefit.
- Precompute the Aiden speaker cache on the 16 GB Mac. Later 8 GB tests use that
  cache so W2V-BERT and CampPlus do not share memory with synthesis.
- Keep automatic Qwen emotion disabled during 8 GB testing. Manual emotion
  vectors and a separate emotion reference exercise the model's native control
  without loading another language model.
- Keep the candidate outside GenStudio, Studio Hub routing, SSD automatic
  staging, and the production Voice Studio catalog until qualification passes.

## Immutable inputs

| Variant | Repository revision | Published bytes |
| --- | --- | ---: |
| 8-bit | `3170ceff8032ab6d0c2945e72068a03ea8c68461` | 1,716,631,394 |
| FP16 | `fdc0f897f1f9fe61a8280f1bb085d0abaa5b63d3` | 2,158,980,528 |
| FP32 | `4ab4cf99018bc394e1345f102c60c93e18a34bc8` | 4,316,411,730 |

The runtime source is pinned to
`vanch007/mlx-indextts2@a7666367b8551656a2029ad75f259cb5e4936b3b`.

## Data flow

1. Hugging Face assets download into Voice Studio's ignored candidate cache.
2. An isolated upstream runtime creates a revision-bound Aiden `.npz` speaker
   cache from the existing authorized reference voice.
3. The 16 GB baseline renders short neutral, calm, and expressive samples,
   followed by the existing 3,033-character sustained narration.
4. Resource sampling records host memory pressure, minimum available RAM, swap
   delta, process RSS, MLX peak, wall time, audio duration, and unload recovery.
5. If the baseline passes, the owner later copies the 8-bit model and speaker
   cache to one 8 GB machine at a time for isolated M2 and M1 runs.

## Qualification gates

An 8 GB run is ineligible if any test:

- reaches urgent or critical memory pressure;
- leaves less than 1.0 GB available;
- adds more than 0.5 GB of swap;
- triggers a memory failure or service restart;
- publishes partial, non-finite, clipped, or structurally invalid audio;
- omits/reorders requested words or adds uncontrolled terminal speech; or
- fails to release model memory after the job.

Quality requires owner listening. Automated transcription and waveform checks
are supporting evidence, not the final decision.

## License boundary

The runtime code is MIT, but the weights and converted derivatives use the
bilibili Model Use License Agreement. Candidate downloads retain the included
license. No commercial route is enabled until the owner explicitly accepts the
license's commercial thresholds, notice obligations, downstream terms, and its
definition of outputs as derivative works.

## Rollback and isolation

No production code, dependency, service, model catalog, or fleet registration
changes during qualification. Removing the ignored candidate directory and
qualification workspace fully removes the experiment without affecting models,
voices, jobs, or settings.
