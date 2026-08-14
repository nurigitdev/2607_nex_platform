# Slice 0282: CX Extraction Materialized-Source Fallback

## Scope

Implement the source-file reader fallback recorded by Slice 0281. CX extraction
must keep runtime source bytes as the fast path, but it must also survive
runtime memory eviction or background-worker process separation by reading the
verified materialized local source file.

## Implemented

- Added `source_bytes_for_extraction(...)` as the single memory/fallback reader
  boundary for `run_text_extraction_job(...)`.
- Added `read_verified_materialized_source_bytes(...)` for local filesystem
  fallback reads.
- The fallback only reads source bytes when source-file lineage exists,
  metadata is `local_filesystem`, checksum verification is present, storage key
  is safe and relative, the file exists, size matches, and SHA-256 matches.
- Extraction results now include redaction-safe `source_reader` metadata without
  storage keys, local filesystem paths, or raw source bytes.
- Updated the Slice 0281 audit so the runtime probe now reports
  `fallback_state=implemented`.

## Evidence

- CX ingestion regression:
  `./.venv/bin/pytest tests/test_nex_cx_ingestion.py tests/test_cx_source_file_reader_fallback_audit.py -q`
- Audit summary:
  `./.venv/bin/python scripts/smoke/run_cx_source_file_reader_fallback_audit.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
