# Slice 0542: AE scheduler daemon runtime state contract/schema

## Scope

Add the AE-owned scheduler daemon runtime state snapshot contract before adding a
CLI entrypoint or bounded continuous loop.

## Contract

- `build_artifact_retention_scheduler_daemon_runtime_state` creates a
  metadata-only state snapshot for the AE artifact retention scheduler daemon.
- `validate_artifact_retention_scheduler_daemon_runtime_state` enforces schema,
  AE service scope, lifecycle status/reason rules, runtime/daemon config scope,
  safe metadata, and deterministic state ids.
- `summarize_artifact_retention_scheduler_daemon_runtime_state` provides the
  small AG-safe read shape for lifecycle dashboards.

## Lifecycle Rules

- `STOPPED` is valid for initialized or stopped snapshots.
- `DISABLED` records either runtime-disabled or explicit-opt-in-required
  reasons.
- `STARTING` and `RUNNING` require ready runtime enablement.
- `STOPPING` requires a stop request or shutdown timestamp.
- `ERROR` requires a failed last-cycle summary and a positive consecutive
  failure count.

## Guardrails

- The builder is state-snapshot-only and performs no persistence.
- The builder never starts the daemon loop.
- Actual retention work still enters through JobQueue.
- AG may consume the metadata-only projection shape later, but must not write AE
  persistence or enqueue AE jobs directly.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
```
