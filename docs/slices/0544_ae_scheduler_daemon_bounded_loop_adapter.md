# Slice 0544: AE scheduler daemon bounded loop adapter

## Scope

Add the first finite AE scheduler daemon bounded-loop adapter on top of the
existing one-cycle runner.

## Implementation

- `run_artifact_retention_scheduler_daemon_bounded_loop` validates runtime and
  daemon config, captures initial/final runtime state, and runs at most
  `max_cycles`.
- Each cycle delegates to `run_artifact_retention_scheduler_daemon_one_cycle`;
  the bounded-loop adapter never implements retention work directly.
- The adapter creates safe default trace/request identifiers when the caller
  does not provide them, so daemon-originated JobQueue admissions remain
  observable.
- `validate_artifact_retention_scheduler_daemon_bounded_loop_result` and
  `summarize_artifact_retention_scheduler_daemon_bounded_loop_result` expose the
  bounded-loop result as a metadata-only contract.

## Guardrails

- The loop is finite and requires `max_cycles` with a hard cap of 100 cycles.
- Runtime must be explicitly enabled before any one-cycle execution occurs.
- A stop request before the first cycle returns `STOPPED` without touching the
  artifact store, lease store, JobQueue, worker, or history path.
- A stop callback can stop cleanly after a completed cycle.
- One-cycle exceptions are converted to safe failed-cycle evidence without
  leaking raw exception text, database URLs, storage paths, or artifact payloads.
- Physical delete automation remains disabled; retention work still enters
  through JobQueue admission.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
