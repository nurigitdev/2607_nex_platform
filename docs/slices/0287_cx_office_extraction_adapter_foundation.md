# Slice 0287: CX Office Extraction Adapter Foundation

## Scope

Close the remaining PPTX and XLSX extractor gaps from Slice 0286. The
implementation stays behind `nex_cx.extractors.TextExtractor`, preserving the
existing upload extraction and processing contract while replacing all remaining
binary placeholders with real local adapters.

## Implemented

- Added pinned `python-pptx` and `openpyxl` parser dependencies.
- Added `PPTX_EXTRACTION_MODE = "pptx_to_markdown"` and
  `XLSX_EXTRACTION_MODE = "xlsx_to_markdown"`.
- Added `extract_pptx_markdown(...)` for slide text and simple slide tables.
- Added `extract_xlsx_markdown(...)` for worksheet rows rendered as Markdown
  tables.
- Shared Markdown table rendering across DOCX/PPTX/XLSX extraction helpers.
- Updated the extractor backend catalog and audit evidence so all six supported
  source formats are real extraction paths:
  Markdown, plain text, PDF, DOCX, PPTX, and XLSX.
- Updated ingestion regression so PPTX and XLSX uploads write real Markdown
  through `run_text_extraction_job(...)`.

## Boundary

The Office adapters consume only uploaded source bytes and emit Markdown plus
metadata through the existing extraction result boundary. Raw source bytes and
local filesystem paths stay out of audit evidence. Malformed Office documents
return typed parse errors; documents without extractable text/cells return
typed unavailable-text errors.

Slice 0288 should run a PostgreSQL-backed smoke evidence path with real
document extraction persisted through `nex_cx_test`.

## Evidence

- Audit:
  `./.venv/bin/python scripts/smoke/run_cx_extractor_backend_gap_audit.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_nex_cx_extractors.py tests/test_nex_cx_ingestion.py tests/test_cx_extractor_backend_gap_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
