# Slice 1204: OA persistence and migration drift audit

## Goal

Verify the static NeX-OA persistence chain before changing identity or security
behavior, while reserving actual database comparison for protected PostgreSQL
evidence.

## Result

- All 11 OA migrations are ordered, unique, transaction-wrapped, and recorded
  in `schema_migrations`.
- The five OA-owned core tables are declared and referenced by their repository
  adapters: tenants, subjects, memberships, user sessions, and credentials.
- PostgreSQL table, index, and constraint identifiers remain within the 63-byte
  identifier limit.
- The canonical history remains versioned SQL through
  `scripts/db/run_migrations.py`. The shared Alembic config builder exists, but
  no separate OA Alembic history is configured; two competing histories must
  not be introduced.
- Static chain validity is not proof of the current database. Actual migration
  ledger, table, column, index, and repository behavior is deferred to Slice
  1210 against `nex_oa_test`.
- No table or migration is added.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_oa_database_drift_audit.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_database_drift_audit.py \
  --coverage-target services/nex-oa/nex_oa/database_drift_audit.py \
  --coverage-target scripts/smoke/run_oa_database_drift_audit.py \
  --smoke scripts/smoke/run_oa_database_drift_audit.py
```
