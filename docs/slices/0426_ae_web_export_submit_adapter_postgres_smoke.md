# Slice 0426: AE Web Export Submit Adapter and PostgreSQL Smoke

Status: Completed

## Purpose

Close the S43 export/transform boundary by wiring AE Web format selection to a
real artifact render-job submit adapter and adding protected PostgreSQL smoke
evidence for multi-format export files.

## Scope

- `apps/nex-ae-web/src/artifactClient.js` now exposes
  `submitArtifactExportRequest` for mock and fetch clients.
- Fetch mode POSTs to `/api/v1/artifacts/{artifact_id}/render-jobs` with
  same-origin credentials, an `Idempotency-Key`, and explicit
  `target_formats`.
- Mock mode materializes a deterministic export result so browser regression can
  exercise the same request/response shape without a live backend.
- `apps/nex-ae-web/src/main.js` now routes the selected output format through
  `submitArtifactExportRequest` before displaying the artifact ref.
- `scripts/smoke/run_ae_artifact_export_postgres_smoke.py` adds protected
  evidence for `MD`, `HTML_PREVIEW`, `DOCX`, and `PDF` render outputs against
  the AE test database.

## Test DB Smoke Policy

The export smoke is intentionally skipped during the normal regression gate.
Run it only with the protected test profile:

```bash
NEX_AE_ARTIFACT_EXPORT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test \
./.venv/bin/python scripts/smoke/run_ae_artifact_export_postgres_smoke.py --summary
```

The smoke runs AE migrations, creates a handoff, creates an artifact, renders
all four formats, selects the persisted version/file/link rows, validates
text-vs-base64 download shapes, verifies local rendered payload files, and
cleans up its rows.

## Evidence

- `npm --prefix apps/nex-ae-web test`
- `./.venv/bin/pytest tests/test_ae_artifact_export_postgres_smoke.py tests/test_ae_artifact_export_transform_boundary_audit.py -q --cov=scripts/smoke/run_ae_artifact_export_postgres_smoke.py --cov=scripts/smoke/run_ae_artifact_export_transform_boundary_audit.py --cov-branch --cov-report=term-missing`
- `./scripts/quality/run_quality_gate.sh`
