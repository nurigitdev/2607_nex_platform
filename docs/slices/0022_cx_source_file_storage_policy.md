# Slice 0022 CX Source File Storage Policy

Status: Implemented.

Backlog candidate: `S3-002` CX source file metadata and local storage key
policy.

Requirement coverage: `CX-FR-001`, `CX-FR-002`, `TRACE-PLAT-001`.

## Scope

Slice 0022 clarifies that original file bytes stay outside PostgreSQL:

- Renames the CX persistence concept from source blobs to source files.
- Adds a migration that renames `cx_source_blobs` to `cx_source_files` and
  renames `source_blob_id` references to `source_file_id`.
- Adds source file metadata columns for `storage_backend`, `storage_key`,
  `stored_filename`, `stored_extension`, and `checksum_verified_at`.
- Defines the local filesystem storage key shape as:
  `YYYYMMDD/<sha256[0:2]>/<sha256[2:4]>/<source_file_id><extension>`.
- Keeps source file bytes in `/data/nex-platform/cx/source-files` for local
  development, with future object storage support represented by backend/key/URI
  metadata.
- Updates CX upload registration records so storage paths no longer include the
  original filename.

User-level dedupe remains based on active logical documents:
`tenant_id + owner_user_id + source_sha256`. Storage-level dedupe remains based
on `source_sha256`, but that fact must not leak across user boundaries.

## Files

- `database/nex-cx/migrations/0022_source_file_storage_policy.sql`
- `services/nex-cx/nex_cx/ingestion.py`
- `contracts/schemas/service/nex_cx/upload_registration.v1.schema.json`
- `tests/test_database_schema_foundation.py`
- `tests/test_nex_cx_ingestion.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests verify source file terminology, no DB byte storage, date/hash
storage-key shape, generated stored filenames, safe extension handling, and
contract validation for updated upload registration records.
