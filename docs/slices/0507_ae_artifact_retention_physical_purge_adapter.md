# Slice 0507: AE Artifact Retention Physical Purge Adapter

## Scope

Slice 0507 puts AE artifact retention physical deletion behind an explicit
storage/database adapter boundary.

## Behavior

- Added `delete_artifact_retention_physical_records(...)` as the shared purge
  adapter helper for both in-memory and SQLAlchemy artifact stores.
- The adapter deletes rendered storage files first, then delegates child-first
  artifact graph row deletion to the store-specific database callback.
- The database callback is not allowed to report storage deletes, keeping
  storage mutation and row mutation accounting separated.
- In-memory and SQLAlchemy purge paths continue to require the Slice 0506
  execute approval contract before invoking the adapter.

## Guardrails

- Adapter inputs must be a list of artifact records.
- Storage callbacks must return booleans.
- Database graph callbacks must return normalized row count dictionaries and
  must not mix storage file counts into DB deletion evidence.
- Handoff lineage remains retained after artifact purge.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_PURGE_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py --summary
```
