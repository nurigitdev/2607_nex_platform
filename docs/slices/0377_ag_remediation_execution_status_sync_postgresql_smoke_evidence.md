# Slice 0377: AG Remediation Execution Status Sync PostgreSQL Smoke Evidence

## Scope

Add guarded PostgreSQL smoke evidence for the AG remediation execution
status-sync worker path.

This slice does not change database schema, add a public API route, or call
remote providers. It proves the Slice 0375/0376 job planning and worker runtime
against real test-profile PostgreSQL databases by writing AG task/job/runtime
rows, reading CX remediation execution detail through the in-process CX
read-model API, completing the AG task sync, and cleaning up all smoke rows.

## Implemented

- Added
  `scripts/smoke/run_ag_remediation_execution_status_sync_worker_postgres_smoke.py`.
- The guarded runner is enabled only with
  `NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_POSTGRES_SMOKE=1`.
- The runner enforces `test` profile only.
- The smoke runs both `nex-ag` and `nex-cx` migrations before execution.
- The smoke writes and verifies:
  - `ag_generation_remediation_tasks`;
  - `service_jobs`;
  - `service_worker_heartbeats`;
  - `service_log_entries`;
  - `cx_remediation_execution_attempts`.
- The smoke executes the AG worker through the shared `SqlAlchemyJobQueue`,
  `SqlAlchemyWorkerHeartbeatStore`, `SqlAlchemyServiceLogStore`, and
  `run_remediation_execution_status_sync_worker_once(...)`.
- Added the runner to the standard quality gate as a skipped-by-default smoke
  and to `run_postgres_test_smoke_suite.py` as a child stage.
- Added regression tests covering skip/config failure, migration failure,
  redacted success, failed checks, engine cleanup, observation helpers, cleanup
  helpers, and CLI summary.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=true
actual_test_db_smoke_executed=true
next_slice=0378_s38_remediation_runtime_operations_closure_checkpoint
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_ag_remediation_execution_status_sync_worker_postgres_smoke.py -q --cov=run_ag_remediation_execution_status_sync_worker_postgres_smoke --cov-branch --cov-report=term-missing
13 passed, 1 warning in 1.11s
scripts/smoke/run_ag_remediation_execution_status_sync_worker_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

PostgreSQL test DB smoke:

```text
NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=<redacted nex_ag_test URL> \
NEX_CX_TEST_DATABASE_URL=<redacted nex_cx_test URL> \
./.venv/bin/python scripts/smoke/run_ag_remediation_execution_status_sync_worker_postgres_smoke.py --summary
ag_remediation_execution_status_sync_worker_postgres_smoke=pass service=nex-ag ag_db_env=NEX_AG_TEST_DATABASE_URL cx_db_env=NEX_CX_TEST_DATABASE_URL worker_status=SUCCEEDED job_cleanup=1 log_cleanup=3
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2701 passed, 1 warning in 89.72s
statement_coverage=98.62% threshold=95.00%
branch_coverage=95.94% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_remediation_execution_status_sync_worker_postgres_smoke=skipped reason=NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_POSTGRES_SMOKE
ag_operations_dashboard_smoke=pass endpoints=20 jobs=2 workers=1 processing_runs=2 threshold_decisions=2 events=1 logs=1 history=1 issues=4
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
