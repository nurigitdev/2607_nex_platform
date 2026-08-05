# NeX-Platform Database Foundations

Status: Slice 0089 AG JobQueue operations projection foundation.

Each service owns its own database and migrations. Cross-service joins and
foreign keys are intentionally avoided; service APIs and contract records carry
references between services.

## Layout

```text
database/
  nex-oa/
    migrations/
  nex-ag/
    migrations/
  nex-ae-api/
    migrations/
  nex-cx/
    migrations/
  nex-mo/
    migrations/
```

## Ownership

| Service | Database Env | Migration Directory |
| --- | --- | --- |
| `nex-oa` | `NEX_OA_DATABASE_URL` | `database/nex-oa/migrations/` |
| `nex-ag` | `NEX_AG_DATABASE_URL` | `database/nex-ag/migrations/` |
| `nex-ae-api` | `NEX_AE_DATABASE_URL` | `database/nex-ae-api/migrations/` |
| `nex-cx` | `NEX_CX_DATABASE_URL` | `database/nex-cx/migrations/` |
| `nex-mo` | `NEX_MO_DATABASE_URL` | `database/nex-mo/migrations/` |

## Migration Runner

Local migrations are applied by the service-owned runner:

```bash
./.venv/bin/python scripts/db/run_migrations.py --service nex-cx --dry-run
./.venv/bin/python scripts/db/run_migrations.py --service nex-cx --profile test --dry-run
./.venv/bin/python scripts/db/run_migrations.py --all
```

The runner reads `.env.local`, rejects placeholder database URLs, creates the
`schema_migrations` state table before checking applied versions, and executes
only migrations that have not already been recorded.

`--profile dev` reads the primary service database envs and is the default.
`--profile test` reads the matching `NEX_*_TEST_DATABASE_URL` envs so regression
database setup can use the same service-owned migration runner.

Existing migrations remain SQL files under `database/<service>/migrations/`.
The runner now also exposes per-service Alembic configuration objects with
service id, profile, database env, database URL, and future
`database/<service>/alembic/` script locations. Alembic is therefore available
for future SQLAlchemy model revisions without changing the current SQL
migration execution contract.

## SQLite Regression And PostgreSQL Compatibility

PostgreSQL migration SQL is the canonical database schema. SQLite DDL used in
unit tests is only a fast behavioral fixture; it is not a compatibility claim
for PostgreSQL DDL.

Default regression tests use SQLite where practical to keep the suite fast and
to preserve statement and branch coverage for repository behavior. PostgreSQL
specific behavior must be verified by guarded smoke tests against `*_test`
databases, especially for:

- `JSONB` storage and serialization
- `TIMESTAMPTZ` parsing, ordering, and timezone normalization
- boolean and check constraint behavior
- unique constraints and idempotent write races
- row locking and `FOR UPDATE SKIP LOCKED`

DB persistence slices should therefore leave both a fast SQLite regression and
an optional PostgreSQL smoke when the implementation depends on PostgreSQL
runtime semantics.

## Runtime Connection Foundation

Runtime services use `nex_runtime.database` for:

- required database URL lookup and placeholder-password rejection
- SQLAlchemy engine/session factory construction
- service-aware DB pool settings
- request/worker unit-of-work transaction boundaries
- redacted database URL rendering for diagnostics
- `/ready` database identity checks through `select current_database(), current_user`
- optional CX vector database routing

`NEX_CX_VECTOR_DATABASE_URL` is optional. When it is empty, CX vector storage
uses the primary CX database. If vector volume later requires a separate
database, setting this env moves vector access without changing the primary CX
database contract. `NEX_CX_VECTOR_TEST_DATABASE_URL` mirrors that option for
test profiles.

### Pool And Transaction Defaults

`nex_runtime.database.database_pool_settings` resolves service-specific pool
configuration from `NEX_<SERVICE>_DB_*` env names. Empty env values use runtime
defaults.

| Workload | Pool Size | Max Overflow | Statement Timeout |
| --- | ---: | ---: | ---: |
| API request | 5 | 10 | 30000 ms |
| Worker/job | 3 | 3 | 60000 ms |

Supported env suffixes are:

- `DB_POOL_SIZE`
- `DB_MAX_OVERFLOW`
- `DB_POOL_TIMEOUT_SECONDS`
- `DB_POOL_RECYCLE_SECONDS`
- `DB_POOL_PRE_PING`
- `DB_STATEMENT_TIMEOUT_MS`

Worker overrides use `DB_WORKER_*` before falling back to the base service
values, for example `NEX_CX_DB_WORKER_POOL_SIZE`.

Transaction rule: keep DB transactions short. Do not hold an open transaction
while doing file I/O, embedding/reranker/generation provider calls, or other
slow external operations. Pipeline and worker code should record job/event state
in short unit-of-work blocks around each durable state change.

## Service Job Queue Foundation

Each service database owns the same `service_jobs` table shape. It stores the
`common_job.v1` identity and lifecycle fields plus JSONB payload/error slots,
availability and lock fields, and indexes needed for status scans, trace lookup,
and subject lookup.

Runtime code uses `nex_runtime.jobs` for the shared in-memory queue port,
contract-aligned common job builder, status validation, transition rules,
worker claim, summaries, and the persistent `SqlAlchemyJobQueue` adapter.

`SqlAlchemyJobQueue` stores and reads the common job shape through the
service-owned `service_jobs` table. It keeps the external job payload aligned to
`common_job.v1`, preserves idempotent enqueue by `job_type + idempotency_key`,
uses short transactions for enqueue/transition/claim, and supports worker claim
with PostgreSQL `FOR UPDATE SKIP LOCKED` when the backend is PostgreSQL.

Optional PostgreSQL write smoke is guarded by:

```text
NEX_DB_JOBQUEUE_SMOKE=1
NEX_DB_JOBQUEUE_SMOKE_SERVICE=nex-cx
NEX_DB_JOBQUEUE_SMOKE_PROFILE=test
```

The smoke is intentionally limited to the test profile. It applies service
migrations, enqueues a short smoke job, validates idempotency, claims it,
completes it, and removes the smoke row.

AG exposes a read-only job operations projection at
`GET /admin/v1/operations/jobs`. It aggregates injected per-service `JobQueue`
ports, applies service/status/job-type/limit filters, summarizes active and
terminal work, and reports per-service source availability. The default AG
runtime registration remains mock-first; DB-backed queue injection is deferred
until service runtime bootstrap wiring is introduced.

## Operational Event Foundation

Each service database also owns `service_operational_events`. It stores
redaction-safe event identity, service, event type, severity, trace/request,
subject, short message, JSONB details, and creation time. Indexes support AG
service, severity, trace, and event-type scans.

Runtime code uses `nex_runtime.operational_events` for event construction,
sensitive detail redaction, validation, in-memory storage, filtering, summaries,
and the persistent `SqlAlchemyOperationalEventStore` adapter. The SQLAlchemy
adapter stores and reads the `operational_event.v1` shape through the
service-owned `service_operational_events` table while keeping JSONB details
redacted before persistence.

Optional PostgreSQL write smoke is guarded by:

```text
NEX_DB_OPERATIONAL_EVENT_SMOKE=1
NEX_DB_OPERATIONAL_EVENT_SMOKE_SERVICE=nex-cx
NEX_DB_OPERATIONAL_EVENT_SMOKE_PROFILE=test
```

The smoke is intentionally limited to the test profile. It applies service
migrations, appends one redaction-guarded smoke event, validates idempotency,
checks list filters and summary output, and removes the smoke row. AG exposes
the first read-only projection at `/admin/v1/operations/events`.

## Prompt Registry Seeds

Prompt registry seed migrations currently install:

- CX `cx.document_summary.default` for bounded document summaries.
- AE `ae.grounded_chat.default` for grounded chat generation.

Runtime prompt render events store hashes, short previews, variable keys, and
lineage IDs. They do not store raw user prompts.

## Source File Storage

CX stores original file bytes outside PostgreSQL. In local development the
default root is:

```text
/data/nex-platform/cx/source-files
```

Source files use a date and hash-sharded storage key:

```text
YYYYMMDD/<sha256[0:2]>/<sha256[2:4]>/<source_file_id><extension>
```

Example:

```text
20260802/61/28/e7e4cf11-c38a-538e-bef8-9567a456b762.md
```

The database stores metadata, hashes, backend, key, URI, and verification
timestamps. It does not store source file bytes.

## Current Principles

- CX owns content lifecycle persistence: source files, logical documents,
  ACL entries, extraction artifacts, chunks, indexes, summaries, summary
  embeddings, and CX prompt registry records.
- AE owns user-facing chat state, prompt analytics, intent classification,
  user task profiles, automation recommendations, feedback, and AE prompt
  registry records.
- Original file dedupe is scoped to active logical documents for a single
  `tenant_id + owner_user_id + source_sha256`; another user may upload the same
  bytes without learning that the file already exists.
- Vector payloads are not stored in these base tables. The foundation records
  model/profile lineage, vector dimensions, hashes, and optional storage URIs so
  a pgvector or external vector store can be added later.
- Raw user prompts are not stored in analytics tables. Analytics keeps hashes,
  short previews, normalized intent, categories, and outcomes.
