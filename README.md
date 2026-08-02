# NeX-Platform

Status: Slice 0001 service skeleton baseline.

NeX-Platform is being built as a monorepo-style workspace with separately owned
services, contracts, tests, scripts, and app shells. The canonical planning
entry point is [docs/README.md](docs/README.md).

## Workspace Layout

```text
apps/
  nex-ae-web/
services/
  nex-oa/
  nex-ag/
  nex-ae-api/
  nex-cx/
  nex-mo/
  _shared/
docs/
scripts/
```

## Local Setup

Install backend dependencies:

```bash
./.venv/bin/pip install -r requirements.txt
```

Create local environment values:

```bash
cp .env.example .env.local
```

Then fill `.env.local` with local-only database passwords. Do not commit
`.env.local`.

Run all backend service shells:

```bash
./.venv/bin/python scripts/dev/run_all_services.py
```

Run the AE web shell:

```bash
npm --prefix apps/nex-ae-web run dev
```

## Service Ports

| Service | Port |
| --- | ---: |
| `nex-oa` | 8101 |
| `nex-ag` | 8102 |
| `nex-ae-api` | 8103 |
| `nex-cx` | 8104 |
| `nex-mo` | 8105 |
| `nex-ae-web` | 5173 |

Every backend shell exposes:

- `GET /health`
- `GET /ready`
- `GET /version`

## Slice Notes

- [Slice 0000 Documentation Baseline](docs/README.md)
- [Slice 0001 Service Skeleton Bootstrap](docs/slices/0001_service_skeleton_bootstrap.md)
