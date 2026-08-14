# Slice 0281: CX Source-File Reader Fallback Audit

## Scope

Freeze the extraction durability gap after verified source-file upload. Slice
0280 proved uploaded bytes can become an extraction artifact while the runtime
still has source bytes in memory. This slice records that production-safe
extraction must also read the verified materialized source file after runtime
memory is cleared or a background worker executes in another process.

## Implemented

- Added `scripts/smoke/run_cx_source_file_reader_fallback_audit.py`.
- The audit verifies the current memory-first extraction reader, source-file
  metadata, checksum verification inputs, and previous Slice 0280 readiness
  record.
- The in-memory gap probe materializes uploaded source bytes, evicts runtime
  source bytes, and confirms current extraction reports
  `cx.source_content_unavailable` while the verified local source file remains
  available.
- Evidence is redaction-safe: no raw source bytes, protected environment
  values, database URLs, passwords, provider endpoints, temp paths, or local
  storage paths are serialized.

## Decision

Slice 0282 should add a verified local source-file reader fallback to
`run_text_extraction_job(...)`: keep memory source bytes as the fast path, then
read the materialized source file only when source metadata is local,
checksum-verified, safely keyed, present on disk, and hash-matching.

## Evidence

- Audit summary:
  `./.venv/bin/python scripts/smoke/run_cx_source_file_reader_fallback_audit.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_cx_source_file_reader_fallback_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
