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
