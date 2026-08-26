# Slice 0361: CX Remediation Execution PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the CX remediation execution path.
The smoke verifies the durable repair-attempt row and the durable job queue row
against the `nex-cx` test profile, then runs the CX remediation worker once.

This slice does not add schema, expose a new public route, or call remote
providers. Parent generation state remains in the current in-memory
`GenerationExecutionStore` boundary; the persistence evidence focuses on
`cx_remediation_execution_attempts` and `service_jobs`.

## Implemented

- Added guarded smoke runner:
  - `scripts/smoke/run_cx_remediation_execution_postgres_smoke.py`.
- The runner is skipped unless
  `NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE=1` is set.
- The runner only allows the `test` profile and resolves the database through
  `NEX_CX_TEST_DATABASE_URL`.
- The live smoke path:
  - runs current `nex-cx` migrations;
  - persists an `ACCEPTED` remediation execution attempt;
  - enqueues a `cx.remediation_execution` job in `service_jobs`;
  - runs the CX remediation worker once;
  - verifies the final `SUCCEEDED` execution/job state;
  - observes JSONB columns and expected indexes directly from PostgreSQL;
  - deletes the smoke rows before returning evidence.
- Registered the smoke in `scripts/quality/run_quality_gate.sh`, where it
  remains skipped by default.
- Added regression coverage for skip/configuration failures, migration
  failure, success with in-memory fakes, execution failure cleanup, DB
  observation helpers, cleanup rowcount handling, redaction guard, and CLI
  summary output.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=true
postgres_profile=test
smoke_env=NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE
database_env=NEX_CX_TEST_DATABASE_URL
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_cx_remediation_execution_postgres_smoke.py -q
14 passed in 0.45s

./.venv/bin/pytest tests/test_cx_remediation_execution_postgres_smoke.py -q --cov=run_cx_remediation_execution_postgres_smoke --cov-report=term-missing --cov-report=json:/tmp/cx_remediation_execution_postgres_smoke_0361_cov.json
14 passed in 1.02s
scripts/smoke/run_cx_remediation_execution_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Protected smoke, skipped by default:

```text
./.venv/bin/python scripts/smoke/run_cx_remediation_execution_postgres_smoke.py --summary
cx_remediation_execution_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE
```

Protected PostgreSQL execution:

```text
NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_cx_remediation_execution_postgres_smoke.py --summary
cx_remediation_execution_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL job_status=SUCCEEDED execution_status=SUCCEEDED cleanup_jobs=1 cleanup_attempts=1
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2530 passed, 1 warning in 69.64s
statement_coverage=98.56% threshold=95.00%
branch_coverage=95.85% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
cx_remediation_execution_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE
```
