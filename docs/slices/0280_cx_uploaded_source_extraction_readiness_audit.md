# Slice 0280: CX Uploaded Source Extraction Readiness Audit

## Scope

Freeze the readiness checkpoint between verified browser source-file upload and
the CX extraction/processing pipeline. This slice does not require remote
providers; it proves the local source bytes captured by upload can become a
redaction-safe extraction artifact.

## Implemented

- Added `scripts/smoke/run_cx_uploaded_source_extraction_readiness_audit.py`.
- The audit checks static boundaries for:
  - captured source bytes in `ContentIngestionStore`;
  - `run_text_extraction_job(...)` source-byte requirements;
  - safe failure when source bytes are unavailable;
  - extracted Markdown write-through;
  - extraction artifact persistence;
  - processing pipeline entry through the extraction job boundary;
  - deterministic local extractor behavior;
  - Slice 0279 verified source-file upload evidence.
- Added an in-memory runtime probe that registers uploaded source bytes,
  materializes the source file, runs extraction, writes Markdown, and verifies
  one extraction artifact without serializing raw source text or local paths.
- Wired the audit into the full quality gate.

## Evidence

- Audit summary:
  `./.venv/bin/python scripts/smoke/run_cx_uploaded_source_extraction_readiness_audit.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_cx_uploaded_source_extraction_readiness_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
