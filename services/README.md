# NeX-Platform Services

Status: Slice 0095 CX processing PostgreSQL OperationalEvent smoke.

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

Route and worker code should emit operational events through the shared
`OperationalEventEmitter`. It resolves the service persistence store from
`app.state.nex_persistence` when available, keeps memory fallback behavior for
local regression, and offers `safe_emit()` for observability writes that must not
fail the primary request or job.

Slice 0005 adds a mock-only OA service token path:

- `POST /api/v1/auth/service-token` on `nex-oa`.
- `POST /api/v1/auth/introspect` on `nex-oa`.
- `GET /internal/v1/auth/service-claim` on every backend service.
