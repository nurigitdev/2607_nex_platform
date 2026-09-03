# Slice 0537: AE Scheduler Daemon Runtime Heartbeat Observability

## Scope

Add optional worker-heartbeat observability to the AE artifact retention
scheduler daemon one-cycle runner. The runner still remains single-pass only,
but it can now emit standard shared runtime heartbeats when an operator-owned
heartbeat emitter is provided.

## Behavior

- The one-cycle runner accepts an optional `daemon_heartbeat_emitter`.
- Without an emitter, the runner preserves the existing no-heartbeat behavior
  and returns `daemon_heartbeat_results=[]`.
- With an emitter, the runner records `STARTING`, `BUSY`, and final `IDLE`
  heartbeat summaries for a successful ready cycle.
- If the tick path raises, the runner emits an `ERROR` heartbeat with the daemon
  loop-plan id for correlation before re-raising the original error.
- Heartbeat emission failures are captured as non-blocking summary evidence so
  scheduler execution is not failed by observability storage alone.

## Guardrails

- Heartbeat summaries are metadata-only and exclude raw payloads, database URLs,
  storage paths, and secrets.
- Heartbeat observability does not participate in the deterministic one-cycle
  result id, so observation failures do not change execution lineage.
- The protected PostgreSQL smoke now writes and reads back the daemon heartbeat
  from `service_worker_heartbeats` while keeping scheduled worker heartbeat
  evidence separate.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py --cov=run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE=1 \
  NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL> \
  ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py --summary
```
