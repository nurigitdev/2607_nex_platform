# Slice 0434: AE Web Export Result UX Read-Model

## Scope

Make AE Web export/download readiness visible through a browser-safe read-model.

## Changes

- Added `apps/nex-ae-web/src/artifactExportResultReadModel.js`.
- Added `apps/nex-ae-web/test/artifactExportResultReadModel.test.mjs`.
- `apps/nex-ae-web/src/main.js` now keeps `artifactExportResult` in workspace
  state and refreshes it after export submit and download save actions.
- The artifact panel summary now shows export status, downloadable formats,
  render job/stage metadata, and latest browser save status without carrying
  raw routes or payloads.
- Added compact `.artifact-export-result` styling inside the existing artifact
  panel.

## Decisions

- Export result UX uses counts, formats, status, and save metadata only.
- Artifact card buttons remain the owner of actual preview/download routes.
- Raw text bodies, base64 payloads, storage refs, service credentials, database
  URLs, and provider endpoints stay out of the read-model and rendered HTML.
- This slice does not add PostgreSQL smoke because it changes only browser
  read-model and rendering behavior.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactExportResultReadModel.test.mjs apps/nex-ae-web/test/artifactDownloadActionWiring.test.mjs apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs
```

Delivery boundary audit:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_artifact_delivery_boundary_audit.py --summary
```
