# Slice 0503: AE Retention Scheduler Tick Planner Foundation

## Scope

Slice 0503 adds a pure scheduler tick planner for AE artifact retention. It
turns an existing metadata-only batch plan and scheduler config into a
deterministic READY, NOOP, or SKIPPED tick decision without enqueuing work.

## Behavior

- READY ticks are only produced when the JobQueue is available, tick admission
  is enabled, the tick is inside the enforced `Asia/Seoul` batch window, and the
  batch plan has selected retention candidates.
- READY ticks include a dry-run `scheduler_tick` command preview.
- NOOP ticks represent valid batch plans with no retention candidates.
- SKIPPED ticks cover unavailable queues or ticks outside the batch window.
- The planner never starts a scheduler daemon, enqueues a job, runs a worker, or
  enables physical delete automation.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `tests/test_nex_ae_artifacts.py`
- `scripts/quality/run_quality_gate.sh`
