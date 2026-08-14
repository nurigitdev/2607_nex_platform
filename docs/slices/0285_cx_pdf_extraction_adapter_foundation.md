# Slice 0285: CX PDF Extraction Adapter Foundation

## Scope

Close the first binary document extractor gap identified in Slice 0284 by
adding real PDF page-text extraction behind the existing
`nex_cx.extractors.TextExtractor` boundary. This keeps ingestion, persistence,
and later document-processing jobs on the same adapter contract while replacing
the PDF placeholder with deterministic Markdown output.

## Implemented

- Added the pinned `pypdf` parser dependency.
- Added `PDF_EXTRACTION_MODE = "pdf_to_markdown"` and
  `extract_pdf_markdown(...)` in `nex_cx.extractors`.
- Updated `LocalMockTextExtractor` so PDF inputs produce Markdown sections per
  extracted page instead of a placeholder body.
- Updated the extractor backend catalog and audit evidence:
  - Markdown, plain text, and PDF are real extraction paths.
  - DOCX, PPTX, and XLSX remain explicit placeholder gaps.
  - The next gap slice is now Slice 0286 for DOCX.
- Updated ingestion regression so PDF upload extraction writes real Markdown
  content through `run_text_extraction_job(...)`.

## Boundary

The PDF adapter extracts text from source bytes only, writes Markdown through
the existing extraction artifact path, and does not serialize raw source bytes
or local filesystem paths into audit evidence. PDFs without extractable text are
rejected with `cx.extractor_pdf_text_unavailable`, while malformed PDFs return
`cx.extractor_pdf_parse_failed`.

DOCX, PPTX, and XLSX intentionally remain placeholder gaps after this slice so
they can be implemented and tested one format family at a time.

## Evidence

- Audit:
  `./.venv/bin/python scripts/smoke/run_cx_extractor_backend_gap_audit.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_nex_cx_extractors.py tests/test_nex_cx_ingestion.py tests/test_cx_extractor_backend_gap_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
