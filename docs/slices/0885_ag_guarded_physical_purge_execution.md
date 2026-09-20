# Slice 0885: AG guarded physical purge execution

## Goal

Add an idempotent physical-purge service that cannot delete an AG source row
without a recoverable external archive receipt and an elapsed grace period.

## Implementation

- Added dry-run and execute modes; dry-run remains the default.
- Required policy execute enablement and the exact `PURGE` confirmation token.
- Required an external `SEALED` receipt, elapsed `purge_after`, existing source,
  and a fresh source-content SHA-256 match.
- Added in-memory and SQLAlchemy purge stores.
- SQL execution locks/rechecks source and receipt on PostgreSQL, deletes one
  source row, and marks its receipt `PURGED` in the same transaction.
- Added idempotent `NOOP` behavior when a prior purge already removed the source
  and committed the tombstone.
- Returned metadata-only execution evidence without source payload or the
  confirmation value.
- Added SQLite transaction regression coverage. Actual PostgreSQL lifecycle
  execution remains assigned to Slice 0888.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_audit_retention_purge.py \
  --cov=nex_ag.audit_retention_purge --cov-branch --cov-report=term-missing
```

Observed verification:

```text
purge tests: 21 passed
purge module statement/branch: 100%
SQLite atomic purge and rollback regression: PASS
aggregate regression: 6112 passed, 1 known warning
statement=74289/75170=98.827989889584%
branch=17412/18062=96.401284464622%
```
