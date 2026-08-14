# Slice 0290: CX Real Document Processing Pipeline PostgreSQL Smoke

## Scope

Add protected PostgreSQL smoke evidence that real PDF, DOCX, PPTX, and XLSX
documents can run through the full CX document processing pipeline against the
`nex_cx_test` database.

This extends Slice 0288 from extraction-only proof to end-to-end processing:
extraction, chunking, lexical index, embedding index, summary, summary
embedding, durable processing run, and durable job lifecycle.

## Implemented

- Added
  `scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py`.
- The smoke is guarded by
  `NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_POSTGRES_SMOKE=1` and only allows
  the `test` profile.
- The smoke migrates the CX test database before execution.
- It uploads generated PDF/DOCX/PPTX/XLSX files through the CX upload route.
- It evicts runtime source bytes before processing so extraction must read the
  verified materialized source file.
- It runs `/api/v1/documents/{document_id}/processing/run` for each format.
- It verifies PostgreSQL rows for:
  - source checksum metadata;
  - extraction artifact;
  - chunk set and chunks;
  - lexical terms and postings;
  - chunk embeddings;
  - document summary and summary embedding;
  - processing run and six processing steps;
  - completed durable `service_jobs` row.
- Evidence keeps raw source bytes, extracted Markdown path, and private marker
  text out of the public smoke result.
- Wired the skipped-by-default smoke into the full quality gate.

## Live Test Command

```bash
NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:nuri1004@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py --summary
```

## Evidence

- Protected PostgreSQL smoke:
  `./.venv/bin/python scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py --summary`
- Python regression:
  `./.venv/bin/pytest tests/test_cx_real_document_processing_pipeline_postgres_smoke.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
