# Slice 0472: AE artifact retention execution history migration

## Scope

Add the PostgreSQL schema foundation for persisted AE artifact retention purge
execution history.

## Changes

- Added `database/nex-ae-api/migrations/0472_ae_artifact_retention_execution_history.sql`.
- Extended database schema regression coverage for the history table, indexes,
  idempotency key uniqueness, and metadata-only constraints.

## Decisions

- Retention execution history is stored in `ae_artifact_retention_executions`.
- The table stores flat query columns plus the validated metadata-only execution
  payload and a SHA-256 payload hash.
- Idempotency is unique per tenant, workspace, owner, and idempotency key.
- The table intentionally does not foreign-key to purged artifact records so
  operational history remains available after physical deletion.
- Raw artifact content, rendered file paths, database URLs, and service tokens
  are excluded from the schema.

## Evidence

```bash
./.venv/bin/pytest tests/test_database_schema_foundation.py -q
```
