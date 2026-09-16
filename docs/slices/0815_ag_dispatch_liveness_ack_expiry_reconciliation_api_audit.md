# Slice 0815: AG dispatch liveness acknowledgement expiry reconciliation API and audit

## Objective

Expose the S82 one-cycle worker through a protected operator route and emit a
safe operational audit summary for every admitted execution or failure.

## Changes

- Added protected `POST /admin/v1/operator-review/dispatch-daemon/liveness/ack-states/reconcile-expired`.
- Accepted only bounded `observed_at` and `limit` execution inputs.
- Emitted distinct reconciled, rejected, and failed operational event types.
- Limited audit details to run status and aggregate counts; per-state outcomes,
  raw comments, idempotency keys, payloads, and database URLs are excluded.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_api.py tests/test_nex_ag_liveness_ack_expiry_reconciliation.py -q --tb=short
```

Targeted API/worker regression: `9 passed`; related AG operations bundle:
`238 passed`.

Full regression result: `5381 passed, 1 warning`.

- Statement coverage: `68920 / 69803 = 98.735011389195%`.
- Branch coverage: `16367 / 17018 = 96.174638617934%`.
