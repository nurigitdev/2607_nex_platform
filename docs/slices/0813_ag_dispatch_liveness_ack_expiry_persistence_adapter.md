# Slice 0813: AG dispatch liveness acknowledgement expiry persistence adapter

## Objective

Add bounded expiry-candidate reads and compare-and-set persistence without
opening an API or starting an execution loop.

## Changes

- Extended memory and SQLAlchemy acknowledgement-state stores with bounded
  candidate selection ordered by suppression deadline.
- Added CAS expiry persistence guarded by state id, `SUPPRESSED` status,
  expected `updated_at`, deadline presence, and elapsed deadline.
- Added `idx_ag_ack_state_expiry` on the existing table; no new table was
  introduced.
- Preserved renewed suppression or operator-cleared state when a stale worker
  attempts to write.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack_expiry.py tests/test_nex_ag_operator_review_liveness_ack.py -q --tb=short
```

Related persistence and migration regression: `48 passed`.

Full regression result: `5372 passed, 1 warning`.

- Statement coverage: `68857 / 69740 = 98.733868655004%`.
- Branch coverage: `16357 / 17008 = 96.172389463782%`.
