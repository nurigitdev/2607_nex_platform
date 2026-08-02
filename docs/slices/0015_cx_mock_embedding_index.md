# Slice 0015 CX Mock Embedding Index

Status: Implemented.

Backlog candidate: `S2-005` CX mock embedding index job.

Requirement coverage: `CX-EMBED-001`, `MO-PROVIDER-001`, `TRACE-PLAT-001`,
`CONTRACT-CX-001`.

## Scope

Slice 0015 connects CX chunk sets to MO embedding generation:

- `POST /api/v1/documents/{document_id}/embeddings/run` builds an embedding
  index from private chunk text.
- `GET /api/v1/documents/{document_id}/embeddings` reads embedding index
  metadata.
- The default alias is `mock-embedding-default`.
- The default HTTP client uses `NEX_MO_BASE_URL` and
  `NEX_CX_TO_MO_SERVICE_TOKEN`, falling back to mock service-token issuance.
- API responses expose vector dimension and embedding hash, not raw vectors.
- Raw embedding vectors remain private in the local in-memory store.

## Contract Artifacts

- `contracts/schemas/service/nex_cx/embedding_index.v1.schema.json`
- `contracts/examples/retrieval/cx_embedding_index.mock_success.json`
- `contracts/tests/negative/retrieval/cx_embedding_index.vector_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover MO client calls, HTTP token forwarding, MO failure
propagation, invalid embedding responses, missing chunk sets, missing private
chunk text, endpoint auth, API readback, and vector redaction.
