# Slice 0933: CX vector manifest and payload persistence schema

## Goal

Persist owner-scoped vector-index manifests and private pgvector payloads while
keeping future vector-database separation possible.

## Implementation

- `cx_vector_indexes` is the primary CX metadata system of record for source
  and embedding-profile fingerprints, lifecycle state, payload receipts, and
  optimistic checkpoint versions.
- `cx_vectors` stores private vector payloads with duplicated owner lineage and
  no cross-database foreign keys, so it can later move behind
  `NEX_CX_VECTOR_DATABASE_URL`.
- The manifest lineage trigger rejects content-owner, chunk-set, policy, source
  hash, and chunk-count mismatches.
- Payload rows enforce `vector_dims(embedding) = vector_dimension` and unique
  `(vector_index_id, chunk_id)` receipts.
- Full `vector` payloads preserve values for flexible future dimensions. The
  current 2560-dimensional Qwen profile uses a `halfvec(2560)` HNSW cosine
  expression index because pgvector limits HNSW `vector` indexes to 2000
  dimensions and `halfvec` indexes to 4000 dimensions.
- pgvector extension installation remains a DBA prerequisite. Application
  migrations verify its presence and do not attempt privileged installation.

The remote embedding provider is not required in this Slice.

## Verification

```bash
./.venv/bin/pytest -q tests/test_cx_vector_persistence_postgres_smoke.py
NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_CX_VECTOR_PERSISTENCE_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_vector_persistence_postgres_smoke.py --summary
```

Observed on 2026-09-21:

- Focused regression: `55 passed`; protected smoke runner statement/branch
  coverage `100%/100%`.
- Actual `nex_cx_test` migration applied and PostgreSQL/pgvector smoke passed
  `9/9` checks, including 2560-dimensional round-trip, owner-scoped cosine
  lookup, lineage and dimension rejection, and cleanup.
- Full quality gate: `6744 passed`; statement coverage `98.84%`; branch
  coverage `96.44%`.
- The remote embedding provider was not invoked.
