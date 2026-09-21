# Slice 0937: CX Vector Retrieval Freshness Enforcement

## Goal

Permit pgvector search only when the caller owns the index and the persisted
READY manifest still matches the current source snapshot, embedding profile,
and vector payload rows.

## Decisions

- A persisted `READY` status alone is not retrieval authority.
- Retrieval loads the manifest through its tenant/owner scope, binds the
  pgvector adapter to that manifest, and computes a fresh payload receipt
  snapshot before any similarity query.
- Source, profile, payload count, or payload fingerprint drift fails closed
  with `CX_VECTOR_INDEX_NOT_READY` and no vector search.
- A missing or differently owned index returns the same not-found response.
- Payload fingerprints are canonicalized by chunk identifier so publish-time
  and read-time receipt ordering cannot create false drift.
- BUILDING is retryable; stale and corrupted payload states require
  reconciliation or rebuild rather than blind query retry.
- Vector payloads remain private in PostgreSQL. The retrieval result exposes
  only chunk identifiers, checksums, distances, and scores.

No remote embedding provider is required in this Slice. Live provider evidence
is intentionally reserved for Slice 0939.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_vector_retrieval_guard.py \
  tests/test_nex_cx_pgvector_store.py \
  tests/test_cx_vector_retrieval_guard_postgres_smoke.py

NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_CX_VECTOR_RETRIEVAL_GUARD_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_vector_retrieval_guard_postgres_smoke.py --summary
```

Observed on 2026-09-21:

- Focused regression: `105 passed`; changed CX vector modules reached
  statement/branch coverage `100%/100%`.
- Actual `nex_cx_test` retrieval smoke passed `8/8` checks: a fresh READY
  index returned an exact cosine match, another owner observed not-found, and
  deleted vector payload caused `PAYLOAD_COUNT_MISMATCH` before search.
- Full quality gate: `6811 passed`; statement coverage `98.85%`; branch
  coverage `96.46%`; schema/example/OpenAPI contract validation passed.
- The remote embedding provider was not invoked.
