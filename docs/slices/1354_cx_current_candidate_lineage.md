# Slice 1354: CX Current Candidate Lineage

## Goal

Keep PostgreSQL BM25 candidates on the same current chunk generation used by
fresh pgvector retrieval.

## Implementation

- BM25 now selects exactly the latest `cx_chunk_sets` row per content object,
  ordered by `created_at` and stable `chunk_set_id` tie-breaker.
- Older lexical terms and postings remain durable history but cannot become
  active retrieval candidates after a document is reprocessed.
- Added protected PostgreSQL evidence that seeds stale and current generations,
  rejects the stale token, returns only the current chunk, enforces owner scope,
  and leaves no fixture residue.
- The vector freshness guard continues to compare the current source snapshot;
  the two candidate channels now share the same generation boundary.

No table or migration was added.

## Verification

```bash
NEX_CX_CURRENT_CHUNK_CANDIDATE_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://.../nex_cx_test' \
./.venv/bin/python \
  scripts/smoke/run_cx_current_chunk_candidate_postgres_smoke.py --summary

scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_current_chunk_candidate_postgres_smoke.py \
  --coverage-target services/nex-cx/nex_cx/lexical_candidates.py \
  --coverage-target scripts/smoke/run_cx_current_chunk_candidate_postgres_smoke.py
```
