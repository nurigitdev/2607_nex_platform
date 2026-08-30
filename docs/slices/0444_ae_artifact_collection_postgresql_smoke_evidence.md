# Slice 0444: AE Artifact Collection PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE artifact collection API.

## Changes

- Added `scripts/smoke/run_ae_artifact_collection_postgres_smoke.py`.
- Added `tests/test_ae_artifact_collection_postgres_smoke.py`.
- Registered the smoke runner in the default quality gate as skipped until
  explicitly enabled.
- Indexed Slice 0444 in the Slice documentation and AE API notes.

## Decisions

- The smoke only writes when `NEX_AE_ARTIFACT_COLLECTION_POSTGRES_SMOKE=1`.
- The write profile must be `test`, and the database URL must target a
  `*_test` database.
- The smoke migrates the real AE test database, creates two owner-scoped
  artifacts plus one other-owner artifact, verifies list/status/limit queries,
  observes owner/status indexes, and cleans up inserted rows.
- Evidence remains redacted and does not include database URLs, local storage
  roots, logical storage refs, rendered payloads, or download content.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_artifact_collection_postgres_smoke.py -q --cov=run_ae_artifact_collection_postgres_smoke --cov-branch --cov-report=term-missing
```

Protected PostgreSQL smoke:

```bash
NEX_AE_ARTIFACT_COLLECTION_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<redacted-nex-ae-test-url>' \
./.venv/bin/python scripts/smoke/run_ae_artifact_collection_postgres_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
