# Slice 0025 CX User-Scoped Duplicate Upload Guard

Status: Implemented.

Backlog candidate: `S3-005` CX owner-scoped upload dedupe.

Requirement coverage: `CX-FR-001`, `CX-FR-002`, `TRACE-PLAT-001`.

## Scope

Slice 0025 applies the multi-user duplicate upload rule in the mock CX ingestion
flow:

- Upload registration accepts `tenant_id` and `owner_user_id`, defaulting to the
  local mock owner when omitted.
- `document_id` is scoped to `tenant_id + owner_user_id + source_sha256`.
- Source file storage keys use the global `source_file_id`, so different owners
  can point to the same stored source bytes without sharing a logical document.
- A same-owner duplicate returns the existing document registration with
  `dedupe.status = ALREADY_EXISTS` and HTTP 200.
- A different-owner upload of the same bytes returns `CREATED` and does not
  expose whether another owner already uploaded the file.

The public upload registration contract now includes `ownership` and `dedupe`
metadata. Raw source text remains private to the mock extraction path.

## Files

- `services/nex-cx/nex_cx/ingestion.py`
- `services/nex-cx/nex_cx/repository.py`
- `contracts/schemas/service/nex_cx/upload_registration.v1.schema.json`
- `contracts/examples/retrieval/cx_upload_registration.mock_success.json`
- `tests/test_nex_cx_ingestion.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover owner-scoped document IDs, global source storage key
reuse, same-owner duplicate response behavior, different-owner privacy, and
contract validation for the expanded upload registration shape.
