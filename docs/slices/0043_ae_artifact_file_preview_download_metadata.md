# Slice 0043 AE Artifact File Preview Download Metadata

Status: Implemented.

Backlog candidate: `S5-003` AE artifact file preview and download metadata.

Requirement coverage: `AEAPI-FR-004`, `AEAPI-FR-005`, `AEAPI-FR-006`,
`AEWEB-FR-004`, `AG-FR-002`, `AG-FR-003`, `TRACE-AE-001`, `TRACE-GEN-001`.

## Scope

Slice 0043 materializes the Markdown renderer output as AE-owned file and link
metadata:

- Markdown artifact file metadata with safe `ae://` storage refs.
- Owner-only preview and download link records attached to the artifact record.
- `GET /api/v1/artifact-files/{artifact_file_id}` metadata read API.
- `GET /api/v1/artifact-files/{artifact_file_id}/preview` preview payload API.
- `GET /api/v1/artifact-files/{artifact_file_id}/download` download payload API.
- Contract example that exercises populated `files` and `links` arrays in
  `ae_artifact_record.v1`.

The slice still avoids local filesystem writes. File metadata is public and
path-safe; generated Markdown content remains in private runtime storage and is
served only through authorized AE preview/download routes.

## Files

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `services/nex-ae-api/README.md`
- `contracts/examples/generation/ae_artifact_record.markdown_file_ready.json`
- `contracts/examples/index.json`
- `contracts/openapi/nex-ae-api.openapi.yaml`
- `tests/test_nex_ae_artifacts.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover safe file name generation, `ae://` storage refs,
preview/download route creation, public artifact metadata readback, authorized
preview/download payloads, missing file handling, missing link handling, not
ready content handling, and raw local path exclusion.
