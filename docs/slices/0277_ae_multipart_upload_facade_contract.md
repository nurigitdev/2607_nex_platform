# Slice 0277: AE Multipart Upload Facade Contract

## Scope

Add an AE API multipart upload facade so browsers can submit real file bytes
without making AE a durable source-file store. The facade reads the request
file, validates size/hash when supplied, forwards bytes to CX as
`content_base64`, and stores only the existing safe upload handoff record.

## Implemented

- Added runtime dependency `python-multipart`.
- Added `POST /api/v1/uploads/files`.
- Added `AE_MULTIPART_UPLOAD_ROUTE`.
- Added `build_multipart_upload_source_payload(...)` for byte-to-CX payload
  preparation.
- Extended AE-to-CX upload payloads to accept `content_base64` while rejecting
  `content_text`/`content_base64` conflicts.
- Multipart route:
  - validates browser/service auth through the existing facade auth boundary;
  - applies browser claim owner scope before CX handoff;
  - checks optional `source_sha256` and `size_bytes` against the actual file;
  - forwards `content_base64` to CX;
  - keeps raw source bytes and base64 payloads out of AE handoff records.

## Evidence

- AE upload regression:
  `./.venv/bin/pytest tests/test_nex_ae_uploads.py --cov=nex_ae_api.uploads --cov-branch --cov-report=term-missing -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
