# Slice 0604: AE fake dry-run execution worker adapter

## Scope

Add an AE-owned fake dry-run operator-control execution worker adapter that
consumes Slice 0602 worker commands and Slice 0603 transition plans.

## Decision

- No new database table is introduced in Slice 0604.
- The first worker adapter uses the existing fake supervisor adapter and
  existing supervisor command/result contracts.
- A ready worker command dispatches each supervisor command to the fake
  supervisor adapter and returns one worker result.
- A blocked worker command does not invoke the supervisor adapter and returns a
  blocked worker result.
- Worker status is `FAILED` only when a supervisor result is `FAILED`;
  otherwise a ready fake dry-run command is considered `SUCCEEDED` because the
  fake adapter completed without real process side effects.

## Implementation

- Added the worker result schema version and status constants.
- Added worker result builder, validator, summary, and summary-line helpers.
- Added
  `run_artifact_retention_scheduler_daemon_operator_control_execution_worker`
  as the fake dry-run worker entrypoint.
- Added regression coverage for start, restart stop-then-start, blocked command,
  failed supervisor result, transition-plan mismatch, invalid payloads, and
  default observed timestamp behavior.

## Guardrails

- Slice 0604 may invoke only the fake supervisor adapter.
- Database writes, JobQueue enqueue, subprocess start/stop, transition
  persistence, supervisor result persistence, and physical deletion remain
  disabled.
- Future persistence should continue to reuse the existing S60 execution state
  and transition tables rather than introducing a long worker table name.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_adapter.py
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_adapter.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

- Targeted regression: `28 passed`.
- Full regression/quality gate: `4247 passed`, exit code `0`.
- Coverage evidence: statement `98.56%`, branch `95.67%`.

## Next

- Slice 0605 should expose the worker plan/command/transition/result flow
  through protected AE service/API routes with explicit defaults that avoid
  persistence unless requested.
