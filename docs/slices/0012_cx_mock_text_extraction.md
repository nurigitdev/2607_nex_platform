# Slice 0012 CX Mock Text Extraction

Status: Implemented.

Backlog candidate: `S2-002` CX mock text extraction to Markdown.

Requirement coverage: `CX-INGEST-001`, `CX-EXTRACT-001`, `TRACE-PLAT-001`,
`CONTRACT-CX-001`.

## Scope

Slice 0012 turns a queued ingestion job into an extracted Markdown artifact in
the local mock profile:

- `POST /api/v1/jobs/{job_id}/run` executes mock extraction.
- `GET /api/v1/documents/{document_id}/extraction` reads extraction metadata.
- Registered `content_text` is kept private in the in-memory store and is not
  returned in upload or extraction API responses.
- Extracted Markdown is written to `NEX_CX_EXTRACTED_MARKDOWN_ROOT`.
- The extraction result records source hash, extracted Markdown hash, path,
  character count, preview, extractor mode, request ID, and trace ID.

The mock extractor supports two deterministic conversions:

- Markdown input is normalized with a trailing newline.
- Non-Markdown text is wrapped with a heading based on the registered filename.

## Contract Artifacts

- `contracts/schemas/service/nex_cx/text_extraction.v1.schema.json`
- `contracts/examples/retrieval/cx_text_extraction.mock_success.json`
- `contracts/tests/negative/retrieval/cx_text_extraction.raw_text_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

The regression tests cover successful materialization, readback, missing auth,
unknown jobs, missing registered documents, missing source text, blank source
normalization, and raw-text response redaction.
