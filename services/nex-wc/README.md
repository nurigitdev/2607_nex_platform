# NeX-WC

NeX-WC is the service-owned system of record for P7 WorkItems, routing,
claims, assignments, WorkResults, and durable WC events.

The service reuses `nex_runtime.JobQueue` as a library while operating its own
`service_jobs` table in the WC database. WC domain records are not common jobs.

## Runtime

```bash
python scripts/dev/run_service.py nex-wc
```

The default port is `8106`. PostgreSQL mode uses `NEX_WC_DATABASE_URL`; test
migrations use `NEX_WC_TEST_DATABASE_URL`.

## P7-S1 API

```text
POST /api/v1/work-items
GET  /api/v1/work-items/{work_item_id}
GET  /api/v1/work-items/{work_item_id}/status
```

All routes require a service token for audience `nex-wc`. Reads additionally
require `X-NeX-Tenant-Id` so WorkItem identity is always tenant-scoped.
