# Slice 0369: AG Remediation Execution Status Sync API/Evidence

## Scope

Expose the protected AG API for synchronizing a dispatched remediation task from
CX remediation execution detail, and add guarded PostgreSQL evidence that proves
the sync can read `nex_cx_test` and update `nex_ag_test`.

This slice does not add database schema, call live remote providers, or execute
the actual CX repair worker. It closes the Slice 0368 deferral for the AG
status-sync API and PostgreSQL evidence boundary.

## Implemented

- Added
  `POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}/sync-execution-status`.
- The route:
  - requires the existing service-token authorization boundary;
  - accepts optional `observed_at`;
  - calls `sync_generation_remediation_execution_status(...)`;
  - returns `ag_generation_remediation_execution_status_sync.v1`;
  - maps AG store/CX detail failures through the shared remediation execution
    problem response.
- Updated `contracts/openapi/nex-ag.openapi.yaml` with:
  - `AgGenerationRemediationExecutionStatusSyncRequest`;
  - `AgGenerationRemediationExecutionStatusSync`;
  - the protected sync route operation and response contract.
- Added guarded cross-database smoke runner:
  - `scripts/smoke/run_ag_remediation_execution_status_sync_postgres_smoke.py`.
- The runner is skipped unless
  `NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE=1` is set.
- The live smoke path:
  - runs current `nex-ag` and `nex-cx` migrations;
  - writes one `WAITING_ON_CX` remediation task into `NEX_AG_TEST_DATABASE_URL`;
  - writes one `SUCCEEDED` remediation execution detail source row into
    `NEX_CX_TEST_DATABASE_URL`;
  - reads CX detail through the protected in-process CX read-model API;
  - calls the protected AG sync API;
  - verifies the AG task is persisted as `COMPLETED`;
  - observes both rows directly from PostgreSQL;
  - redacts raw DB URLs and unsafe raw payload/provider fields;
  - deletes both smoke rows before returning evidence.
- Registered the smoke in `scripts/quality/run_quality_gate.sh`, where it
  remains skipped by default.
- Included the new smoke stage in the optional
  `scripts/smoke/run_postgres_test_smoke_suite.py`.

## Refactoring Checkpoint

```text
external_api_changed=true
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=true
postgres_profile=test
ag_database_env=NEX_AG_TEST_DATABASE_URL
cx_database_env=NEX_CX_TEST_DATABASE_URL
smoke_env=NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py -q --cov=nex_ag.generation_remediation_execution --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_execution_0369_cov.json
43 passed, 1 warning in 1.31s
nex_ag.generation_remediation_execution statement_coverage=100% branch_coverage=100%

./.venv/bin/pytest tests/test_ag_remediation_execution_status_sync_postgres_smoke.py -q --cov=run_ag_remediation_execution_status_sync_postgres_smoke --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_execution_status_sync_postgres_smoke_0369_cov.json
15 passed, 1 warning in 1.19s
scripts/smoke/run_ag_remediation_execution_status_sync_postgres_smoke.py statement_coverage=100% branch_coverage=100%

./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py tests/test_ag_remediation_execution_status_sync_postgres_smoke.py tests/test_smoke_helpers.py -q
257 passed, 1 warning in 9.07s
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
```

Protected PostgreSQL execution:

```text
NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_ag_remediation_execution_status_sync_postgres_smoke.py --summary
ag_remediation_execution_status_sync_postgres_smoke=pass service=nex-ag ag_db_env=NEX_AG_TEST_DATABASE_URL cx_db_env=NEX_CX_TEST_DATABASE_URL final_status=COMPLETED cx_status=SUCCEEDED cleanup_ag=1 cleanup_cx=1
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2616 passed, 1 warning in 74.77s
statement_coverage=98.60% threshold=95.00%
branch_coverage=95.91% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_remediation_execution_status_sync_postgres_smoke=skipped reason=NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```
