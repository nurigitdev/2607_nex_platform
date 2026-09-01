# Slice 0480: S48 AE artifact retention history closure

Close the S48 artifact retention execution history track with an automated
closure checkpoint.

## Changes

- Added `scripts/smoke/run_s48_ae_artifact_retention_history_closure.py`.
- Added `tests/test_s48_ae_artifact_retention_history_closure.py`.
- Added the S48 closure check to `scripts/quality/run_quality_gate.sh`.

## Closure Matrix

- Retention execution history boundary audit.
- PostgreSQL migration for `ae_artifact_retention_executions`.
- In-memory and SQLAlchemy history repositories.
- Purge API history writer and idempotency reuse.
- PostgreSQL writer smoke evidence.
- Metadata-only history read-model.
- Authenticated history query API.
- PostgreSQL query smoke evidence against `nex_ae_test`.
- AG retention history operations projection.

## Decisions

- AE remains the retention history system of record.
- AG owns only a read-only operations projection.
- Query and AG surfaces exclude raw persisted execution JSON and expose
  execution payload hashes for correlation/debugging.

## Verification

```bash
./.venv/bin/pytest tests/test_s48_ae_artifact_retention_history_closure.py -q --cov=run_s48_ae_artifact_retention_history_closure --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_s48_ae_artifact_retention_history_closure.py --summary
```
