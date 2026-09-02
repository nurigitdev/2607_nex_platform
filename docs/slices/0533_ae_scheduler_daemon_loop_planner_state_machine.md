# Slice 0533: AE scheduler daemon loop planner state machine

## Scope

Add a pure AE-owned state machine for the artifact retention scheduler daemon
loop. The planner decides whether one cycle is allowed, but does not acquire a
lease, enqueue a job, execute a worker, write history, start the daemon, or open
a continuous loop.

## Decision States

- `DISABLED` with `runtime_disabled` when runtime enablement is off.
- `BLOCKED` with `explicit_opt_in_required` when enablement lacks explicit
  test-profile opt-in.
- `BLOCKED` for scheduler tick admission, operator dispatch admission, lease
  repository, JobQueue, or batch-window failures.
- `NOOP` with `stop_requested` when a stop request is planned against a runtime
  that has not started.
- `READY` only when test-profile explicit opt-in, admission checks, lease
  repository, JobQueue, and batch window all pass.

## Guardrails

- Planning is metadata-only and safe for later AG projection.
- Lease acquisition and JobQueue enqueue are explicitly marked as not performed.
- `runs_tick_once` is set only in the execution plan for a `READY` decision.
- Auto-start, daemon start, continuous loop start, physical delete automation,
  storage mutation, and database row delete remain disabled.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
```
