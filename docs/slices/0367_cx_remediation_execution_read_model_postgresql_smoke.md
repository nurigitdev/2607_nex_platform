# Slice 0367: CX Remediation Execution Read-Model PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the CX remediation execution
read-model APIs from Slice 0366. The smoke verifies that a persisted execution
attempt in `nex_cx_test` can be read through the protected list/detail HTTP
routes without loading the parent generation record in memory.

This slice does not add schema, change the read-model contract, synchronize AG
task status, or call live remote providers.

## Implemented

- Added guarded smoke runner:
  - `scripts/smoke/run_cx_remediation_execution_read_model_postgres_smoke.py`.
- The runner is skipped unless
  `NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE=1` is set.
- The runner only allows the `test` profile and resolves the database through
  `NEX_CX_TEST_DATABASE_URL`.
- The live smoke path:
  - runs current `nex-cx` migrations;
  - persists one `ACCEPTED` row in `cx_remediation_execution_attempts`;
  - builds the CX FastAPI app with an empty parent generation store;
  - calls the protected read-model list/detail routes;
  - verifies the missing detail path collapses to `404`;
  - observes JSONB columns and expected indexes directly from PostgreSQL;
  - verifies evidence redaction for raw prompt/output/source text, provider
    endpoint keys, API keys, passwords, and raw DB URLs;
  - deletes the smoke row before returning evidence.
- Registered the smoke in `scripts/quality/run_quality_gate.sh`, where it
  remains skipped by default.
- Added regression coverage for skip/configuration failures, migration
  failure, success with in-memory fakes, failed verification checks, DB
  observation helpers, cleanup rowcount handling, redaction guard, and CLI
  summary output.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=true
postgres_profile=test
smoke_env=NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE
database_env=NEX_CX_TEST_DATABASE_URL
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_cx_remediation_execution_read_model_postgres_smoke.py -q
11 passed, 1 warning in 0.47s

./.venv/bin/pytest tests/test_cx_remediation_execution_read_model_postgres_smoke.py -q --cov=run_cx_remediation_execution_read_model_postgres_smoke --cov-report=term-missing --cov-report=json:/tmp/cx_remediation_execution_read_model_postgres_smoke_0367_cov.json
11 passed, 1 warning in 1.09s
scripts/smoke/run_cx_remediation_execution_read_model_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Protected smoke, skipped by default:

```text
./.venv/bin/python scripts/smoke/run_cx_remediation_execution_read_model_postgres_smoke.py --summary
cx_remediation_execution_read_model_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE
```

Protected PostgreSQL execution:

```text
NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_cx_remediation_execution_read_model_postgres_smoke.py --summary
cx_remediation_execution_read_model_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL list_count=1 detail_status=ACCEPTED row_status=ACCEPTED cleanup=1
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2589 passed, 1 warning in 72.08s
statement_coverage=98.59% threshold=95.00%
branch_coverage=95.89% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
cx_remediation_execution_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE
cx_remediation_execution_read_model_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE
```
