# NeX-Platform Services

Status: Slice 0151 service log retention PostgreSQL smoke evidence.

Each backend service owns its package, database, and public service boundary.
The `_shared` runtime contains service shell behavior and the Slice 0005
local-mock service claim validator; it must not grow service-private database
models or domain ownership.

| Service | Package | Default Port | Database Env |
| --- | --- | ---: | --- |
| `nex-oa` | `nex_oa` | 8101 | `NEX_OA_DATABASE_URL` |
| `nex-ag` | `nex_ag` | 8102 | `NEX_AG_DATABASE_URL` |
| `nex-ae-api` | `nex_ae_api` | 8103 | `NEX_AE_DATABASE_URL` |
| `nex-cx` | `nex_cx` | 8104 | `NEX_CX_DATABASE_URL` |
| `nex-mo` | `nex_mo` | 8105 | `NEX_MO_DATABASE_URL` |

Run one service:

```bash
./.venv/bin/python scripts/dev/run_service.py nex-oa
```

Run all service shells:

```bash
./.venv/bin/python scripts/dev/run_all_services.py
```

Both scripts load `.env.local` when present. Keep `.env.local` out of git.

Persistent schema foundations live under `database/<service>/migrations/`.
Service migrations must only reference tables in the owning service database.

Runtime persistence is selected explicitly:

- `NEX_PERSISTENCE_MODE=memory` is the default and keeps local regression
  mock-first.
- `NEX_<SERVICE>_PERSISTENCE_MODE=postgres` switches that service entrypoint to
  SQLAlchemy-backed JobQueue and OperationalEventStore adapters.
- Service-specific mode envs override the global mode. PostgreSQL mode requires
  the matching service database URL and should be paired with migration/smoke
  checks.

AG operations projections can also attach read-only PostgreSQL sources for
selected service databases:

```text
NEX_AG_OPERATIONS_SOURCE_MODE=postgres
NEX_AG_OPERATIONS_SOURCE_PROFILE=dev
NEX_AG_OPERATIONS_SOURCE_SERVICES=nex-ae-api,nex-ag,nex-cx,nex-mo,nex-oa
```

The default mode is `memory`. PostgreSQL source mode uses the selected
service-owned database envs, wraps JobQueue, OperationalEventStore, and
WorkerHeartbeatStore adapters as read-only, and keeps AG from writing into
other service databases.

Route and worker code should emit operational events through the shared
`OperationalEventEmitter`. It resolves the service persistence store from
`app.state.nex_persistence` when available, keeps memory fallback behavior for
local regression, and offers `safe_emit()` for observability writes that must not
fail the primary request or job.

Structured service logs use `service_log_entry.v1` through the shared
`nex_runtime.service_logs` builder, validator, emitter, safe emission result,
store abstraction, app-state fallback, and SQLAlchemy-backed
`service_log_entries` adapter. Services should emit explicit redaction-safe
diagnostic log entries; this is not a blanket capture of all Python log lines.
AG can read service-local structured logs through
`GET /admin/v1/operations/logs` and `GET /admin/v1/operations/logs/{log_id}`
using the operations source registry. The registry wraps service log stores as
read-only sources, so AG search/debug projections do not mutate service data.
AG issue candidate projection also treats `ERROR` and `CRITICAL` structured
service logs as candidate signals when a service log store is configured.
Cross-service trace timelines include correlated structured service log entries
alongside jobs and operational events when log stores are configured.
Operations rollups include structured service log totals, severity counts,
logger counts, and redaction counts for configured log stores.
AG exposes the active structured service log query and retention policy at
`GET /admin/v1/operations/logs/policy` and a read-only retention candidate
projection at `GET /admin/v1/operations/logs/retention/dry-run`; retention
execution evidence uses `service_log_retention_execution.v1`. Service log
stores support guarded retention purge capability through
`POST /internal/v1/service-logs/retention/purge`. AG can dispatch that control
path through `POST /admin/v1/operations/logs/retention/{service_id}/purge` and
returns `ag_service_log_retention_dispatch.v1`. Execute-mode dispatch requires
`delete_enabled=true`; otherwise AG blocks before calling the target service.
The default quality gate runs `run_ag_service_log_retention_smoke.py`, which
exercises dry-run dispatch, unsafe execute blocking, guarded execute deletion,
and AG audit events in-process. The optional PostgreSQL test-profile smoke
`run_postgres_service_log_retention_smoke.py` verifies the same retention
guardrails against a service-local SQLAlchemy store and deletes only temporary
smoke rows. Scheduled enforcement workers are future implementation steps.

Service workers should also report `worker_heartbeat.v1` payloads through the
shared worker heartbeat runtime. It defines the status vocabulary, emitter,
safe emission result, stale-threshold helper, summary shape, in-memory store,
SQLAlchemy-backed service table adapter, and `app.state.nex_persistence` lookup
path so AG can project worker liveness across services.

The shared `nex_runtime.worker_runner` module provides a small bounded worker
execution helper around service-owned JobQueue adapters. It claims jobs by
`job_type`, emits STARTING/BUSY/IDLE/ERROR heartbeats through the injected
worker heartbeat emitter, optionally writes structured service logs through an
injected `ServiceLogEmitter`, calls a service-owned job handler, and completes or
fails the job without adding service-private domain logic to `_shared`.

JobQueue adapters support a common retry decision path. Handler failures can
requeue RUNNING jobs with bounded exponential backoff by updating
`available_at`; exhausted or non-retryable jobs are represented as `FAILED`
with `error.dead_lettered=true`. The common job status enum is unchanged, so the
existing PostgreSQL DDL and contract status vocabulary remain stable.

Every service entrypoint exposes an authenticated internal job control surface:

```text
GET /internal/v1/jobs/{job_id}
POST /internal/v1/jobs/{job_id}/cancel
POST /internal/v1/jobs/{job_id}/retry
POST /internal/v1/jobs/{job_id}/replay
```

These routes operate only on the service-local `SERVICE_PERSISTENCE.job_queue`
adapter and require a service claim with the target service as audience. The
projection intentionally omits job `payload`.

Dead-letter operator replay is planned as a new queued job, not a mutation of
the failed source job. The shared `plan_dead_letter_replay()` helper requires a
FAILED job with `error.dead_lettered=true`, a non-empty operator id, and a
bounded operator reason. It copies service-private payload for service-local
execution but stores only safe source metadata in `replay_lineage`. The
service-local replay endpoint returns a payload-redacted replay job projection
and a safe source-job summary. AG replay endpoint wiring and audit emission are
explicit operator workflow steps.

AG job control dispatches are audited as AG-owned operational events. Successful
dispatches emit `ag.job_control.succeeded`; failed dispatches emit
`ag.job_control.failed`. Audit emission is safe: event-store errors are returned
as audit summaries but do not block the underlying control response.

The AG operator-facing cancel/retry/replay routes and the CX service-local
target routes are documented in OpenAPI. The default quality gate runs
`run_ag_job_control_smoke.py`, which exercises AG dispatch, service-local queue
mutation, dead-letter replay creation, audit events, and payload redaction
in-process.

AG also exposes an operator-facing replay dispatch path:

```text
POST /admin/v1/operations/jobs/{service_id}/{job_id}/replay
```

It forwards explicit replay metadata to the service-local replay endpoint and
audits successful dispatch as `ag.job_control.succeeded` with
`details.action=replay`. The replay response remains payload-redacted while
exposing safe source summary and lineage metadata for operator debugging.

AG operations dashboard snapshots expose `replay_candidates` for failed jobs
with `error.dead_lettered=true`. Issue candidates also include
`dead_letter_replay_available.v1` as a `WARNING` actionability signal with the
AG replay control path and required payload fields.

`nex-cx` processing routes still support the MVP inline run path, but they now
also expose an enqueue-first path for background worker execution. Inline runs
report `cx-processing-inline-worker`; background execution uses
`cx-processing-worker`. Both use `cx.document_processing.worker` so the same
heartbeat projection and stuck-job rules apply across execution modes.

The CX inline worker also emits operational events for `BUSY`, `IDLE`, and
`ERROR` lifecycle transitions. These events are separate from the processing
started/succeeded/failed events so AG can correlate job state, heartbeat state,
and event timeline without reading worker heartbeat storage directly.

AG exposes a worker detail projection at
`GET /admin/v1/operations/workers/{service_id}/{worker_id}`. The projection
reads the selected service worker heartbeat, correlates `active_job_id` through
the service job queue, and returns matching worker lifecycle operational events
as one debug surface.

The mock-first AG operations dashboard smoke exercises both the worker runtime
list and worker detail projection so the heartbeat/job/event correlation path is
covered by the default quality gate.

PostgreSQL test-profile smoke evidence can be executed as one guarded suite:

```text
NEX_POSTGRES_TEST_SMOKE_SUITE=1
NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE=test
NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES=nex-ae-api,nex-ag,nex-cx,nex-mo,nex-oa
NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE=nex-cx
```

The suite runs readiness, migrations, common JobQueue/Event smokes, dead-letter
replay smoke, ServiceLogStore smoke, ServiceLog retention smoke, the
cross-service operations pack, CX processing PostgreSQL smokes, and AG
cross-service observability smoke. It is skipped by default in the quality gate
and refuses non-test profiles because it writes temporary smoke rows.

The ServiceLogStore PostgreSQL smoke can also be run directly for one service:

```text
NEX_DB_SERVICE_LOG_SMOKE=1
NEX_DB_SERVICE_LOG_SMOKE_SERVICE=nex-cx
NEX_DB_SERVICE_LOG_SMOKE_PROFILE=test
```

The ServiceLog retention PostgreSQL smoke can also be run directly for one
service:

```text
NEX_DB_SERVICE_LOG_RETENTION_SMOKE=1
NEX_DB_SERVICE_LOG_RETENTION_SMOKE_SERVICE=nex-cx
NEX_DB_SERVICE_LOG_RETENTION_SMOKE_PROFILE=test
```

Slice 0005 adds a mock-only OA service token path:

- `POST /api/v1/auth/service-token` on `nex-oa`.
- `POST /api/v1/auth/introspect` on `nex-oa`.
- `GET /internal/v1/auth/service-claim` on every backend service.
