# Slice 0071 CX Real File Upload Boundary Hardening

Status: Implemented.

Backlog candidate: `S7-001` CX real file upload boundary hardening.

Requirement coverage: `CX-INGEST-001`, `CX-STORAGE-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0071 hardens the CX upload registration boundary before adding richer
extractors.

- Upload registration now accepts either `content_text`, `content_base64`, or a
  precomputed `source_sha256 + size_bytes` metadata-only registration.
- `content_text` and `content_base64` are mutually exclusive.
- Source size is validated against `NEX_CX_MAX_UPLOAD_SIZE_BYTES`.
- Provided `size_bytes` must match supplied text or base64 source content.
- Base64 source bytes are materialized to the existing hash/UUID local storage
  key without storing raw content in the public document record.
- Same-owner duplicate uploads keep returning the existing document, but if the
  existing registration was metadata-only and duplicate bytes arrive later, CX
  can materialize and checksum-verify the existing source file.

## Storage Policy

The public upload record exposes only boundary metadata:

- payload source kind
- sha256 checksum algorithm
- source-content-in-record flag
- maximum allowed upload size

Raw source bytes remain private in the in-memory test store and local source
file path. Future object storage can replace the local path while keeping the
same metadata boundary.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_cx_ingestion.py
scripts/quality/run_quality_gate.sh
```
