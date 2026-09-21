# Slice 0936: CX stale detection and reindex reconciliation

## Goal

Turn vector freshness drift into durable, explainable rebuild state while
preserving the lineage of the index that became stale.

## Implementation

- A compatible READY manifest remains retrieval-usable with no write.
- Source, policy, chunk, provider, model, deployment, dimension, count, and
  payload-fingerprint drift move READY through `STALE` to
  `REBUILD_REQUIRED`, with optimistic checkpoint persistence at each step.
- FAILED builds normalize to the stable `BUILD_FAILED` rebuild reason.
- Payload-only drift can rebuild the same identity in place. Source or profile
  identity drift preserves the old manifest and creates a new deterministic
  BUILDING replacement.
- A follow-up constraint migration preserves the last READY timestamp and
  payload receipt on stale/rebuild-required rows; only a new BUILDING state
  must clear them.
- Missing indexes produce a create plan; in-flight BUILDING indexes produce a
  wait plan, preventing duplicate admission.

No remote provider call is required in this Slice.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_vector_index_reconciliation.py \
  tests/test_cx_vector_reconciliation_postgres_smoke.py
NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_CX_VECTOR_RECONCILIATION_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_vector_reconciliation_postgres_smoke.py --summary
```

Observed on 2026-09-21:

- Focused regression: `33 passed`; reconciliation and smoke runner
  statement/branch coverage `100%/100%`.
- Actual `nex_cx_test` migration and reconciliation smoke passed `8/8` checks,
  preserving the old checkpoint-3 manifest and creating a changed-profile
  BUILDING replacement.
- Full quality gate: `6800 passed`; statement coverage `98.85%`; branch
  coverage `96.46%`.
- The remote embedding provider was not invoked.
