# Slice 0475: AE artifact retention history PostgreSQL smoke

## Scope

Prove the AE artifact retention execution history path against the real
`nex_ae_test` database.

## Changes

- Added `scripts/smoke/run_ae_artifact_retention_history_postgres_smoke.py`.
- Added `tests/test_ae_artifact_retention_history_postgres_smoke.py`.
- Registered the smoke runner in the default quality gate as skip-by-default.
- The protected smoke migrates the AE test DB, creates rendered logical-purge
  artifacts, runs dry-run, blocked execute, guarded execute, and duplicate
  idempotency replay, then directly reads
  `ae_artifact_retention_executions`.

## Decisions

- PostgreSQL smoke is only executed when
  `NEX_AE_ARTIFACT_RETENTION_HISTORY_POSTGRES_SMOKE=1` is set.
- The runner requires the `test` DB profile and validates that the configured DB
  URL targets a test database before writes.
- Evidence remains metadata-only and redacts database URLs, passwords, storage
  roots, rendered payloads, and storage refs.
- Smoke cleanup deletes generated history rows, remaining smoke artifacts, and
  handoff rows by the generated owner scope.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_history_postgres_smoke.py -q --cov=run_ae_artifact_retention_history_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_HISTORY_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_history_postgres_smoke.py --summary
```
