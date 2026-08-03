# Wave 1 qualification drafts

`tools/wave1_qualification.py plan` creates offline-only draft evidence for
the three Wave 1 models. It records the fixed candidate, voice/language,
machine, corpus, reference, and case matrix; it does not contact Voice Studio,
providers, or models.

```bash
python3 tools/wave1_qualification.py plan --run-id wave1-example --run-dir model-audits/wave1/wave1-example
python3 tools/wave1_qualification.py validate --run-dir model-audits/wave1/wave1-example
```

Only a later public-API executor may submit controlled jobs through Voice
Studio's public local endpoints and append public job, telemetry, and output
evidence. That executor must preserve `candidate_status: not_audit`; audit
promotion is a separate explicit review authority and is not implemented here.

## Human-listening archive

Every terminal qualification job that produced an audio artifact must also be
exported to an operator-controlled review directory outside this repository.
This includes plausible outputs, known-bad quality evidence, corrective reruns,
and long-form outputs. An intentional cancellation may have no artifact.

The executor must:

1. group recordings by run, model, capability, voice or language, machine tier,
   and attempt identity;
2. verify the downloaded byte count and SHA-256 value against the worker's
   terminal evidence before giving the recording its final filename;
3. retain the worker-owned original and never treat the review copy as the
   authoritative execution artifact;
4. leave incomplete transfers visibly partial rather than presenting them as
   listenable evidence; and
5. report the expected, downloaded, verified, missing, and intentionally absent
   artifact counts before handing the run to a human reviewer.

Every listening archive must also include a human-readable performance report
and machine-readable evidence. For each test, record when available:

- model, operation, voice or language, machine identity, and memory tier;
- submitted character count and adapter chunk count;
- wall-clock generation time and produced-audio duration;
- real-time factor (`generation seconds / audio seconds`) and its inverse,
  audio produced per generation second;
- sample rate, output size, peak observed model memory, minimum available host
  memory, swap, memory pressure, and memory-failure outcome; and
- qualification warnings, cancellation state, and the matching listening-file
  identity.

The report must explain that lower real-time factor is faster, separate short
request overhead from long-form throughput, and never treat speed as a substitute
for transcript integrity or human quality review. It must include per-model
aggregates plus a direct long-form comparison. Missing telemetry stays explicitly
unknown; it must not be estimated or silently filled.

Do not commit customer reference audio, generated review audio, credentials,
private worker addresses, or absolute operator paths. The audit draft stores
only safe machine-readable evidence; the listening archive is private review
material.
