# Slice 0099: AG Runtime DB-Backed Operations Wiring

## Scope

Slice 0099 wires AG operations projections to optional service-owned
PostgreSQL sources at runtime.

Implemented:

- `NEX_AG_OPERATIONS_SOURCE_MODE=memory|postgres`
- `NEX_AG_OPERATIONS_SOURCE_PROFILE=dev|test`
- `NEX_AG_OPERATIONS_SOURCE_SERVICES`
- AG runtime source attachment on `app.state.nex_ag_operations_source_runtime`
- read-only JobQueue and OperationalEventStore wrappers for AG observation
- PostgreSQL-backed source registry construction with service-aware pool
  settings and redacted database URL summaries

Default behavior remains mock-first: `memory` mode does not require database
URLs and leaves the existing in-memory operations projections unchanged.

## Runtime Rule

AG may observe selected service databases for operational monitoring, but it
must not write into service-owned databases. PostgreSQL operations sources are
therefore wrapped as read-only:

- job reads: `get_job`, `list_jobs`
- event reads: `get_event`, `list_events`
- job writes such as `enqueue` or `start_job`: rejected
- event writes such as `append`: rejected

## Database Profiles

`dev` reads each service's primary database env, for example
`NEX_CX_DATABASE_URL`.

`test` reads matching test database envs, for example
`NEX_CX_TEST_DATABASE_URL`, so guarded smoke tests can exercise the same AG
runtime wiring without touching development data.

## Evidence

Regression coverage should verify:

- memory mode does not require DB envs
- PostgreSQL mode builds selected read-only sources
- duplicate service selections are normalized deterministically
- invalid mode, profile, service id, missing URL, and placeholder URL fail fast
- read-only wrappers allow reads and reject writes

## Follow-Up

Slice 0100 should add a guarded cross-service observability smoke that writes
CX processing job/event rows into the CX test database and verifies AG can read
them through this DB-backed operations source registry.
