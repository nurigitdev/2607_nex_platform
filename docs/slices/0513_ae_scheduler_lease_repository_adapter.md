# Slice 0513: AE Scheduler Lease Repository Adapter

## Scope

Add the persistence adapter for AE artifact retention scheduler leases without
starting a daemon loop or executing retention work automatically.

## Contract

- The repository API supports `ensure_available`, `get`, `acquire`, and
  `release`.
- `ArtifactRetentionSchedulerLeaseStore` remains the deterministic in-memory
  regression implementation.
- `SqlAlchemyArtifactRetentionSchedulerLeaseStore` uses the same request,
  record, decision, and release contract from Slice 0512.
- Duplicate requests with the same scheduler, owner, operation, and
  idempotency key return the current held lease.
- A different request is blocked while an existing held lease has not expired.
- Released or expired records allow a new acquisition with an incremented
  fencing token.

## Persistence

PostgreSQL migration
`database/nex-ae-api/migrations/0513_ae_artifact_retention_scheduler_lease.sql`
adds `ae_artifact_retention_scheduler_leases`.

The table stores scheduler lease metadata, fencing token, idempotency key,
timestamps, guardrails, and metadata. PostgreSQL uses `JSONB` for structured
fields; SQLite regression uses the same adapter with JSON strings.

## Guardrails

- Scheduler daemon auto-start remains disabled.
- Continuous scheduler loops remain disabled.
- No job is enqueued by the repository adapter itself.
- No worker execution or purge mutation is performed by the repository adapter.
- Lease records remain metadata-only and exclude database URLs, storage paths,
  raw artifact payloads, and raw execution payloads.

## Evidence

Regression coverage checks:

- in-memory lifecycle, duplicate idempotency, busy, release, and reacquire;
- expired lease replacement with fencing token increment;
- SQLAlchemy SQLite lifecycle and unavailable-table error mapping;
- default store factory behavior with and without persistence;
- migration loader discovery of the new AE scheduler lease migration.

## Next

- Slice 0514: Scheduler tick-once runtime wiring.
- Slice 0515: Scheduler tick-once PostgreSQL smoke evidence.
