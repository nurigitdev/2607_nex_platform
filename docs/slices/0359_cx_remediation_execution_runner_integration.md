# Slice 0359: CX Remediation Execution Runner Integration

## Scope

Wire the Slice 0358 remediation execution mock handler into the shared service
worker runner.

This slice does not add a public API route, change database schema, perform
PostgreSQL smoke testing, or call live providers.

## Implemented

- Added `build_remediation_execution_worker_config(...)`.
- Added `run_cx_remediation_execution_worker_once(...)`.
- Added `run_cx_remediation_execution_worker_batch(...)`.
- Reused the Slice 0358 claimed-job handler with
  `handler_finalizes_job=true`.
- The shared runner now provides standard behavior for remediation execution:
  - bounded one-shot job polling;
  - bounded batch processing;
  - `STARTING/BUSY/IDLE` worker heartbeats;
  - optional service log emission;
  - standard `WorkerJobExecution` / `WorkerBatchResult` summaries.
- Domain failures, such as missing parent generation records, are finalized by
  the CX handler. The common runner observes the finalized `FAILED` job and does
  not retry it again.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
runner_handler_finalizes_job=true
next_slice=0360_cx_remediation_execution_closure_checkpoint
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution_worker.py -q
18 passed in 0.41s

./.venv/bin/pytest tests/test_nex_cx_remediation_execution_worker.py -q --cov=nex_cx.remediation_execution_worker --cov-report=json:/tmp/cx_remediation_execution_worker_cov_0359.json --cov-report=term-missing
18 passed in 0.95s
nex_cx.remediation_execution_worker statement_coverage=100% branch_coverage=100%

./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py tests/test_nex_cx_remediation_execution_planning.py tests/test_nex_cx_remediation_execution_worker.py tests/test_nex_runtime_worker_runner.py -q
84 passed, 1 warning in 0.57s
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2512 passed, 1 warning in 68.17s
statement_coverage=98.56% threshold=95.00%
branch_coverage=95.84% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
