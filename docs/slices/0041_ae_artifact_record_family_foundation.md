# Slice 0041 AE Artifact Record Family Foundation

Status: Implemented.

Backlog candidate: `S5-001` AE artifact record family foundation.

Requirement coverage: `AEAPI-FR-004`, `AEAPI-FR-005`, `AEAPI-FR-006`,
`AG-FR-002`, `AG-FR-003`, `TRACE-AE-001`, `TRACE-GEN-001`.

## Scope

Slice 0041 creates the first AE-owned artifact record family on top of the
validated handoff contract from Slice 0038:

- `ae_artifact_record.v1` JSON Schema for root artifacts, source refs,
  versions, render jobs, rendered files, preview/download links, and template
  refs.
- Positive and negative contract fixtures, including a raw local storage path
  leak guard for future file metadata.
- AE artifact creation/read APIs:
  `/api/v1/artifacts`,
  `/api/v1/artifacts/{artifact_id}`, and
  `/api/v1/artifacts/{artifact_id}/versions`.
- In-memory artifact record store with idempotent create semantics.
- Handoff validation guards before an artifact shell is created.

This slice intentionally stops before Markdown/HTML rendering. New artifact
records are `DRAFT` shells with source refs and empty version, render job, file,
and link arrays. Later slices fill those arrays without changing the root
record boundary.

## Files

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `services/nex-ae-api/README.md`
- `contracts/schemas/generation/ae_artifact_record.v1.schema.json`
- `contracts/examples/generation/ae_artifact_record.mock_success.json`
- `contracts/tests/negative/generation/ae_artifact_record.storage_path_leak.json`
- `contracts/openapi/nex-ae-api.openapi.yaml`
- `tests/test_nex_ae_artifacts.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover artifact record construction, safe source refs, empty
render family arrays, idempotent route create/readback, version listing,
authentication, missing handoff/artifact errors, invalid artifact type, invalid
handoff state, missing handoff fields, and raw local path exclusion.
