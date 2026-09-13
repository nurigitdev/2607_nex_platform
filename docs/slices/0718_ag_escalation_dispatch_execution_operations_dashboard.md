# Slice 0718: AG escalation dispatch execution operations dashboard

## Intent

Expose safe dispatch execution-result evidence in the AG operations dashboard so
operators can see recent execution outcomes without opening raw provider data.

## Implementation

- Added execution-result dashboard projection helpers in
  `nex_ag.operations`.
- Added `operator_review_escalation_dispatches.execution_summary` with counts by
  execution status, retryable count, latest execution timestamp, and redaction
  flags.
- Added `summary.execution_*_count` fields for compact dashboard rollups.
- Added item-level `execution_result` projections for dispatch `attention` and
  `recent` entries when `metadata.last_execution_result` is present.
- Updated the AG operations projection contract schema to allow the new
  dashboard section field.

## Boundary

Slice 0718 is read-model/dashboard integration only. It does not add a new table,
does not mutate dispatch rows, and does not expose raw provider payloads,
provider errors, secrets, tokens, or idempotency keys.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_operator_review_dispatch_execution.py -q
```
