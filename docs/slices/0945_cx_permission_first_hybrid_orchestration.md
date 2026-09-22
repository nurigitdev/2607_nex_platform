# Slice 0945: CX Permission-First Hybrid Orchestration

## Goal

Enforce the S95 owner-private permission decision before query tokenization,
BM25 access, vector target admission, or private chunk candidate expansion.

## Implementation

- Validates the request bounds, then applies the canonical
  `cx.private_owner_active.v1` decision to the full explicit document scope.
  Missing, inactive, or cross-owner IDs stop the request with an
  indistinguishable not-found response before candidate stores are called.
- Builds the measured permission snapshot from the exact filter result and
  passes only visible content IDs to PostgreSQL BM25.
- Uses MeCab-ko query tokenization by default with `korean_mixed_v1` fallback,
  deduplicates normalized terms, and records the effective tokenizer profile.
- Selects vector targets only by visible document ID, requires target/content
  identity agreement, and delegates freshness and owner checks to the Slice
  0944 adapter.
- Revalidates lexical and vector candidate content lineage against the visible
  scope. Malformed or foreign candidate results fail closed with redacted
  orchestration errors.
- Returns separated lexical and vector candidate sets, a query hash, measured
  permission evidence, and explicit vector degradation state. Weighted RRF and
  authorized-text reranking remain Slice 0946 responsibilities.
- Adds no table, migration, route, or persistent row.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_hybrid_candidate_orchestration.py \
  tests/test_cx_permission_first_hybrid_orchestration.py \
  --cov=nex_cx.hybrid_candidate_orchestration \
  --cov=run_cx_permission_first_hybrid_orchestration \
  --cov-branch --cov-report=term-missing
```

Results:

- Focused regression: `41 passed`; both the orchestration module and contract
  runner reached 100% statement and branch coverage.
- Deterministic contract evidence: `9/9` checks passed.
- Full quality gate: `6968 passed`; repository statement coverage 98.87% and
  branch coverage 96.51%.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.

This deterministic Slice does not require PostgreSQL or remote providers, so
both remained disabled. The complete actual hybrid path is reserved for Slice
0949.
