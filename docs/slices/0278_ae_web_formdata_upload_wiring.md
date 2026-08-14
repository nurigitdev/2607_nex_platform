# Slice 0278: AE Web FormData Upload Wiring

## Scope

Wire AE Web so selected browser files are sent through the AE multipart upload
facade added in Slice 0277. Metadata-only upload remains available when no file
object is provided.

## Implemented

- Added `AE_MULTIPART_UPLOAD_ROUTE` as `/api/v1/uploads/files`.
- Added `buildUploadFormDataPayload(...)` to construct browser `FormData`
  without service tokens, storage paths, provider endpoints, or CX internal
  byte-payload field names.
- Extended upload clients to accept `submitUploadDraft(draft, { file })`.
- Fetch upload client now:
  - posts JSON to `/api/v1/uploads` when no file is selected;
  - posts multipart `FormData` to `/api/v1/uploads/files` when a file is
    selected;
  - leaves the multipart `Content-Type` boundary to the browser.
- The main upload submit handler now passes the selected file object to the
  upload client.

## Evidence

- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
- Python static guard:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
