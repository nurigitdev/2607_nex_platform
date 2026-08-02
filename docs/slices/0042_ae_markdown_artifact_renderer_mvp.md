# Slice 0042 AE Markdown Artifact Renderer MVP

Status: Implemented.

Backlog candidate: `S5-002` AE Markdown artifact renderer MVP.

Requirement coverage: `AEAPI-FR-004`, `AEAPI-FR-005`, `AEAPI-FR-006`,
`AG-FR-002`, `AG-FR-003`, `TRACE-AE-001`, `TRACE-GEN-001`.

## Scope

Slice 0042 adds the first synchronous AE render path:

- Markdown renderer over CX `cx_structured_draft.v1` safe preview blocks.
- `POST /api/v1/artifacts/{artifact_id}/render-jobs` for Markdown render job
  creation.
- `GET /api/v1/artifact-render-jobs/{render_job_id}` for render job readback.
- Artifact version creation with render policy hash, artifact content hash,
  source draft hash, citation hash, and validation snapshot.
- Private in-memory Markdown payload storage keyed by artifact version ID.
- Idempotent render job creation via `Idempotency-Key` or `render_request_id`.

Public artifact records expose version and render job metadata only. Markdown
content is not returned through the artifact record API in this slice; file,
preview, and download metadata are left to Slice 0043.

## Files

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `services/nex-ae-api/README.md`
- `contracts/examples/generation/ae_artifact_record.markdown_ready.json`
- `contracts/examples/index.json`
- `contracts/openapi/nex-ae-api.openapi.yaml`
- `tests/test_nex_ae_artifacts.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover Markdown formatting, citation rendering, completed
render job metadata, version lineage, private Markdown storage, route
idempotency, render job readback, missing artifact/job handling, required render
request IDs, unsupported formats, unrequested Markdown output, invalid draft
status, citation failure, source draft ID/hash mismatch, and archived artifact
guards.
