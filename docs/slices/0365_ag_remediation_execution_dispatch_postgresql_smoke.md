# Slice 0365: AG Remediation Execution Dispatch PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the AG remediation execution
dispatch API introduced in Slice 0364. The smoke verifies that an AG
remediation task is seeded in `nex_ag_test`, dispatched through the protected
HTTP route, updated to `WAITING_ON_CX`, observed directly from PostgreSQL, and
cleaned up before the runner exits.

This slice does not add schema, change the dispatch contract, or require a
live remote provider. The CX execution dependency is injected as a static safe
client so the smoke focuses on the AG persistence and API boundary.

## Implemented

- Added guarded smoke runner:
  - `scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py`.
- The runner is skipped unless
  `NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE=1` is set.
- The runner only allows the `test` profile and resolves the database through
  `NEX_AG_TEST_DATABASE_URL`.
- The live smoke path:
  - runs current `nex-ag` migrations;
  - persists a `PROPOSED` remediation task in
    `ag_generation_remediation_tasks`;
  - calls the protected dispatch route with a service token;
  - verifies the route returns
    `ag_generation_remediation_execution_dispatch.v1`;
  - verifies the persisted task reaches `WAITING_ON_CX`;
  - observes JSONB columns and expected indexes directly from PostgreSQL;
  - checks that raw prompts, raw generation output, provider endpoints, API
    keys, passwords, and raw DB URLs are not present in evidence;
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
smoke_env=NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE
database_env=NEX_AG_TEST_DATABASE_URL
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_ag_remediation_execution_dispatch_postgres_smoke.py -q
11 passed, 1 warning in 0.46s

./.venv/bin/pytest tests/test_ag_remediation_execution_dispatch_postgres_smoke.py -q --cov=run_ag_remediation_execution_dispatch_postgres_smoke --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_execution_dispatch_postgres_smoke_0365_cov.json
11 passed, 1 warning in 1.05s
scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py statement_coverage=100% branch_coverage=100%
```

Protected smoke, skipped by default:

```text
./.venv/bin/python scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py --summary
ag_remediation_execution_dispatch_postgres_smoke=skipped reason=NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE
```

Protected PostgreSQL execution:

```text
NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py --summary
ag_remediation_execution_dispatch_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL final_status=WAITING_ON_CX row_status=WAITING_ON_CX cleanup=1
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2574 passed, 1 warning in 67.74s
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.88% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_remediation_execution_dispatch_postgres_smoke=skipped reason=NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE
cx_remediation_execution_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE
```
