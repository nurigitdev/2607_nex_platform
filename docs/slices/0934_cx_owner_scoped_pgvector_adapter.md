# Slice 0934: CX owner-scoped pgvector adapter and routing

## Goal

Implement an owner-scoped pgvector adapter without weakening the existing
private-vector capability or coupling it to one database deployment shape.

## Implementation

- `PgVectorCxVectorStore` binds to a validated vector-index manifest before it
  exposes a `CxVectorStore` implementation. The binding fixes index, content,
  chunk set, owner, allowed chunk IDs, dimension, and lifecycle state.
- Bound writes are accepted only while the manifest is `BUILDING`; all reads,
  writes, deletes, and cosine searches repeat tenant and owner predicates.
- Payload writes are immutable and idempotent, storage receipts contain no raw
  owner identifiers, and database failures map to a retryable redacted error.
- `NEX_CX_VECTOR_DATABASE_URL` routes production payloads to an optional
  separate database and otherwise falls back to the primary CX database.
  `NEX_CX_VECTOR_TEST_DATABASE_URL` provides the equivalent protected test
  override.
- A separately routed vector database must be provisioned with pgvector and the
  `cx_vectors` payload schema before traffic is enabled. The current deployment
  uses the primary-database fallback.
- Summary vectors remain on the existing generic private-vector adapter. This
  S94 index adapter intentionally owns retrieval chunk embeddings only.

The remote embedding provider is not required in this Slice.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_pgvector_store.py \
  tests/test_cx_pgvector_adapter_postgres_smoke.py \
  tests/test_nex_runtime_database.py
NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_CX_PGVECTOR_ADAPTER_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_pgvector_adapter_postgres_smoke.py --summary
```

Observed on 2026-09-21:

- Focused regression: `57 passed`; adapter and smoke runner statement/branch
  coverage `100%/100%`.
- Actual `nex_cx_test` adapter smoke passed `10/10` checks using the primary
  fallback route, including idempotent put/get/search/delete and cleanup.
- Full quality gate: `6773 passed`; statement coverage `98.85%`; branch
  coverage `96.44%`.
- The remote embedding provider was not invoked.
