# Slice 0366: CX Remediation Execution Read-Model API Foundation

## Scope

Expose a protected CX remediation execution read model so AG can inspect the
execution state after dispatch without depending on CX's in-memory parent
generation store. The read surface is intentionally persistence-oriented:
if an execution attempt exists in the execution store, list/detail reads can
return it even when the parent generation record is not loaded in memory.

This slice does not add database schema, PostgreSQL smoke evidence, AG status
synchronization, or live provider calls. PostgreSQL evidence is deferred to
Slice 0367.

## Implemented

- Added CX remediation execution read-model schema versions:
  - `cx_remediation_execution_list.v1`;
  - `cx_remediation_execution_detail.v1`.
- Added protected routes:
  - `GET /api/v1/generations/{cx_generation_id}/remediation-executions`;
  - `GET /api/v1/generations/{cx_generation_id}/remediation-executions/{remediation_action_id}`.
- List responses include deterministic item ordering, count, status/type
  rollups, latest update time, and redaction summary flags.
- Detail responses include the stored execution record, execution status,
  attention flag for failed/cancelled attempts, and safe debug paths.
- Wrong-parent detail lookups collapse to the same not-found response as missing
  executions, preserving the path-scope boundary.
- Updated `contracts/openapi/nex-cx.openapi.yaml` for the new read routes.
- Added regression coverage for persisted-row reads without a parent generation
  record, auth failures, not-found collapse, store errors, empty list summaries,
  unknown rollup buckets, and required-field builder failures.

## Refactoring Checkpoint

```text
external_api_changed=true
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
read_model_store=cx_remediation_execution_attempts via RemediationExecutionStoreProtocol
next_slice=0367_cx_remediation_execution_read_model_postgresql_smoke
```

## Evidence

Targeted regression and coverage:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py -q --cov=nex_cx.remediation_execution --cov-report=term-missing --cov-report=json:/tmp/cx_remediation_execution_0366_cov.json
19 passed, 1 warning in 1.21s
nex_cx.remediation_execution statement_coverage=100% branch_coverage=100%
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2578 passed, 1 warning in 68.59s
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.88% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_remediation_execution_dispatch_postgres_smoke=skipped reason=NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE
cx_remediation_execution_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE
```
