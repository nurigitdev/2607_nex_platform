# Slice 0949: CX Permission Hybrid Live PostgreSQL Smoke

## Goal

Prove the S95 permission-filtered hybrid retrieval path against the actual
`nex_cx_test` PostgreSQL database and the live DGX embedding/reranker providers
without exposing private payloads or provider credentials in smoke evidence.

## Implementation

- Adds a protected, default-disabled smoke that accepts only the
  `nex_cx_user@nex_cx_test` target and runs the versioned CX migrations.
- Persists a private owner-scoped document and its extraction/chunk lineage,
  then builds a PostgreSQL-backed BM25 candidate set.
- Calls the live `Qwen3-Embedding-4B` provider, verifies 2560-dimensional
  vectors, publishes them through the pgvector adapter, and requires a fresh
  vector candidate.
- Applies permission admission before candidate materialization, weighted RRF
  with vector/BM25 weights `0.7/0.3` and `rrf_k=60`, and the live
  `Qwen3-Reranker-4B` provider.
- Executes the canonical `POST /api/v1/retrieval/context` route and verifies the
  package was written with query/evidence hashes while both private previews
  remain `NULL`.
- Adds migration `0949_cx_retrieval_private_preview_nullable` so the historical
  evidence preview column permits the S95 hash-only private persistence policy.
- Deletes all smoke fixtures and reports only redacted database/provider
  identity, bounded counts, policy identifiers, and boolean checks.
- Updates the canonical reranker defaults and examples from the former 0.6B
  target to the current `Qwen3-Reranker-4B`; the explicit NeX-PCX legacy
  profile remains unchanged.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_database_schema_foundation.py \
  tests/test_cx_permission_hybrid_live_postgres_smoke.py
```

Focused results:

- `442 passed` across the provider/model and protected-smoke impact set.
- `62 passed` across the migration, CX drift/re-audit, and protected-smoke
  regression set after the schema ledger changed from 17 to 18 migrations.
- Protected smoke runner statement/branch coverage: 100%/100% under its unit
  configuration and response-shape tests.
- Actual protected live execution: `16/16` checks passed.
- Database identity: `nex_cx_user@nex_cx_test`.
- Live providers: `Qwen3-Embedding-4B` and `Qwen3-Reranker-4B`.
- Canonical API returned HTTP 200; migration was current; hash-only persistence
  and fixture cleanup both passed.

The protected execution command and credentials are intentionally excluded
from repository files. Default regression executes the runner in `SKIPPED`
mode unless `NEX_CX_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE=1` is supplied.

Full quality-gate results:

- `7137 passed`.
- Repository statement coverage: 98.88%.
- Repository branch coverage: 96.56%.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.
