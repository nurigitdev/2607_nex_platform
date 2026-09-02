# Slice 0535: AE Scheduler Daemon Start/Stop Control Guardrail

## Scope

Add an AE-owned guardrail evidence payload for artifact retention scheduler
daemon `start_daemon` and `stop_daemon` controls. This slice does not introduce
a daemon process, supervisor, stop signal, background thread, or continuous loop.

## Behavior

- `start_daemon` remains `BLOCKED` by policy with
  `daemon_disabled_by_policy`.
- `stop_daemon` remains an idempotent `NOOP` with `daemon_not_running`.
- Start/stop dispatch results include a dedicated
  `start_stop_guardrail` payload.
- Non start/stop dispatch results keep `start_stop_guardrail` as `None`.
- AG may project the guardrail as metadata-only operator evidence without
  receiving raw control payloads, database URLs, storage paths, or secrets.

## Guardrails

- Start/stop actions are never allowed by the current runtime policy.
- Runtime state transitions are fixed to `NONE`.
- The guardrail performs no lease acquisition, JobQueue enqueue, worker
  execution, history write, stop signal, daemon start, or continuous loop start.
- Future daemon start enablement must be introduced behind an explicit
  supervisor/runtime decision rather than this control facade.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1 \
  NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL> \
  ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py --summary
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1 \
  NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL> \
  ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py --summary
```
