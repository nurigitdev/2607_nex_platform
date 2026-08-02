# Slice 0026 CX Local Source File Materialization

Status: Implemented.

Backlog candidate: `S3-006` CX local source file materialization.

Requirement coverage: `CX-FR-001`, `CX-FR-002`, `QA-FR-001`.

## Scope

Slice 0026 makes the mock upload path write original source bytes to local
storage when `content_text` is supplied:

- Writes source bytes to the generated local source storage path.
- Verifies the bytes against `source_sha256` before storing.
- Treats an existing matching source file as idempotent.
- Rejects unsafe storage keys, non-absolute local paths, unsupported backends,
  and checksum collisions.
- Marks the private source file repository record with `checksum_verified_at`.

Tests use temporary directories instead of `/data/nex-platform`; local
development can continue to use the configured `/data` roots.

## Files

- `services/nex-cx/nex_cx/ingestion.py`
- `services/nex-cx/nex_cx/repository.py`
- `tests/test_nex_cx_ingestion.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover source file writes, checksum verification, idempotent
existing-file handling, unsafe metadata rejection, collision detection, and
endpoint-level source file materialization.
