# Slice 0072 CX Text Extraction Adapter Foundation

Status: Implemented.

Backlog candidate: `S7-002` CX text extraction adapter foundation.

Requirement coverage: `CX-FR-002`, `CX-INGEST-001`, `TRACE-CONTENT-001`,
`PLAT-FR-007`.

## Scope

Slice 0072 moves extraction behavior behind an explicit CX extractor adapter
boundary.

- `nex_cx.extractors` defines extractor input/output records, a protocol, source
  type classification, UTF-8 text decoding, and the default local mock adapter.
- Markdown and plain text sources are converted from source bytes into normalized
  Markdown.
- PDF, DOCX, PPTX, and XLSX are recognized by content type or extension, but the
  current local adapter emits a deterministic placeholder with a warning instead
  of pretending to perform real extraction.
- Unsupported binary files fail with `415 cx.extractor_source_type_unsupported`.
- Non-UTF-8 text sources fail with
  `415 cx.extractor_source_encoding_unsupported`.

## Adapter Boundary

The public extraction result records:

- extractor provider, mode, version, and source format
- extraction warnings
- Markdown hash, path, char count, and preview

Raw source bytes remain outside public records. Real extractor backends can
replace the local mock adapter without changing the ingestion job endpoint.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_cx_extractors.py tests/test_nex_cx_ingestion.py
scripts/quality/run_quality_gate.sh
```
