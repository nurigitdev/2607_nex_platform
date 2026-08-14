# Slice 0288: CX Real Document Extraction PostgreSQL Smoke

## Scope

Add protected PostgreSQL smoke evidence for the real document extraction
adapters completed in Slice 0285 through Slice 0287. This slice proves that
PDF, DOCX, PPTX, and XLSX uploads can be materialized, extracted through the job
API, and persisted to `cx_extraction_artifacts` against `nex_cx_test`.

## Implemented

- Added `scripts/smoke/run_cx_real_document_extraction_postgres_smoke.py`.
- The smoke is guarded by
  `NEX_CX_REAL_DOCUMENT_EXTRACTION_POSTGRES_SMOKE=1` and only allows the `test`
  profile.
- The smoke migrates the CX test database before execution.
- It uploads four real generated document files:
  PDF, DOCX, PPTX, and XLSX.
- It evicts runtime source bytes so extraction must read the verified
  materialized source file.
- It verifies:
  - each extractor mode matches the source format;
  - private marker text appears only in the private Markdown file;
  - source checksums are verified in `cx_source_files`;
  - one `cx_extraction_artifacts` row is persisted per uploaded document;
  - evidence excludes raw source text, local storage paths, and source storage
    path fields.
- Added regression tests with SQLite route execution and protected smoke guard
  behavior.
- Wired the skipped-by-default smoke into the full quality gate.

## Live Test Command

```bash
NEX_CX_REAL_DOCUMENT_EXTRACTION_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:nuri1004@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_cx_real_document_extraction_postgres_smoke.py --summary
```

## Evidence

- Protected PostgreSQL smoke:
  `./.venv/bin/python scripts/smoke/run_cx_real_document_extraction_postgres_smoke.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_cx_real_document_extraction_postgres_smoke.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
