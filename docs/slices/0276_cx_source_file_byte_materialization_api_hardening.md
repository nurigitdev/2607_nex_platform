# Slice 0276: CX Source-File Byte Materialization API Hardening

## Scope

Harden the CX source-byte upload boundary before AE and AE Web start sending
real browser file bytes. This slice keeps CX as the source-file system of
record and adds a redacted, owner-scoped materialization receipt API.

## Implemented

- CX now rejects `source_sha256` mismatches when `content_text` or
  `content_base64` is provided.
- Added `cx_source_file_materialization_receipt.v1`.
- Added
  `GET /api/v1/documents/{document_id}/source-file/materialization`, scoped by
  `tenant_id` and `owner_user_id`.
- The receipt reports checksum verification, payload source, source byte
  availability, storage backend/key/URI metadata, and source-file ID without
  exposing raw bytes or local filesystem paths.
- Metadata-only uploads remain valid and report materialization status
  `PENDING` until bytes are supplied and checksum-verified.

## Evidence

- CX regression:
  `./.venv/bin/pytest tests/test_nex_cx_ingestion.py --cov=services/nex-cx/nex_cx/ingestion.py --cov-branch --cov-report=term-missing -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
