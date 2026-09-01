# Slice 0493: AE artifact retention scheduled job planner/admission

Wire the S50 scheduled retention contract into the shared JobQueue admission
path without starting a scheduler daemon or executing deletion work.

## Scope

- Added scheduled job admission plan/result builders for AE artifact retention.
- Added deterministic admission idempotency derived from tenant, workspace,
  owner, batch plan, and trigger type.
- Added `enqueue_artifact_retention_scheduled_job(...)` as the queue boundary
  wrapper around shared `JobQueue.enqueue(...)`.
- Added regression coverage for READY admission, duplicate enqueue replay,
  NOOP skip behavior, queue failures, and validator edge cases.

## Decisions

- READY batch plans produce a scheduled execution command and a retryable
  `common_job.v1` job.
- NOOP batch plans return `SKIPPED` admission and never call the queue.
- Queue admission records stay explicit that the scheduler daemon was not
  started, the worker was not executed, and physical delete automation remains
  disabled.
- JobQueue errors are wrapped as AE artifact retention admission errors so the
  API boundary can expose service-local problem details later.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
