# Slice 1000: CX MVP Integration Live PostgreSQL Smoke

## Goal

Prove the S100 MVP lifecycle on the actual `nex_cx_test` database and all three
DGX provider capabilities while preserving the CX-to-MO capability boundary,
owner isolation, private payload storage, and restart-safe AE handoff.

## Implementation

- Added a protected live runner that requires the test profile, validates the
  exact PostgreSQL database/role, applies all CX migrations, and rejects model
  or request-shape drift before any write flow starts.
- Composed the production CX MVP runtime with PostgreSQL content metadata,
  lexical candidates, pgvector stores, external owner-scoped private text, and
  the NeX-MO embedding/reranking capability clients.
- Exercised one continuous document lineage through upload, extraction,
  `1000_100` chunking, MeCab lexical indexing, live embedding, atomic vector
  publication, permission-filtered hybrid retrieval, and live reranking.
- Admitted the resulting retrieval package to the durable asynchronous
  generation queue, executed the worker through the NeX-MO generation alias,
  and verified `PENDING` to restart-safe `READY` AE handoff progression.
- Verified that another owner receives not-found semantics and that PostgreSQL
  metadata does not contain the private source or prompt markers.
- Added activation, configuration, target, model, request-shape, redaction,
  safe-failure, evidence-summary, and CLI regression tests. Live-only database
  and provider execution remains explicitly excluded from ordinary regression.

## Verification

```bash
./.venv/bin/pytest -q tests/test_cx_mvp_integration_live_postgres_smoke.py

NEX_CX_MVP_INTEGRATION_LIVE_POSTGRES_SMOKE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py --summary
```

## Observed Evidence

- Slice Gate: `2251 passed`; statement coverage `99.02%`, branch coverage
  `98.15%`.
- Live smoke runner target coverage: statement `97.63%`, branch `100.00%`.
- Contract validation: `92` schemas, `145` positive examples, `109` negative
  examples, and `7` OpenAPI documents.
- Protected DGX preflight: PASS for embedding, reranking, and generation.
- PostgreSQL identity: `nex_cx_user@nex_cx_test`.
- Migration state: `21` planned, `0` applied, `21` already current.
- Live providers: `Qwen3-Embedding-4B` 2 successes,
  `Qwen3-Reranker-4B` 1 success, and `Qwen3.5-4B` 1 success; no failures.
- Persisted lifecycle: vector `READY`, retrieval `READY`, generation
  `COMPLETED`, job `SUCCEEDED`.
- Protected checks: `11/11`; handoff `READY`; owner scope enforced.
- S100 boundary audit: resolved gaps `8/8`, next Slice `1001`.
