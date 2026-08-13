# Slice 0272: AE Web Authenticated Upload Metadata Surface Hardening

## Scope

Add a browser-safe file metadata surface for the authenticated upload workflow.
This slice keeps upload behavior on metadata handoff only; it does not read or
send raw file bytes.

## Implemented

- Added `ae_web_upload_file_metadata.v1` to `uploadSurface.js`.
- Added `buildUploadFileMetadata` and
  `buildUploadSurfaceDraftFromFileMetadata`.
- Added an AE Web file input and optional SHA-256 field in the upload panel.
- The browser surface now updates upload handoff drafts from:
  - file name;
  - content type;
  - file size;
  - optional source SHA-256;
  - OA session-claim owner scope.
- Safe upload preview now includes file metadata summary flags and continues to
  exclude raw source bytes, local paths, service tokens, provider endpoints, and
  database URLs.
- Added Node regression coverage for file metadata, draft creation, invalid
  metadata, and source-byte redaction.

## Evidence

- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
- Post-login workflow audit:
  `./.venv/bin/python scripts/smoke/run_ae_web_post_login_document_workflow_audit.py --summary`
  - Expected after this slice:
    `ae_web_post_login_document_workflow_audit=pass ... gaps_ready=1/2 ...`

## Next

Slice 0273 should wire the authenticated upload fetch path so the browser can
submit the metadata handoff through same-origin `/ae-api/api/v1/uploads` after
credential login.
