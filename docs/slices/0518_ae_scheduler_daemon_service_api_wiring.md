# Slice 0518: AE Scheduler Daemon Service API Wiring

## Scope

Expose the S52 scheduler daemon config/control surface through AE API routes.
The routes publish daemon readiness and allow protected manual tick-once
dispatch without letting AG or operators write directly to AE persistence.

## API

- `GET /api/v1/artifact-retention/scheduler-daemon-config`
- `POST /api/v1/artifact-retention/scheduler-daemon-controls`

The scheduler config route now advertises both daemon endpoints in `api_routes`.

## Implementation

- Added the two AE routes beside the existing scheduler config route.
- Used route-local imports for the scheduler module to avoid circular imports.
- Added an injectable scheduler lease store for isolated tests and later
  PostgreSQL wiring.
- The control route forwards AE-owned artifact store, JobQueue, history store,
  scheduler config, lease store, request IDs, trace IDs, and idempotency key to
  the Slice 0517 dispatch facade.

## Evidence

Regression tests cover:

- authenticated daemon config route;
- unauthorized config route;
- blocked `start_daemon` control response;
- `manual_tick_once` control dispatch through artifact store, lease, JobQueue,
  and tick-once result;
- scheduler config route map exposure;
- metadata-only redaction checks.

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py::test_artifact_retention_scheduler_config_route_returns_runtime_surface tests/test_nex_ae_artifacts.py::test_artifact_retention_scheduler_daemon_routes_surface_control_dispatch tests/test_nex_ae_artifact_retention_scheduler.py -q --cov=nex_ae_api.artifacts --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
```

Result: `61 passed`.

## Guardrails

- AE owns the daemon control route.
- AG still performs no direct database writes and no direct JobQueue enqueue.
- `start_daemon` remains blocked by policy.
- No daemon process or continuous loop is started.
