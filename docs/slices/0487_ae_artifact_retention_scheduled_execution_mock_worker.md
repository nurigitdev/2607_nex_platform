# Slice 0487: AE artifact retention scheduled execution mock worker

Exercise scheduled retention command execution through a mock worker pipeline
before any scheduler daemon or background worker is introduced.

## Scope

- Added runtime helpers:
  - `AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_WORKER_RESULT_SCHEMA_VERSION`
  - `run_artifact_retention_scheduled_execution_mock_worker(...)`
  - `validate_artifact_retention_scheduled_execution_worker_result(...)`
  - `summarize_artifact_retention_scheduled_execution_worker_result(...)`
- Updated the scheduled execution command payload to carry explicit
  `dry_run=true` in the purge request body.
- Added regression coverage for READY worker execution, history-store writes,
  NOOP commands, invalid stores, worker result validation, and dry-run safety
  flags.

## Decisions

- The mock worker consumes the Slice 0486 command and delegates execution to the
  existing retention purge path.
- The worker always calls purge in safe dry-run mode; delete, storage, and
  database-row mutation flags are forced false.
- READY commands may write retention execution history when a history store is
  supplied.
- NOOP commands do not execute purge and must keep history empty.
- Worker result evidence keeps command embedding disabled and remains free of
  raw storage references or database URLs.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
