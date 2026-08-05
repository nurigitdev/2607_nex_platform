# Slice 0102: AG Operation Source Readiness Projection

## Scope

Slice 0102 adds a read-only AG source readiness endpoint:

```text
GET /admin/v1/operations/sources
```

The endpoint reports the AG operations source runtime and the per-service
source status used by operations projections.

## Response Shape

The projection schema version is:

```text
ag_operation_source_readiness_projection.v1
```

Each source row includes:

- `service_id`
- `readiness_status`
- `configured`
- `source_kind`
- `capabilities.jobs`
- `capabilities.events`
- `read_only`
- `job_queue`
- `operational_event_store`
- `database_env`
- `redacted_database_url`

## Readiness Status

- `DEFAULT_MEMORY`: AG is using default mock-first in-memory operations sources.
- `READY`: an explicit operations source is configured for the service.
- `NOT_CONFIGURED`: the runtime is explicit but no source exists for the
  selected service.

## Safety

The projection does not expose raw database URLs or credentials. PostgreSQL
sources are reported with redacted URLs and `read_only=true` when wrapped by
the AG read-only source adapters.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_app.py
```

Observed result:

```text
77 passed
```
