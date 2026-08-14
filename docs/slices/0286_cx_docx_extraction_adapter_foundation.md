# Slice 0286: CX DOCX Extraction Adapter Foundation

## Scope

Close the DOCX extractor gap identified by the backend catalog after Slice 0285.
The adapter stays behind `nex_cx.extractors.TextExtractor`, so upload ingestion,
extraction artifact persistence, and processing jobs continue to use the same
source-byte-to-Markdown contract.

## Implemented

- Added the pinned `python-docx` parser dependency.
- Added `DOCX_EXTRACTION_MODE = "docx_to_markdown"` and
  `extract_docx_markdown(...)` in `nex_cx.extractors`.
- Converted DOCX paragraphs and simple tables into Markdown.
- Updated `LocalMockTextExtractor` so DOCX inputs produce real Markdown instead
  of placeholder output.
- Updated the extractor backend catalog and audit evidence:
  - Markdown, plain text, PDF, and DOCX are real extraction paths.
  - PPTX and XLSX remain explicit placeholder gaps for Slice 0287.
- Updated ingestion regression so DOCX upload extraction writes real Markdown
  content through `run_text_extraction_job(...)`.

## Boundary

DOCX extraction consumes only uploaded source bytes and emits Markdown plus
metadata through the existing extraction result boundary. Raw source bytes and
local filesystem paths stay out of audit evidence. Malformed DOCX files return
`cx.extractor_docx_parse_failed`; DOCX files without extractable paragraph or
table text return `cx.extractor_docx_text_unavailable`.

PPTX and XLSX remain deferred to Slice 0287 so the remaining Office extraction
surface can be implemented and tested together.

## Evidence

- Audit:
  `./.venv/bin/python scripts/smoke/run_cx_extractor_backend_gap_audit.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_nex_cx_extractors.py tests/test_nex_cx_ingestion.py tests/test_cx_extractor_backend_gap_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
