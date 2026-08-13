# Slice 0275: CX Source-File Materialization Boundary Audit

## Scope

Freeze the source-file materialization boundary before adding browser multipart
upload support. This slice records that CX is the source-file system of record,
AE is a transient upload facade, and source bytes must remain outside
PostgreSQL while DB rows keep metadata, hashes, and storage links only.

## Implemented

- Added `scripts/smoke/run_cx_source_file_materialization_boundary_audit.py`.
- The audit verifies existing CX local filesystem materialization guardrails:
  checksum verification, safe relative storage keys, absolute local paths,
  collision detection, checksum verification timestamps, date partitioning, and
  hash sharding.
- The audit verifies AE and AE Web still operate as metadata-only upload
  surfaces until the multipart/source-byte slices are added.
- Evidence is redaction-safe: no raw source bytes, protected environment values,
  database URLs, passwords, provider endpoints, or local source paths are
  serialized.

## Boundary Decision

- CX owns durable source-file storage.
- AE must not keep long-term source-file copies.
- Browser-to-AE transport should move to multipart form data.
- AE-to-CX transport can initially use service-authenticated `content_base64`
  JSON because CX already verifies bytes against `source_sha256` before marking
  files checksum-verified.
- Future storage can replace the current local filesystem adapter with object
  storage while preserving the CX metadata boundary.
- Local storage keys remain shaped as
  `YYYYMMDD/sha2/sha2/source_file_id_extension`.

## Next Slices

- Slice 0276: CX source-file byte materialization API hardening.
- Slice 0277: AE multipart upload facade contract.
- Slice 0278: AE Web FormData upload wiring.
- Slice 0279: AE Web source-file upload Playwright PostgreSQL smoke.

## Evidence

- Boundary audit:
  `./.venv/bin/python scripts/smoke/run_cx_source_file_materialization_boundary_audit.py --summary`
- Python runner coverage:
  `./.venv/bin/pytest tests/test_cx_source_file_materialization_boundary_audit.py --cov=run_cx_source_file_materialization_boundary_audit --cov-branch --cov-report=term-missing -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
