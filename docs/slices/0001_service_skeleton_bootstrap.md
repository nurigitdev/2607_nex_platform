# Slice 0001 Service Skeleton Bootstrap

Status: Implemented.

Backlog candidate: `S1-001` Repository and service skeleton bootstrap.

## Scope

Slice 0001 creates the first runnable monorepo skeleton:

- Five backend service shells: `nex-oa`, `nex-ag`, `nex-ae-api`, `nex-cx`, and
  `nex-mo`.
- One Korean-default AE web shell under `apps/nex-ae-web`.
- Runtime markers for Python 3.12 and Node 22.
- Local environment example with service-owned database URLs.
- Developer scripts for running backend service shells and smoke-checking DB and
  endpoint readiness.

## Requirement Coverage

| Requirement | Coverage |
| --- | --- |
| `PLAT-FR-001` | Every backend service exposes `/health`, `/ready`, and `/version`. |
| Environment freeze | Workspace directories now match the first monorepo-style implementation path. |
| Service ownership | Each backend service has its own package and database env var. |

## Service Shells

| Service | Package | Port | Database Env |
| --- | --- | ---: | --- |
| `nex-oa` | `nex_oa` | 8101 | `NEX_OA_DATABASE_URL` |
| `nex-ag` | `nex_ag` | 8102 | `NEX_AG_DATABASE_URL` |
| `nex-ae-api` | `nex_ae_api` | 8103 | `NEX_AE_DATABASE_URL` |
| `nex-cx` | `nex_cx` | 8104 | `NEX_CX_DATABASE_URL` |
| `nex-mo` | `nex_mo` | 8105 | `NEX_MO_DATABASE_URL` |

## Evidence Commands

```bash
./.venv/bin/python scripts/smoke/check_db_readiness.py
./.venv/bin/python scripts/smoke/check_backend_service_endpoints.py
git diff --check
```

The smoke scripts require local database URLs to be present in environment
variables or `.env.local`. Real credentials must stay out of git.

## Follow-Up

Slice 0002 should add the single-pass quality gate command and test coverage
reporting. Slice 0003 should bootstrap the contract package layout.
