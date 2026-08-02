# Slice 0028 CX Summary Embedding Index

Status: Implemented.

Backlog candidate: `S3-008` CX summary embedding index.

Requirement coverage: `CX-FR-003`, `MO-FR-001`, `TRACE-PLAT-001`.

## Scope

Slice 0028 adds a summary-level embedding path:

- `POST /api/v1/documents/{document_id}/summary-embedding/run` embeds the
  private document summary text through the MO embedding client.
- `GET /api/v1/documents/{document_id}/summary-embedding` returns public
  metadata.
- The public record stores summary hash, embedding hash, vector dimension,
  provider alias, model revision, deployment ID, and usage.
- Raw vectors and full summary text stay private in the mock store.
- Contract schema, success example, and negative vector leak example are
  registered in the contract quality gate.

## Files

- `services/nex-cx/nex_cx/summary_embeddings.py`
- `services/nex-cx/nex_cx/ingestion.py`
- `contracts/schemas/service/nex_cx/document_summary_embedding.v1.schema.json`
- `contracts/examples/retrieval/cx_document_summary_embedding.mock_success.json`
- `contracts/tests/negative/retrieval/cx_document_summary_embedding.vector_leak.json`
- `tests/test_nex_cx_summary_embeddings.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover MO client calls, private summary text lookup, vector
hashing, bad MO responses, provider errors, endpoint auth, readback, and
contract validation.
