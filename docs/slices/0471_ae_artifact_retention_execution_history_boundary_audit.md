# Slice 0471: AE artifact retention execution history boundary audit

## Scope

Start S48 by freezing the AE artifact retention execution history boundary before
adding schema, repositories, and API writes.

## Changes

- Added `scripts/smoke/run_ae_artifact_retention_history_boundary_audit.py`.
- Added `tests/test_ae_artifact_retention_history_boundary_audit.py`.
- Registered the audit in the default quality gate.
- Documented the S48 sequence for retention execution history persistence:
  migration, repository, API wiring, and protected PostgreSQL smoke evidence.

## Decisions

- `nex-ae-api` remains the system of record for artifact retention execution
  history.
- Retention history will be stored in `ae_artifact_retention_executions`.
- History records use `ae_artifact_retention_execution_history.v1` and derive
  from the existing `ae_artifact_retention_execution.v1` purge evidence.
- History scope is `tenant_id`, `workspace_id`, and `owner_user_id`.
- Idempotency is scoped by `tenant_id`, `workspace_id`, `owner_user_id`, and
  `idempotency_key`.
- History payloads remain metadata-only: no raw artifact content, rendered file
  content, database URL, service token, or storage-root value may be persisted
  in evidence.
- The purge API is the first planned writer of retention execution history.

## Planned Follow-up

- Slice 0472: PostgreSQL migration and indexes.
- Slice 0473: in-memory and SQLAlchemy repository with SQLite regression.
- Slice 0474: purge API persisted history wiring.
- Slice 0475: protected PostgreSQL smoke evidence against `nex_ae_test`.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_history_boundary_audit.py -q --cov=run_ae_artifact_retention_history_boundary_audit --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_history_boundary_audit.py --summary
```
