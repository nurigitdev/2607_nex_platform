# Slice 0374: AG Remediation Execution Dashboard/Issue Candidate Integration

## Scope

Integrate the Slice 0372/0373 remediation execution operations projection into
the unified AG operations dashboard and issue-candidate surfaces.

This slice does not change database schema, run PostgreSQL smoke evidence, or
call remote providers. It keeps remediation task and remediation execution
read-model sources read-only and injects the remediation execution projection
builder into the dashboard path to avoid module import cycles.

## Implemented

- Added the `remediation_executions` section to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Wired `services/nex-ag/nex_ag/main.py` so the dashboard uses the same AG task
  store and CX execution operation store as
  `GET /admin/v1/operations/remediation-executions`.
- Added dashboard normalization for remediation execution operation items,
  including task status, execution status, status-sync state, safe failure
  hashes, source/evidence counts, and debug paths.
- Added `remediation_execution_attention_required.v1` to the AG operations
  issue-candidate rule catalog.
- Added issue-candidate aggregation for failed execution, orphan execution,
  missing execution, unknown status, and status-sync review cases.
- Extended `contracts/schemas/service/nex_ag/operations_projection.v1.schema.json`
  with the new dashboard section contract.

## Refactoring Checkpoint

```text
external_api_changed=false
dashboard_contract_changed=true
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
next_slice=0375_ag_remediation_execution_status_sync_job_planning_foundation
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-report=term-missing --cov-report=json:/tmp/nex_ag_operations_0374_coverage.json
160 passed, 1 warning in 3.82s
services/nex-ag/nex_ag/operations.py statement_coverage=98% branch_coverage=98%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2659 passed, 1 warning in 87.36s
statement_coverage=98.61% threshold=95.00%
branch_coverage=95.90% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_operations_dashboard_smoke=pass endpoints=20 jobs=2 workers=1 processing_runs=2 threshold_decisions=2 events=1 logs=1 history=1 issues=4
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
