# Slice 1098: AE MVP Operations Handoff

## Goal

Create an immutable, privacy-safe NeX-AE-to-NeX-AG operations handoff without
moving AE records or giving AG direct access to the AE database.

## Two-Stage Handoff

1. Build and verify a `SEALED` manifest containing relative asset paths,
   SHA-256 hashes, the protected read-model route, ownership boundaries,
   operator entrypoints, dependencies, and deferred risks.
2. Bind the verified manifest hash to an `ACCEPTED` and
   `READY_FOR_OPERATIONS` report, producing a hashed `BOUND` attestation.

Any missing asset, modified hash, wrong service identity, blocked acceptance,
invalid acceptance ID, or naive timestamp fails closed.

## Operations Boundary

- AE retains workspace, chat, generated-response, artifact, scheduler, worker,
  job, and log records.
- AG reads only redacted protected AE operations projections and never queries
  `nex_ae_test` or a production AE database directly.
- The handoff contains no prompt, response, source document, artifact bytes,
  database URL, credential, provider endpoint/key, or local absolute path.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ae_mvp_operations_handoff.py \
  --cov=nex_ae_api.mvp_operations_handoff \
  --cov-branch --cov-report=term-missing
```

No table or migration is added.
