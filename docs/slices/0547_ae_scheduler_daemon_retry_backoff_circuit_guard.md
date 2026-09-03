# Slice 0547: AE scheduler daemon retry/backoff/circuit guard

## Scope

Add the AE-owned retry, backoff, and circuit guard contract for the artifact
retention scheduler daemon.

## Implementation

- `build_artifact_retention_scheduler_daemon_retry_circuit_guard` evaluates a
  runtime state snapshot and decides whether the daemon may attempt the next
  cycle.
- The guard uses the runtime config `backoff_seconds` value by default and
  applies a default circuit threshold of three consecutive failures.
- `READY` covers normal operation and elapsed retry windows.
- `BACKING_OFF` blocks retry attempts until the next retry timestamp.
- `CIRCUIT_OPEN` blocks repeated failures at or beyond the threshold until an
  operator-driven recovery path resets runtime state.
- `NOOP` covers stopped, stopping, stop-requested, and disabled daemon states.
- `validate_artifact_retention_scheduler_daemon_retry_circuit_guard` enforces
  schema, AE scope, deterministic guard ids, retry decisions, backoff values,
  circuit threshold values, safe metadata, and guardrails.

## Guardrails

- The guard is metadata-only and performs no runtime-state mutation.
- The guard does not start a loop, run a tick, enqueue JobQueue work, run a
  worker, write a database row, or enable physical delete automation.
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
