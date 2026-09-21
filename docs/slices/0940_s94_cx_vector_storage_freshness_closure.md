# Slice 0940: S94 CX Vector Storage and Freshness Closure

## Closure Result

S94 closes as `READY_FOR_S95` with
`CX_VECTOR_STORAGE_AND_INDEX_FRESHNESS_FOUNDATION_READY` readiness.

- `cx_vector_indexes` is the owner-scoped metadata system of record and
  `cx_vectors` is the private PostgreSQL/pgvector payload store.
- `NEX_CX_VECTOR_DATABASE_URL` can route payloads to a separately provisioned
  vector database; the current deployment falls back to the primary CX
  database.
- Qwen3-Embedding-4B uses 2560-dimensional vectors and a `halfvec(2560)` HNSW
  cosine expression index.
- Atomic publish validates the complete chunk set, writes private payloads,
  and exposes READY only after an optimistic manifest checkpoint. Failure
  triggers compensating payload deletion and a best-effort FAILED state.
- Freshness compares source, embedding profile, payload count, and payload
  fingerprint. Only an owner-scoped compatible READY index is queryable.
- Drift is reconciled durably through STALE and REBUILD_REQUIRED, preserving
  the prior manifest and creating a replacement identity when required.
- Protected readiness routes expose read-only evaluation and explicit
  reconciliation without returning private text or vector values.

## Actual Evidence

The S94 PostgreSQL smoke set completed 53 checks across schema persistence,
the owner-scoped adapter, atomic publish, reconciliation, retrieval admission,
and readiness API behavior. All runners targeted the actual
`nex_cx_user@nex_cx_test` database and cleaned their fixtures.

The Slice 0939 protected smoke additionally made an actual OpenAI-compatible
request to the DGX Qwen3-Embedding-4B provider, validated one finite non-zero
2560-dimensional vector, published it to `nex_cx_test`, and retrieved it
through the freshness guard. All 11 checks passed and the independent fixture
audit reported zero remaining index, vector, and content rows.

## Scope Boundary

This closure deliberately claims a storage and freshness foundation, not a
fully automated production indexing runtime. The following remain deferred:

- durable-ingestion worker wiring that invokes embedding, publish, and
  reconciliation automatically;
- deployment and migration operations for a physically separate vector
  database;
- multi-document ANN scale, tuning, and performance validation.

The existing versioned SQL plus `schema_migrations` runner remains the only
canonical migration history. Cross-owner resources remain indistinguishable
from missing resources.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s94_cx_vector_storage_freshness_closure.py
./.venv/bin/python \
  scripts/smoke/run_s94_cx_vector_storage_freshness_closure.py --summary
```

Observed on 2026-09-22:

- Focused closure suite: `7 passed`.
- Closure evidence: `PASS`, deterministic evidence `3/3`, PostgreSQL checks
  `53`, protected live checks `11`, next requirement `S95`.
- Closure runner coverage: statement `100.00%`, branch `100.00%`.
- Full regression: `6838 passed`, statement coverage `98.86%`, branch
  coverage `96.47%`.
- Contract validation: schemas `85`, examples `136`, negative cases `101`,
  OpenAPI documents `7`.
- Full quality gate and the final S94 closure check completed with exit code
  `0`.

This closure adds no table, index, route, migration, or provider call.
