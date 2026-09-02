# Slice 0517: AE Scheduler Daemon Dispatch Facade

## Scope

Wire the Slice 0516 daemon control plan to the existing manual tick-once runner.
This creates an AE-owned dispatch facade without introducing a long-running
scheduler daemon.

## Implementation

- Added `dispatch_artifact_retention_scheduler_daemon_control`.
- Added daemon dispatch result schema, validation, and summary helpers.
- `manual_tick_once` dispatches the Slice 0514 tick-once runner only when the
  control plan is `READY`.
- `start_daemon` returns `BLOCKED` and never starts a process.
- `status_probe` and `stop_daemon` return `NOOP` without touching the artifact
  store or JobQueue.
- Dispatch evidence records tick-once result status, lease release, JobQueue
  admission, and daemon/loop guardrails.

## Evidence

Regression tests cover:

- ready manual dispatch through lease, batch plan, JobQueue admission, and
  tick-once result validation;
- blocked daemon start without side effects;
- status/no-op path without side effects;
- manual dispatch blocked by unavailable JobQueue;
- manual dispatch with a busy lease captured as a dispatched tick-once skip;
- dispatch result validation drift and redaction checks.

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
```

Result: `59 passed`, module coverage `98%`.

## Guardrails

- Dispatch requires a daemon control plan.
- Tick-once dispatch requires a `READY` manual control plan.
- No scheduler daemon or continuous loop is started.
- No physical delete automation is enabled.
- Dispatch evidence remains metadata-only and redacted.
