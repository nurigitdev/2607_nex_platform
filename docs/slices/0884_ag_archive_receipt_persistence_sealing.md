# Slice 0884: AG archive receipt persistence and sealing

## Goal

Persist immutable evidence that an eligible AG source payload was archived by
an injected provider before any physical purge can be considered.

## Implementation

- Added the 15-character `ag_ret_archives` table through migration 0884.
- Stored source identity, content SHA-256, provider mode, hashed object
  reference, provider receipt SHA-256, lifecycle status, and safe timestamps.
- Excluded payloads, object URLs/keys, endpoints, and credentials.
- Added in-memory and SQLAlchemy receipt stores with idempotent save behavior
  and immutable source/hash conflict detection.
- Added the `AgArchiveAdapter` protocol and a development mock adapter.
- External recoverable results become `SEALED` and receive `purge_after`.
  Development mock results become `MOCKED` and never receive `purge_after`.
- Added a status/due index named `idx_ag_ret_arc_status_due` (25 characters).
- Added SQLite persistence regression coverage. Actual `nex_ag_test` migration
  verification is performed before this Slice is committed; full lifecycle
  PostgreSQL evidence remains assigned to Slice 0888.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_audit_retention_archive.py \
  --cov=nex_ag.audit_retention_archive --cov-branch --cov-report=term-missing
```

Observed verification:

```text
archive receipt tests: 36 passed
archive module statement/branch: 100%
nex_ag_test migration: 0884_ag_retention_archive_receipts applied
PostgreSQL CRUD smoke: saved=1 loaded=1 deleted=1
direct SQL: table=true index=true smoke_residue=0
aggregate regression: 6091 passed, 1 known warning
statement=74130/75011=98.825505592513%
branch=17358/18008=96.390493114171%
```
