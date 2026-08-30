# Slice 0432: AE Web Browser File-Save Adapter Foundation

## Scope

Add the browser-only adapter that may materialize AE artifact download payloads
into downloadable files.

## Changes

- Added `apps/nex-ae-web/src/artifactDownloadSaveAdapter.js`.
- Added `apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs`.
- The adapter builds safe save plans, creates Blob payloads for text and base64
  downloads, sanitizes filenames, triggers temporary anchor downloads when the
  browser APIs are available, and returns metadata-only summaries.
- The adapter returns `PREPARED` when Blob creation succeeds but browser
  download primitives are unavailable.

## Decisions

- `artifactClient.downloadArtifactFile` remains the normalized payload source.
- `artifactDownloadSaveAdapter` is the only browser module allowed to
  materialize `content` or `contentBase64` into a Blob.
- Save plans and summaries must not include raw download body, base64 payload,
  storage refs, service credentials, database URLs, or provider endpoints.
- This slice does not add PostgreSQL smoke because no backend persistence path
  changed.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs apps/nex-ae-web/test/artifactClient.test.mjs apps/nex-ae-web/test/artifactPreviewPanel.test.mjs
```

Delivery boundary audit:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_artifact_delivery_boundary_audit.py --summary
```
