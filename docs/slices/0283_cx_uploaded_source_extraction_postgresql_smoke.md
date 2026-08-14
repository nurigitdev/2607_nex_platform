# Slice 0283: CX Uploaded Source Extraction PostgreSQL Smoke

## Scope

Add protected smoke evidence for the Slice 0282 fallback against a real
`nex_cx_test` database. The smoke must migrate the CX test schema, upload source
content through the CX API, evict runtime source bytes, run extraction through
the job API, and prove the extraction artifact is persisted while evidence
stays redaction-safe.

## Implemented

- Added `scripts/smoke/run_cx_uploaded_source_extraction_postgres_smoke.py`.
- The smoke is opt-in through
  `NEX_CX_UPLOADED_SOURCE_EXTRACTION_POSTGRES_SMOKE=1` and only allows the
  `test` profile for write execution.
- The execution path verifies:
  - CX persistence runtime is PostgreSQL-backed;
  - migrations run before the write smoke;
  - upload creates a checksum-verified source file row;
  - runtime source bytes are evicted before extraction;
  - extraction uses the `materialized_local_source_file` reader;
  - `cx_extraction_artifacts` contains the Markdown artifact row;
  - smoke evidence omits raw source text and local storage paths.

## Evidence

- Protected PostgreSQL smoke:
  `NEX_CX_UPLOADED_SOURCE_EXTRACTION_POSTGRES_SMOKE=1 ./.venv/bin/python scripts/smoke/run_cx_uploaded_source_extraction_postgres_smoke.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_cx_uploaded_source_extraction_postgres_smoke.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
