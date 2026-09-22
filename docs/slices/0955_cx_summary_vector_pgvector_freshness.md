# Slice 0955: CX Summary Vector pgvector Persistence and Freshness

## Goal

Persist private document-summary vectors in PostgreSQL/pgvector and admit them
only while their owner, summary, embedding profile, digest, and dimension match
the current metadata lineage.

## Implementation

- Adds the short `cx_summary_vectors` payload table rather than weakening the
  chunk-only `cx_vectors` manifest boundary.
- Keeps `cx_document_summary_embeddings` as the public metadata authority and
  stores the raw vector only in the private pgvector table.
- Enforces ACTIVE content plus READY summary/embedding state, exact tenant and
  owner lineage, source summary SHA-256, model profile, vector SHA-256, and
  vector dimension in both application and database boundaries.
- Adds an immutable, owner-bound summary pgvector adapter implementing the
  existing private vector capability for one document summary.
- Emits explicit freshness reasons and permits use only when all current
  lineage values match the persisted payload.
- Adds a partial HNSW cosine index for the canonical
  `Qwen3-Embedding-4B` 2560-dimension profile.

This Slice validates SQL shape and adapter behavior with deterministic session
doubles. It does not migrate `nex_cx_test` or call the remote embedding
provider; those protected checks remain assigned to Slice 0959.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_summary_pgvector_store.py \
  tests/test_cx_summary_vector_pgvector.py \
  --cov=nex_cx.summary_pgvector_store \
  --cov=run_cx_summary_vector_pgvector \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_summary_vector_pgvector.py --summary
```

Observed on 2026-09-22:

- Focused summary-vector suite: 35 passed; adapter and evidence runner
  statement/branch coverage 100%.
- Related migration and summary regression: 107 passed.
- Deterministic pgvector evidence: 10/10 checks passed.
- Full regression: 7,245 passed; quality gate exit 0.
- Full coverage: 98.89% statements and 96.58% branches.
- Contract validation: 85 JSON Schema files, 136 examples, 101 negative
  examples, and 7 OpenAPI documents passed.
