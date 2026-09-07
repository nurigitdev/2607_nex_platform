# Slice 0574: AE supervised process service/API wiring

## Scope

Expose AE-owned supervised daemon process snapshot evidence through protected
service APIs while keeping real subprocess start/stop execution disabled.

## Implementation

- Added supervised process dispatch, collection, and detail response builders.
- Added protected AE routes:
  - `POST /api/v1/artifact-retention/scheduler-daemon-process-snapshots`
  - `GET /api/v1/artifact-retention/scheduler-daemon-process-snapshots`
  - `GET /api/v1/artifact-retention/scheduler-daemon-process-snapshots/{daemon_supervised_process_record_id}`
- Wired the routes to
  `SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore` when
  `app.state.nex_persistence.api_session_factory` is available, with explicit
  test-store injection still taking precedence.
- Added scheduler config route-map visibility for the supervised process
  snapshot endpoint family.
- Added regression coverage for auth, dispatch persistence, list filters,
  detail readback, missing-store errors, invalid filters, missing records, and
  redaction safety.

## Guardrails

- Slice 0574 does not start or stop a subprocess.
- The POST route records observed process evidence only; it does not invoke the
  supervisor adapter, daemon CLI, JobQueue, worker execution, or physical
  delete automation.
- Persistence remains AE-owned. AG may later read safe projections through AE
  APIs, but AG still has no direct database write or process-control authority.
- API payloads exclude database URLs, local storage paths, raw artifact payloads,
  raw execution payloads, raw daemon runtime payloads, provider secrets, and
  service tokens.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py services/nex-ae-api/nex_ae_api/artifacts.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_routes.py tests/test_nex_ae_artifacts.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_routes.py tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

## Next

- Slice 0575 should run protected PostgreSQL smoke evidence against
  `NEX_AE_TEST_DATABASE_URL` for the supervised process API path.
