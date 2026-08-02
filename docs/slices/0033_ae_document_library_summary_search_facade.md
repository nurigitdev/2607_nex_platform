# Slice 0033 AE Document Library Summary Search Facade

Status: Implemented.

Backlog candidate: `S4-003` AE document library and summary search facade.

Requirement coverage: `AEAPI-FR-001`, `AEWEB-FR-003`, `AEWEB-FR-004`,
`TRACE-CONTENT-001`.

## Scope

Slice 0033 adds AE read facades for workspace document UX:

- `GET /api/v1/workspaces/{workspace_id}/documents`
- `GET /api/v1/documents/summary-search`
- CX document, summary, and summary embedding status aggregation.
- Mock lexical search over filename, summary preview, and summary status.
- `ae_document_library_item.v1` contract with raw summary/path leak guard.

AE does not take ownership of CX source files, Markdown artifacts, chunks,
summary text, vectors, or storage paths. It assembles a safe user-facing read
model from AE upload handoff refs plus CX APIs.

## Files

- `services/nex-ae-api/nex_ae_api/documents.py`
- `services/nex-ae-api/nex_ae_api/uploads.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `contracts/schemas/service/nex_ae_api/document_library_item.v1.schema.json`
- `tests/test_nex_ae_documents.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover safe document projections, missing summaries, summary
embedding metadata, lexical match ordering, endpoint auth, empty workspace
listing, and CX error propagation.
