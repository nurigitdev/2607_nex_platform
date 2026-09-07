# Slice 0558: AE daemon run read-model API

## Scope

Expose the persisted AE scheduler daemon run and lifecycle event summaries from
Slice 0557 through read-only AE API routes.

## Implementation

- Added safe collection/detail builders for daemon run read models in
  `nex_ae_api.artifact_retention_scheduler_daemon`.
- Added `SqlAlchemyArtifactRetentionSchedulerDaemonRunStore.list_run_records`
  with scheduler, result-status, and bounded limit filters.
- Added AE routes:
  `/api/v1/artifact-retention/scheduler-daemon-runs` and
  `/api/v1/artifact-retention/scheduler-daemon-runs/{daemon_run_record_id}`.
- Added default store construction from `app.state.nex_persistence` while
  returning a 503 problem response when no database-backed run store is
  configured.
- Updated the scheduler config route catalog so operators can discover the new
  daemon run read-model endpoint.

## Guardrails

- The routes are read-only and require AE auth.
- AE remains the persistence owner.
- AG can consume these routes in a later projection slice, but it still cannot
  write AE daemon run rows, enqueue AE retention jobs, or control the daemon
  process.
- Responses include safe summaries only and keep database URLs, local storage
  paths, raw artifact payloads, raw execution payloads, and raw daemon runtime
  payloads out of the read model.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifacts.py services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifacts.py tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py -q
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0559 can add the AG read-only projection over these AE-owned daemon run
  collection/detail routes and prove the flow against the AE test database.
