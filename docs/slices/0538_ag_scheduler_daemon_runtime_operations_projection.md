# Slice 0538: AG Scheduler Daemon Runtime Operations Projection

## Scope

Expose AE scheduler daemon runtime heartbeat state as read-only AG operations
evidence. AE remains the source of record for daemon runtime state, heartbeat
persistence, lease ownership, JobQueue admission, worker execution, and artifact
retention effects.

## Behavior

- AE adds a protected
  `/api/v1/artifact-retention/scheduler-daemon-runtime` route that returns a
  metadata-only runtime observation from `service_worker_heartbeats`.
- AG extends the AE artifact operations client with the daemon runtime route and
  includes the observation under the scheduler daemon operations projection.
- AG summarizes heartbeat-store availability, observed heartbeat status,
  worker id, active job id, and last-seen timestamp without exposing database
  URLs, storage paths, source payloads, or secrets.
- Runtime observation fetch failures degrade the AG projection with a warning
  source error. Daemon config fetch failures still produce the existing problem
  response because config remains the minimum source contract.
- Manual tick projection also refreshes runtime evidence after dispatch, so the
  operator view can correlate control evidence with the latest AE heartbeat.

## Guardrails

- AG does not write AE heartbeat rows and does not infer daemon state from AG
  persistence.
- Runtime projection is metadata-only and renames raw persistence indicators to
  operator-safe terms.
- Empty or unavailable heartbeat stores are represented explicitly instead of
  being treated as successful daemon health.
- The protected one-cycle PostgreSQL smoke now calls AE's runtime route after
  writing the daemon heartbeat and verifies the route reads back the actual
  `nex_ae_test` heartbeat row.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py tests/test_nex_ae_artifacts.py tests/test_nex_ag_artifact_operations.py tests/test_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py -q
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py tests/test_nex_ae_artifacts.py tests/test_nex_ag_artifact_operations.py tests/test_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py --cov=nex_ae_api.artifact_retention_scheduler --cov=nex_ae_api.artifacts --cov=nex_ag.artifact_operations --cov=run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE=1 \
  NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL> \
  ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py --summary
```
