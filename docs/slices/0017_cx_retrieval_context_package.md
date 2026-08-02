# Slice 0017 CX Retrieval Context Package

Status: Implemented.

Backlog candidate: `S2-007` CX retrieval context package endpoint.

Requirement coverage: `CX-RETRIEVAL-001`, `AE-CX-001`, `TRACE-PLAT-001`,
`CONTRACT-CX-001`.

## Scope

Slice 0017 adds the first CX-to-AE retrieval package surface:

- `POST /api/v1/retrieval/context` returns a retrieval context package.
- `GET /api/v1/retrieval/context/{retrieval_package_id}` reads a stored package.
- Retrieval uses lexical postings and embedding-index presence in a deterministic
  mock hybrid score.
- The package includes evidence items, permission snapshot, retrieval profile,
  source summary, score summary, warnings, package hash, and trace metadata.
- Status semantics start with `READY`, `NO_ANSWER`, and `LOW_CONFIDENCE`.

This slice does not apply reranking. The package explicitly marks rerank state
as `NOT_APPLIED`, leaving room for a later reranker provider pass.

## Contract Artifacts

- `contracts/schemas/service/nex_cx/retrieval_context_package.v1.schema.json`
- `contracts/examples/retrieval/cx_retrieval_context_package.mock_success.json`
- `contracts/tests/negative/retrieval/cx_retrieval_context_package.raw_token_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover package creation, readback, no-answer, low-confidence
status, scope validation, top-k bounds, permission snapshot defaults, score
summary, tokenizer fallback warnings, missing indexes, endpoint auth, and raw
token redaction.
