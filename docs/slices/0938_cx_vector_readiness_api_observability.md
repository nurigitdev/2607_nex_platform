# Slice 0938: CX Vector Readiness API and Observability

## Goal

Expose an owner-scoped operational surface for inspecting vector index
readiness and explicitly reconciling stale indexes without exposing private
text or vector values.

## API Boundary

- `GET /api/v1/vector-indexes/{vector_index_id}/readiness`
  verifies the current pgvector payload snapshot and remains read-only.
- `POST /api/v1/vector-indexes/{vector_index_id}/readiness/reconcile`
  accepts the trusted caller's current metadata-only source snapshot and
  embedding profile, then persists the established reconciliation state
  machine.
- Both routes require a trusted service claim plus canonical tenant and
  subject headers. Cross-owner and missing indexes are indistinguishable.
- In memory-only runtime mode, routes remain discoverable but return a
  retryable `CX_VECTOR_OPERATIONS_UNAVAILABLE` response.

The projection separates persisted `status` from evaluated
`freshness_status`. A GET can therefore report persisted `READY` alongside
evaluated `STALE` without mutating the manifest. Only the POST route performs
state transitions.

## Observability

The reconcile route emits `cx.vector_index.reconciled` with deterministic
identity and metadata-only details: action, statuses, checkpoint, usability,
rebuild requirement, and vector count. Source hashes, embedding checksums,
vector values, and document text are not emitted. Event-store failure does
not roll back a successful reconciliation.

No new table or migration is required. No remote embedding provider is called
in this Slice.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_vector_index_operations.py \
  tests/test_cx_vector_readiness_api_postgres_smoke.py

NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_CX_VECTOR_READINESS_API_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_vector_readiness_api_postgres_smoke.py --summary
```

Observed on 2026-09-21:

- Focused regression: `11 passed`; vector operations statement/branch
  coverage `100%/100%`.
- Actual `nex_cx_test` API smoke passed `10/10` checks, including owner
  isolation, non-mutating drift visibility, durable READY-to-STALE-to-
  REBUILD_REQUIRED reconciliation, event emission, and fixture cleanup.
- Full quality gate: `6822 passed`; statement coverage `98.85%`, branch
  coverage `96.47%`.
- Contract validation passed with OpenAPI `0.94.0` and all `33/33` CX runtime
  routes represented by the canonical contract.
- Post-smoke fixture audit: `cx_vector_indexes=0`, `cx_vectors=0` for the
  Slice tenant.
- The remote embedding provider was not invoked.
