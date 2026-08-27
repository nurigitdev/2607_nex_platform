# Slice 0372: AG Remediation Execution Operations Projection Foundation

## Scope

Add the read-only AG operations projection foundation for remediation execution
runtime status.

This slice does not add public API routes, change database schema, run
PostgreSQL smoke evidence, or call remote providers. It prepares the projection
that later AG routes, dashboard cards, issue candidates, and status-sync worker
planning can reuse.

## Implemented

- Added `ag_remediation_execution_operations_projection.v1`.
- Added `nex_ag.remediation_execution_operations` with:
  - `InMemoryRemediationExecutionOperationsStore`;
  - `SqlAlchemyRemediationExecutionOperationsStore` for read-only CX execution
    attempts;
  - task/execution source status metadata;
  - AG task and CX execution merge by `remediation_action_id`;
  - safe operator fields for task status, execution status, target task status,
    sync state, result refs, failure hashes, lineage, attempts, and timestamps.
- Added status-sync state projection:
  - `NO_EXECUTION`;
  - `ORPHAN_EXECUTION`;
  - `UNKNOWN_EXECUTION_STATUS`;
  - `IN_SYNC`;
  - `TERMINAL_TASK_DIVERGED`;
  - `SYNC_REQUIRED`.
- Added summaries for task status, execution status, missing executions, orphan
  executions, failed executions, sync-required items, and attention-required
  items.
- Kept raw prompt, raw generation output, raw source text, raw evidence preview,
  provider secrets, service tokens, and database URLs out of projected records.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
next_slice=0373_ag_remediation_execution_operations_api_wiring
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_remediation_execution_operations.py -q --cov=nex_ag.remediation_execution_operations --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_execution_operations_0372_cov.json
14 passed in 1.02s
services/nex-ag/nex_ag/remediation_execution_operations.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2651 passed, 1 warning in 76.34s
statement_coverage=98.62% threshold=95.00%
branch_coverage=95.99% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
