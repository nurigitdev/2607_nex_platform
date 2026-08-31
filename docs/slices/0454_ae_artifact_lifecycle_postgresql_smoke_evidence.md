# Slice 0454: AE Artifact Lifecycle PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL evidence for the AE artifact lifecycle route against
the real `nex_ae_test` database.

## Changes

- Added `scripts/smoke/run_ae_artifact_lifecycle_postgres_smoke.py`.
- Added `tests/test_ae_artifact_lifecycle_postgres_smoke.py`.
- Registered the smoke in the default quality gate as opt-in/skipped by
  default.
- Indexed Slice 0454 in the Slice documentation and AE API notes.

## Evidence Shape

When explicitly enabled, the smoke:

- runs `nex-ae-api` migrations for the test profile;
- creates a rendered artifact through the real AE API store;
- calls `POST /api/v1/artifacts/{artifact_id}/lifecycle-actions` for
  `ARCHIVE`, `RESTORE`, and `MARK_DELETED`;
- reads the artifact and owner-scoped collection back through the API;
- checks `ae_artifacts`, `ae_artifact_files`, and `ae_artifact_links` directly
  in PostgreSQL;
- verifies rendered files remain present because S46 does not perform physical
  deletion;
- cleans up smoke rows.

## Protected Execution

```bash
NEX_AE_ARTIFACT_LIFECYCLE_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://...' \
./.venv/bin/python scripts/smoke/run_ae_artifact_lifecycle_postgres_smoke.py --summary
```

The smoke rejects non-test profiles and redacts database URLs, passwords,
storage roots, rendered payloads, and local data paths from evidence.

## Regression

```bash
./.venv/bin/pytest tests/test_ae_artifact_lifecycle_postgres_smoke.py -q --cov=run_ae_artifact_lifecycle_postgres_smoke --cov-branch --cov-report=term-missing
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
