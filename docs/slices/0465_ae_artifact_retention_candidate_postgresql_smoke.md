# Slice 0465: AE artifact retention candidate PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL evidence for the AE artifact retention candidate route
against the real `nex_ae_test` database.

## Changes

- Added `scripts/smoke/run_ae_artifact_retention_candidate_postgres_smoke.py`.
- Added `tests/test_ae_artifact_retention_candidate_postgres_smoke.py`.
- Registered the smoke in the default quality gate as opt-in/skipped by
  default.
- Indexed Slice 0465 in the Slice documentation and AE API notes.

## Evidence Shape

When explicitly enabled, the smoke:

- runs `nex-ae-api` migrations for the test profile;
- creates two rendered artifacts through the AE API persisted store;
- marks both artifacts as `DELETED` through the lifecycle route;
- ages one logical purge timestamp beyond the 30-day retention cutoff;
- calls `GET /api/v1/artifact-retention/candidates` with owner scope;
- verifies the API candidate set and direct PostgreSQL counts agree;
- confirms artifact, file, link rows and local rendered files are retained;
- cleans up smoke rows after the evidence is collected.

## Protected Execution

```bash
NEX_AE_ARTIFACT_RETENTION_CANDIDATE_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://...' \
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_candidate_postgres_smoke.py --summary
```

The smoke rejects non-test profiles and redacts database URLs, passwords,
storage roots, rendered payloads, and local data paths from evidence.

## Decisions

- Slice 0465 is still dry-run only. It does not physically delete artifact
  rows, file rows, link rows, or rendered files.
- The first logical purge marker is `artifact_status=DELETED`.
- The first retention policy default is 30 days after logical purge, with 15-day
  and 30-day presets carried from Slice 0462.
- Scheduled physical deletion remains deferred to a later guarded batch track.

## Regression

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_candidate_postgres_smoke.py -q --cov=run_ae_artifact_retention_candidate_postgres_smoke --cov-branch --cov-report=term-missing
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
