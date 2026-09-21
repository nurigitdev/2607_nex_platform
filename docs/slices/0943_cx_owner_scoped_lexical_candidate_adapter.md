# Slice 0943: CX Owner-Scoped Lexical Candidate Adapter

## Goal

Replace term-coverage scoring at the persistent retrieval boundary with an
owner-scoped PostgreSQL BM25 candidate adapter.

## Implementation

- Reuses `cx_chunks`, `cx_lexical_terms`, and `cx_lexical_postings`; no new
  table or migration is required.
- The first query stage admits only ACTIVE content matching the authenticated
  tenant and owner subject. Corpus statistics are therefore calculated only
  over authorized chunks.
- Computes standard BM25 with configurable `k1` (`1.2`) and `b` (`0.75`) from
  posting term frequency, owner-scoped document frequency, chunk length, and
  average authorized chunk length.
- Supports an explicit authorized content-ID scope or all owner documents,
  bounded query terms, deduplication, and deterministic score/ordinal/ID order.
- Returns metadata and bounded text preview only. Loading private full text for
  reranking remains a later permission-first orchestration step.
- Database failures are converted to a redacted CX error.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_lexical_candidates.py \
  tests/test_cx_lexical_candidate_postgres_smoke.py
```

Observed on 2026-09-22:

- Focused adapter/smoke suite: `26 passed`; new adapter and smoke runner
  statement/branch coverage `100%`.
- Actual `nex_cx_user@nex_cx_test` smoke: `PASS`, checks `9/9`, two authorized
  candidates, BM25 frequency order confirmed, cross-owner and inactive
  fixtures excluded.
- Independent cleanup query: content objects `0`, lexical terms `0` for the
  smoke tenant.
- Full quality gate: `6892 passed`; statement coverage `98.86%`; branch
  coverage `96.49%`.
- Contract validation: schemas `85`, examples `136`, negative cases `101`,
  OpenAPI documents `7`.
- DGX providers were not invoked in this Slice.
