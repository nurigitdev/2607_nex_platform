# Slice 0011 CX Upload Registration Ingestion Job

Status: Implemented.

Backlog candidate: `S2-001` CX upload registration and ingestion job shell.

Requirement coverage: `CX-INGEST-001`, `TRACE-PLAT-001`, `CONTRACT-CX-001`.

## Scope

Slice 0011 adds the first CX content ingestion surface:

- `POST /api/v1/documents/uploads` registers uploaded document metadata.
- `GET /api/v1/documents/{document_id}` reads the registration record.
- `GET /api/v1/jobs/{job_id}` reads the queued ingestion job shell.
- CX records source file, extracted Markdown, and extraction temp paths under
  `/data/nex-platform` defaults.
- The record carries chunk policy `chunk_1000_100`, chunk size `1000`, overlap
  `100`, BM25 tokenizer `mecab_ko`, and fallback `korean_mixed_v1`.

This slice intentionally does not parse files or write extracted Markdown. It
creates a traceable, contract-tested registration and job boundary for the next
extraction slice.

## Runtime Defaults

```text
NEX_DATA_ROOT=/data/nex-platform
NEX_CX_SOURCE_STORAGE_ROOT=/data/nex-platform/cx/source-files
NEX_CX_EXTRACTED_MARKDOWN_ROOT=/data/nex-platform/cx/extracted-markdown
NEX_CX_EXTRACTION_TEMP_ROOT=/data/nex-platform/cx/extraction-temp
NEX_CX_DEFAULT_CHUNK_POLICY=chunk_1000_100
NEX_CX_CHUNK_SIZE=1000
NEX_CX_CHUNK_OVERLAP=100
NEX_CX_BM25_TOKENIZER=mecab_ko
NEX_CX_BM25_TOKENIZER_FALLBACK=korean_mixed_v1
```

Model-provider defaults remain mock-first until DGX-spark is reachable.

## Contract Artifacts

- `contracts/schemas/common/common_job.v1.schema.json`
- `contracts/schemas/service/nex_cx/upload_registration.v1.schema.json`
- `contracts/examples/retrieval/common_job.ingestion_queued.json`
- `contracts/examples/retrieval/cx_upload_registration.mock_success.json`
- `contracts/tests/negative/retrieval/common_job.bad_status.json`
- `contracts/tests/negative/retrieval/cx_upload_registration.path_traversal.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

The test set includes explicit branch coverage for missing service claims,
unknown document/job reads, unsafe filenames, invalid hash and size fields,
and storage configuration defaults/overrides.
