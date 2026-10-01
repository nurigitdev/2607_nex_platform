# Slice 1220: OA identity lifecycle PostgreSQL smoke evidence

## Goal

Prove the S122 durable lifecycle path against the actual `nex_oa_test` database,
including migration currency, protected APIs, transaction outcomes, and cleanup.

## Protected Execution

The smoke accepts only `nex_oa_user@.../nex_oa_test` and requires an explicit
opt-in flag. Database URLs are redacted from evidence.

```bash
NEX_OA_IDENTITY_LIFECYCLE_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:<password>@127.0.0.1:5432/nex_oa_test' \
./.venv/bin/python scripts/smoke/run_oa_identity_lifecycle_postgres_smoke.py --summary
```

## Evidence

The 2026-10-01 protected execution completed with:

- database/role: `nex_oa_test` / `nex_oa_user`
- migration plan: `12`; newly applied: `1215_oa_identity_lifecycle`
- subject transition: `ACTIVE -> DISABLED`, revision `1 -> 2`
- membership transition: `ACTIVE -> DISABLED`, revision `1 -> 2`
- stale revision: HTTP `409` with `oa.lifecycle_revision_conflict`
- lifecycle events: `2` with server actor, request, and trace lineage
- revoked active sessions: `2`; remaining active sessions: `0`
- cleanup: events `2`, sessions `2`, memberships `2`, subjects `2`, tenant `1`
- cleanup residue across all five tables: `0`

The protected test is skipped unless explicitly enabled, so ordinary regression
and Full Gate runs remain deterministic and do not write to PostgreSQL.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_identity_lifecycle_postgres_smoke.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_postgres_smoke.py \
  --smoke scripts/smoke/run_oa_identity_lifecycle_postgres_smoke.py
```
