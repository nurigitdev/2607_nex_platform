# Slice 0816: AG dispatch liveness acknowledgement expiry operations overlay

## Objective

Expose S82 reconciliation readiness in existing recovery, dashboard, and issue
candidate read models without mutating acknowledgement or heartbeat state.

## Changes

- Added reconciliation statuses `PENDING`, `RECONCILED`, `NOT_DUE`, and safe
  source fallback states to the acknowledgement overlay.
- Marked stored `SUPPRESSED` plus effective `EXPIRED` as pending reconciliation.
- Propagated the bounded manual reconciliation path into dashboard and issue
  candidate signals.
- Preserved the source liveness projection and kept every overlay read-only.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_operations_overlay.py tests/test_nex_ag_operations.py -q --tb=short
```

Result: `212 passed, 1 warning`.

Full regression result: `5385 passed, 1 warning`.

- Statement coverage: `68937 / 69820 = 98.735319392724%`.
- Branch coverage: `16373 / 17024 = 96.175986842105%`.
