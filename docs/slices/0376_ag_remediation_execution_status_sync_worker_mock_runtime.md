# Slice 0376: AG Remediation Execution Status Sync Worker Mock Runtime

## Scope

Add the AG service-local worker facade that executes Slice 0375 remediation
execution status-sync jobs through the shared worker runner.

This slice does not add a public API route, change database schema, run
PostgreSQL smoke evidence, or call remote providers. The worker uses injected
stores/clients in tests, claims `common_job.v1` records from the shared job
queue, and delegates the business update to the existing Slice 0368/0369
`sync_generation_remediation_execution_status(...)` facade.

## Implemented

- Added `nex_ag.remediation_execution_status_sync_worker`.
- Added AG worker config construction for
  `ag.remediation_execution.status_sync` jobs.
- Added a status-sync job handler that:
  - validates job type, payload schema, subject, state, and correlation;
  - runs only `SYNC_REQUIRED` payloads;
  - rejects sensitive raw prompt/output/source/evidence/provider/runtime fields;
  - calls the existing AG status-sync facade;
  - returns a safe worker result summary without embedding AG task snapshots.
- Added one-shot and batch runner helpers over the shared
  `run_worker_once(...)` and `run_worker_batch(...)` functions.
- Covered mock runtime success, idle, batch, failure/retry, shape validation,
  correlation mismatch, subject mismatch, redaction, and runtime timestamp
  fallback paths.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
worker_runtime_changed=true
next_slice=0377_ag_remediation_execution_status_sync_postgresql_smoke_evidence
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_remediation_execution_status_sync_worker.py -q --cov=nex_ag.remediation_execution_status_sync_worker --cov-branch --cov-report=term-missing
16 passed in 0.92s
services/nex-ag/nex_ag/remediation_execution_status_sync_worker.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2688 passed, 1 warning in 78.53s
statement_coverage=98.62% threshold=95.00%
branch_coverage=95.93% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_operations_dashboard_smoke=pass endpoints=20 jobs=2 workers=1 processing_runs=2 threshold_decisions=2 events=1 logs=1 history=1 issues=4
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
