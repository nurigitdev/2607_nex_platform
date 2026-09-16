# Slice 0814: AG dispatch liveness acknowledgement expiry reconciliation worker

## Objective

Execute one bounded reconciliation cycle through the S82 contract and
persistence adapter without introducing scheduling or API concerns.

## Changes

- Added a dedicated one-cycle worker that reads a bounded candidate batch,
  revalidates every candidate, builds the pure expiry transition, and applies
  it through compare-and-set persistence.
- Added safe `APPLIED`, `CONFLICT`, and `SKIPPED` outcomes with aggregate counts.
- Made repeated execution idempotent: persisted `EXPIRED` rows are not selected
  again.
- Kept raw comments, payloads, process control, source heartbeat mutation, and
  scheduling outside the worker boundary.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_reconciliation.py tests/test_nex_ag_operator_review_liveness_ack_expiry.py -q --tb=short
```

Related worker/state regression: `34 passed`; changed modules statement/branch
coverage `100%`.

Full regression result: `5376 passed, 1 warning`.

- Statement coverage: `68881 / 69764 = 98.734304225675%`.
- Branch coverage: `16361 / 17012 = 96.173289442746%`.
