# Slice 0429: AE Artifact Export Read-Model PostgreSQL Smoke

## Scope

Harden the protected AE artifact export PostgreSQL smoke so rendered export
files are also verified through the service read-model routes.

## Changes

- `scripts/smoke/run_ae_artifact_export_postgres_smoke.py` now reads back:
  - `/api/v1/artifacts/{artifact_id}`;
  - `/api/v1/artifacts/{artifact_id}/versions`; and
  - `/api/v1/artifact-render-jobs/{render_job_id}`.
- The smoke records safe read-model observations only: status codes, file
  counts, rendered formats, download-link counts, and render-job status/stage.
- Checks now prove that artifact detail, versions, and render-job readbacks
  match the multi-format render result persisted in PostgreSQL.
- The summary line includes `read_model_files=4` when the protected test DB
  smoke passes.

## Test DB Smoke Policy

Run only against the AE test database:

```bash
NEX_AE_ARTIFACT_EXPORT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test \
./.venv/bin/python scripts/smoke/run_ae_artifact_export_postgres_smoke.py --summary
```

The smoke runs migrations, creates an artifact handoff, creates and renders a
multi-format artifact, verifies file/download/read-model state, and cleans up
its rows.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_artifact_export_postgres_smoke.py -q --cov=run_ae_artifact_export_postgres_smoke --cov-branch --cov-report=term-missing
```

Protected PostgreSQL smoke:

```bash
ae_artifact_export_postgres_smoke=pass ... files=4 links=8 read_model_files=4 storage_files=4 deleted_artifacts=1 deleted_handoffs=1
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
