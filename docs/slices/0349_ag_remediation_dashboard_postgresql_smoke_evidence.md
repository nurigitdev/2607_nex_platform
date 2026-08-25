# Slice 0349: AG Remediation Dashboard PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence proving that the AG operations
dashboard and issue-candidate projections read persisted generation remediation
tasks from the real `nex_ag_test` database.

## Implemented

- Added `run_ag_generation_remediation_dashboard_postgres_smoke.py`.
- The smoke runner is guarded by
  `NEX_AG_GENERATION_REMEDIATION_DASHBOARD_POSTGRES_SMOKE=1`.
- The runner applies AG migrations, writes three remediation tasks, reads the
  protected dashboard and issue-candidate routes, verifies remediation attention
  and runbook signals, and deletes the smoke rows.
- Added the runner to the full quality gate as a skipped-by-default smoke.
- Added regression coverage for skip, missing DB URL, migration failure,
  redaction, success, execution failure, row-count, and cleanup branches.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_ag_generation_remediation_dashboard_postgres_smoke.py -q
8 passed
```

PostgreSQL smoke against `nex_ag_test`:

```text
NEX_AG_GENERATION_REMEDIATION_DASHBOARD_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python scripts/smoke/run_ag_generation_remediation_dashboard_postgres_smoke.py --summary
ag_generation_remediation_dashboard_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL tasks=3 deleted_rows=3
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2405 passed
statement_coverage=98.51%
branch_coverage=95.70%
```

Next slice:

```text
Slice 0350: S35 remediation observability closure checkpoint
```
