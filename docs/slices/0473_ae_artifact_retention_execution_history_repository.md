# Slice 0473: AE artifact retention execution history repository

## Scope

Add the runtime repository foundation for persisted AE artifact retention
execution history before wiring the purge API.

## Changes

- Added `ae_artifact_retention_execution_history.v1` record building and
  validation in `nex_ae_api.artifacts`.
- Added in-memory and SQLAlchemy retention execution history stores.
- Added a default store factory that uses the service persistence session
  factory when available.
- Extended SQLite regression coverage for idempotency reuse, scoped listing,
  nullable JSON handling, and database error mapping.

## Decisions

- History records are derived from validated
  `ae_artifact_retention_execution.v1` evidence and include a SHA-256 hash of
  that payload.
- Duplicate idempotency keys reuse the first persisted execution inside the
  tenant/workspace/owner scope.
- `error` remains SQL NULL when absent rather than a JSON `null` payload.
- Repository tests stay SQLite-based; protected PostgreSQL evidence is planned
  for Slice 0475.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
