# Slice 0935: CX atomic private-vector publish wiring

## Goal

Publish a complete owner-scoped chunk-vector set and expose it as `READY`
without leaving a partially usable index when payload or metadata persistence
fails.

## Implementation

- All chunk IDs, numeric vectors, hashes, and dimensions are validated before
  the first payload write.
- The BUILDING manifest is persisted idempotently before its pgvector adapter
  is bound.
- Payloads are written idempotently outside metadata transactions, then a
  complete receipt fingerprint drives the single optimistic READY checkpoint.
- Any payload or READY-CAS failure triggers reverse-order payload deletion and
  a best-effort FAILED manifest record. Compensation failure is reported as
  non-retryable for operator attention.
- `SqlAlchemyVectorIndexRepository` reconstructs source chunk fingerprints from
  canonical CX chunk rows and owner-scopes every read and checkpoint update.
- The protocol remains valid when vector payloads move to a separate database;
  it does not pretend cross-database work is one ACID transaction.

The remote embedding provider is not required because this Slice receives a
precomputed deterministic vector batch.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_vector_index_publish.py \
  tests/test_cx_vector_atomic_publish_postgres_smoke.py
NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_CX_VECTOR_ATOMIC_PUBLISH_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_vector_atomic_publish_postgres_smoke.py --summary
```

Observed on 2026-09-21:

- Focused regression: `17 passed`; publish, repository, and smoke runner
  statement/branch coverage `100%/100%`.
- Actual `nex_cx_test` atomic publish smoke passed `8/8` checks for READY CAS,
  receipt count/fingerprint, checkpoint, timestamp, routing, and cleanup.
- Full quality gate: `6790 passed`; statement coverage `98.85%`; branch
  coverage `96.45%`.
- The remote embedding provider was not invoked.
