# Slice 0527: AG scheduler daemon dashboard rollup

## Scope

- Roll AE scheduler daemon posture into the existing AG artifact retention
  automation dashboard.
- Keep AG read-only for dashboard visibility while AE remains the source of
  record for daemon config, scheduler lease, JobQueue, artifacts, and history.
- Preserve the dedicated daemon operations routes from S53 for detailed
  inspection and guarded manual tick-once dispatch.

## Implementation

- `build_artifact_operation_retention_automation_projection` now accepts
  optional daemon config and emits a `scheduler_daemon` block with metadata-only
  daemon summary.
- The automation summary now includes daemon readiness fields:
  `daemon_manual_tick_once_available`, `daemon_start_daemon_available`,
  `daemon_scheduler_daemon_started`, `daemon_continuous_loop_started`,
  `daemon_lease_repository_available`, and `daemon_job_queue_available`.
- The protected AG automation route fetches AE daemon config through the AG AE
  artifact operations client and rolls it into the dashboard projection.
- The mock automation smoke now checks daemon rollup visibility.

## Guardrails

- AG still performs no direct database writes and no direct JobQueue enqueue.
- `start_daemon` and continuous loop execution remain unavailable.
- The rollup is metadata-only and redaction guarded; raw artifact payloads,
  storage refs, DB URLs, and local data paths are not allowed in AG evidence.

## Evidence

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_artifact_operations.py \
  tests/test_ag_artifact_retention_automation_operations_smoke.py \
  -q --cov=nex_ag.artifact_operations \
  --cov=run_ag_artifact_retention_automation_operations_smoke \
  --cov-branch --cov-report=term-missing
```

The default quality gate continues to run
`scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py`.
