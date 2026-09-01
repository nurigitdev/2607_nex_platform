# Slice 0469: AE artifact retention purge PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE artifact retention purge API.

## Changes

- Added `scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py`.
- Added `tests/test_ae_artifact_retention_purge_postgres_smoke.py`.
- Registered the new smoke runner in `scripts/quality/run_quality_gate.sh`.
- The smoke runner migrates the AE test database, creates two rendered logical
  purge artifacts, verifies dry-run and blocked execute keep rows/files intact,
  executes a guarded purge through `POST /api/v1/artifact-retention/purge`,
  checks direct DB row counts and local storage file counts, and cleans up smoke
  data.

## Safety

- The runner is skipped by default.
- Enable only against a test database:

```bash
NEX_AE_ARTIFACT_RETENTION_PURGE_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py --summary
```

- The runner rejects non-test profiles.
- Evidence redacts database URLs, passwords, storage roots, and local data paths.
- Smoke evidence remains metadata-only and excludes `storage_ref`, rendered
  payloads, and `content_base64`.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_purge_postgres_smoke.py -q --cov=run_ae_artifact_retention_purge_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_PURGE_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py --summary
```

Observed summary:

```text
ae_artifact_retention_purge_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL deleted_artifacts=1 deleted_files=2 live_db=true cleanup_artifacts=1 cleanup_handoffs=2
```
