# Slice 0716: AG escalation dispatch execution worker run-once batch

## Intent

Introduce the first bounded run-once worker for AG-owned escalation dispatch
execution.

## Implementation

- Added
  `ag_operator_review_escalation_dispatch_execution_worker_run.v1`.
- Added `run_dispatch_execution_worker_once(...)`.
- The worker requires explicit `confirm_run=True`.
- The worker reads eligible `PENDING`, `RETRY_WAIT`, and `FAILED` dispatch rows
  through the existing service API.
- The worker uses the mock provider adapter and transition planner, then mutates
  dispatch state through `apply_escalation_dispatch_action(...)`.
- `dry_run=True` produces plans without mutating dispatch rows.

## Boundary

Slice 0716 is run-once and bounded. It does not introduce a daemon loop, live
outbound delivery, cross-service writes, or new tables.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```
