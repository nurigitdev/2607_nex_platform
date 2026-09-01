# Slice 0494: AE artifact retention scheduled worker runner adapter

Connect queued scheduled retention jobs to the shared worker runner while
keeping the S50 runtime limited to dry-run execution.

## Scope

- Added AE scheduled retention worker constants, config builder, handler
  builder, and once/batch runner helpers.
- Added `artifact_retention_scheduled_command_from_job(...)` to recover the
  validated scheduled command from a `common_job.v1` payload.
- Reused the Slice 0487 mock scheduled execution worker as the domain handler.
- Added regression coverage for success, persisted history, heartbeat updates,
  batch idle behavior, invalid jobs, and handler failure retry behavior.

## Decisions

- The shared worker runner owns claim, complete, retry, heartbeat, and optional
  log emission.
- The AE handler does not finalize jobs directly; it only performs the guarded
  dry-run retention worker operation.
- Failed handler execution is retried through the shared JobQueue policy because
  scheduled retention jobs are retryable with `max_attempts=3`.
- Physical delete automation remains disabled.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
