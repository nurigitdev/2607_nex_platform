# Slice 0284: CX Extractor Backend Gap Audit

## Scope

Freeze the CX extractor backend state before adding real PDF, DOCX, PPTX, and
XLSX adapters. Slice 0283 proved durable uploaded-source extraction against
`nex_cx_test`; this slice makes the remaining extractor gaps explicit so the
next slices can close them without changing the ingestion job boundary.

## Implemented

- Added an explicit `ExtractorBackendCapability` catalog in
  `nex_cx.extractors`.
- Centralized source-format groups and binary placeholder mode/warning
  constants.
- Added `extractor_backend_catalog()` and `extractor_backend_gap_summary()` so
  audit and operator/debug surfaces can distinguish implemented text extraction
  from placeholder binary document handling.
- Added `scripts/smoke/run_cx_extractor_backend_gap_audit.py`.
- The audit verifies:
  - Markdown and plain text use real local conversion;
  - PDF, DOCX, PPTX, and XLSX are recognized but still placeholder gaps;
  - placeholder warnings are stable;
  - unsupported binary input still fails with a typed extraction error;
  - raw source bytes, protected env values, and local paths are absent from
    evidence.

## Decision

Keep extractor selection behind `nex_cx.extractors.TextExtractor`. Slice 0285
should close the PDF gap first, Slice 0286 should close the DOCX gap, and Slice
0287 should decide and harden the PPTX/XLSX Office extraction boundary.

## Evidence

- Audit:
  `./.venv/bin/python scripts/smoke/run_cx_extractor_backend_gap_audit.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_nex_cx_extractors.py tests/test_cx_extractor_backend_gap_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
