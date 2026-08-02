# NeX-Platform Services

Status: Slice 0001 service shell baseline.

Each backend service owns its package, database, and public service boundary.
The `_shared` runtime currently contains only the Slice 0001 shell behavior for
`/health`, `/ready`, and `/version`; it must not grow service-private database
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
