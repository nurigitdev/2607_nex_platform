# Slice 0478: AE artifact retention history query PostgreSQL smoke

Prove the authenticated retention history query route against the real AE test
database.

## Changes

- Added `scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py`.
- Added `tests/test_ae_artifact_retention_history_query_postgres_smoke.py`.
- Added the query smoke to the default quality gate as a protected skip-by-default
  check.

## Evidence

- The protected smoke migrates the AE test DB, seeds three retention execution
  history records through the SQLAlchemy history store, queries
  `GET /api/v1/artifact-retention/executions`, validates all/execute/blocked
  filters, checks unauthorized and invalid-mode paths, cross-checks direct DB
  counts, and cleans up generated history rows.
- Smoke evidence records only route summaries, DB row summaries, hashes, and
  boolean checks. It does not include raw execution JSON, local storage paths, or
  database credentials.

## Verification

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_history_query_postgres_smoke.py -q --cov=run_ae_artifact_retention_history_query_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_HISTORY_QUERY_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py --summary
```
