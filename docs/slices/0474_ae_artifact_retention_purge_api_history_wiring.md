# Slice 0474: AE artifact retention purge API history wiring

## Scope

Wire the guarded artifact retention purge API to persisted execution history.

## Changes

- Added `retention_history_store` support to AE artifact routes.
- The purge route now reuses tenant/workspace/owner-scoped idempotency history
  before executing a duplicate request.
- The purge route writes metadata-only history records for dry-run, blocked, and
  successful execute responses.
- Execute requests check history store availability before physical delete is
  attempted.
- Added regression coverage for idempotency reuse and execute-time history
  availability failure.

## Decisions

- A retention purge idempotency key represents one command inside the
  tenant/workspace/owner scope. Reusing the same key returns the first persisted
  execution.
- Protected physical delete remains guarded by the existing three delete flags.
- API wiring uses the same repository abstraction as the planned PostgreSQL
  smoke path; actual test DB evidence follows in Slice 0475.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
