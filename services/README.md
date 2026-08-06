# NeX-Platform Services

Status: Slice 0116 CX processing worker heartbeat integration.

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

Service workers should also report `worker_heartbeat.v1` payloads through the
shared worker heartbeat runtime. It defines the status vocabulary, emitter,
safe emission result, stale-threshold helper, summary shape, in-memory store,
SQLAlchemy-backed service table adapter, and `app.state.nex_persistence` lookup
path so AG can project worker liveness across services.

`nex-cx` processing routes currently run the MVP document pipeline inline, but
they still report the inline worker as `cx-processing-inline-worker` with
`cx.document_processing.worker` so the same heartbeat projection and stuck-job
rules apply before a separate worker process is introduced.

Slice 0005 adds a mock-only OA service token path:

- `POST /api/v1/auth/service-token` on `nex-oa`.
- `POST /api/v1/auth/introspect` on `nex-oa`.
- `GET /internal/v1/auth/service-claim` on every backend service.
