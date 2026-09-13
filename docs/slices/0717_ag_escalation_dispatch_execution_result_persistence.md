# Slice 0717: AG escalation dispatch execution result persistence hardening

## Intent

Persist only safe execution-result summaries after a run-once dispatch execution
worker run.

## Implementation

- Added
  `ag_operator_review_escalation_dispatch_execution_result_metadata.v1`.
- Added `build_dispatch_execution_result_metadata(...)`.
- Added `record_dispatch_execution_result_metadata(...)`.
- `run_dispatch_execution_worker_once(...)` now records
  `metadata.last_execution_result` on the dispatch row after non-dry-run worker
  processing.
- Persisted metadata contains safe status, provider profile, result hash, safe
  preview, retry/error summary, run id, worker id, and redaction flags.

## Boundary

Slice 0717 does not add a worker-result table. Result persistence stays inside
the existing `ag_op_esc_dispatches.metadata` envelope until a future slice
requires a separate table.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```
