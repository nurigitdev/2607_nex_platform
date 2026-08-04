# Slice 0073 CX Document Processing Pipeline Job

Status: Implemented.

Backlog candidate: `S7-003` CX document processing pipeline job.

Requirement coverage: `CX-FR-001`, `CX-FR-002`, `CX-FR-003`,
`TRACE-CONTENT-001`, `PLAT-FR-007`.

## Scope

Slice 0073 adds an idempotent CX document processing pipeline over the existing
mock-first document stages.

Pipeline order:

1. extraction
2. chunking
3. lexical index
4. embedding index
5. document summary
6. summary embedding

Each step reuses the existing implementation function. If a step output already
exists, the pipeline records that step as `SKIPPED` and continues. This gives AE
and future operators one stable processing command without losing the narrower
per-step APIs.

## API

- `POST /api/v1/documents/{document_id}/processing/run`
- `GET /api/v1/documents/{document_id}/processing`

The pipeline response stores safe output references only. It does not expose raw
source bytes, chunk text, summary text, provider endpoint URLs, or API keys.

Failed runs are saved with the failed step and a safe error summary; problem
responses include only the pipeline run ID, failed step, and step counts.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_cx_processing.py tests/test_nex_cx_ingestion.py tests/test_nex_cx_chunking.py tests/test_nex_cx_lexical_index.py tests/test_nex_cx_embedding_index.py tests/test_nex_cx_summaries.py tests/test_nex_cx_summary_embeddings.py
scripts/quality/run_quality_gate.sh
```
