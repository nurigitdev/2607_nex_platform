# Slice 0546: AE scheduler daemon graceful shutdown/state transition

## Scope

Add the AE-owned graceful shutdown transition contract for the artifact retention
scheduler daemon.

## Implementation

- `build_artifact_retention_scheduler_daemon_shutdown_transition` accepts a
  validated runtime state snapshot and projects the next lifecycle state.
- `STARTING`, `RUNNING`, and `ERROR` states transition to `STOPPING` with
  `stop_requested=true` and `shutdown_requested_at` set to the request time.
- `STOPPING`, `STOPPED`, and `DISABLED` states return `NOOP` decisions and keep
  the current state unchanged.
- `validate_artifact_retention_scheduler_daemon_shutdown_transition` enforces
  schema version, AE scope, actor shape, deterministic transition ids, lifecycle
  rules, safe metadata, guardrails, and the expected next state.
- `summarize_artifact_retention_scheduler_daemon_shutdown_transition` exposes the
  compact AG-safe read shape for lifecycle dashboards.

## Guardrails

- The transition is metadata-only and performs no runtime-state mutation.
- The transition does not deliver a process signal, start a loop, run a tick,
  enqueue JobQueue work, run a worker, write a database row, or enable physical
  delete automation.
- Actual retention work still flows through JobQueue admission and finite worker
  execution.
- AG may consume the projection later, but AG must not write AE persistence or
  enqueue AE jobs directly.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
