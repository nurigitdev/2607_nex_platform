# Slice 0289: CX Extracted Markdown Normalization Contract

## Scope

Harden the Markdown artifact boundary after the real PDF, DOCX, PPTX, and XLSX
extractors. This slice keeps raw extracted text out of public records while
making the normalized Markdown shape visible through redaction-safe metadata.

## Implemented

- Added `cx_extracted_markdown_normalization.v1` metadata from
  `nex_cx.extractors`.
- Normalized extractor Markdown output before storage:
  - CRLF/CR line endings become LF;
  - trailing spaces and tabs are removed per line;
  - a final newline is guaranteed.
- Added extractor contract validation for:
  - supported `source_format`;
  - source-format-specific extraction mode;
  - non-empty provider/version;
  - H1 title for plain-text and binary extraction outputs;
  - required `Page`, `Slide`, or `Sheet` section headings for PDF, PPTX, and
    XLSX outputs;
  - non-empty warning strings.
- `run_text_extraction_job(...)` now includes
  `extracted_markdown_normalization` with counts and booleans only. The raw
  Markdown body remains in the private extracted Markdown file path.
- Hardened `cx_text_extraction.v1` to require:
  - extractor `source_format`;
  - source reader redaction metadata;
  - warning list;
  - normalized Markdown metadata.

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_nex_cx_extractors.py tests/test_nex_cx_ingestion.py tests/test_contract_validation.py -q`
- Contract validation:
  `PYTHONPATH=scripts/quality ./.venv/bin/python scripts/quality/validate_contracts.py contracts`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
