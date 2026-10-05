# Slice 1358: CX Retrieval Operations Evidence

## Goal

Make hybrid retrieval success and provider failures actionable from operations
events without persisting private retrieval payloads.

## Implementation

- Advanced metadata-only retrieval operations events to
  `cx_retrieval_observability.v2`.
- Added confidence policy, bucket, reason, best score, and threshold evidence.
- Added BM25, vector, and fused candidate counts.
- Added safe embedding and reranker alias, model revision, and deployment ID.
- Classified failure events by embedding, reranker, vector search, lexical
  search, private evidence, candidate pipeline, or persistence role.
- Kept endpoint URLs, credentials, query text, document IDs, vectors, and
  private chunk text out of emitted details.

No table, migration, route, or remote-provider request was added.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_retrieval_observability.py \
  --test tests/test_cx_retrieval_operations_observability.py \
  --coverage-target services/nex-cx/nex_cx/retrieval_observability.py \
  --coverage-target scripts/smoke/run_cx_retrieval_operations_observability.py \
  --smoke scripts/smoke/run_cx_retrieval_operations_observability.py
```

Observed result: `2348 passed`; statement coverage `99.08%`, branch coverage
`98.18%`, and both changed observability targets at 100% statement and branch
coverage.
