# Slice 0032 AE Upload Handoff Facade To CX

Status: Implemented.

Backlog candidate: `S4-002` AE upload handoff facade to CX.

Requirement coverage: `AEAPI-FR-001`, `CX-FR-001`, `AEWEB-FR-003`,
`TRACE-CONTENT-001`.

## Scope

Slice 0032 adds an AE-owned upload facade:

- `POST /api/v1/uploads` accepts upload metadata and mock `content_text`.
- AE forwards upload registration to CX with tenant/owner scope.
- AE stores only a safe handoff record with CX document and ingestion job refs.
- Same-owner CX duplicate responses become `ALREADY_EXISTS` handoff records.
- `ae_upload_handoff.v1` contract rejects raw source content and CX filesystem
  path leaks.

CX continues to own source file storage, extraction artifacts, and dedupe
semantics.

## Files

- `services/nex-ae-api/nex_ae_api/uploads.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `contracts/schemas/service/nex_ae_api/upload_handoff.v1.schema.json`
- `tests/test_nex_ae_uploads.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover CX payload construction, owner/hash/size/content
validation, safe handoff record redaction, duplicate mapping, endpoint auth,
readback, missing records, and CX error propagation.
