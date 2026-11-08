# P8-S08: EOS DB Bootstrap

Completed on 2026-10-21. NeX-EOS now owns an active PostgreSQL migration
stream, pooled SQLAlchemy runtime, transaction boundary, and protected test
database reset helper. This Slice creates no EOS business table.

## Scope

- Registered `nex-eos` dev/test profiles in the canonical migration runner.
- Started the EOS stream at `2500_eos_schema_migrations_baseline`.
- Reused the shared database settings, pool, engine, session factory, and
  `SqlAlchemyUnitOfWork` implementation.
- Exposed API and worker pool profiles through one EOS runtime builder.
- Attached the optional API database runtime to the EOS application when
  `NEX_EOS_DATABASE_URL` is configured; invalid configured values fail closed.
- Added a protected `nex_eos_test` reset helper.

## Database Decisions

The service-owned PostgreSQL role is `nex_eos_user`. The canonical local
databases are `nex_eos_dev` and `nex_eos_test`. Credentials remain outside
source control.

The reset helper requires all of the following before mutation:

1. the exact `RESET_NEX_EOS_TEST` confirmation value;
2. a PostgreSQL URL naming `nex_eos_test` and `nex_eos_user`;
3. matching `current_database()` and `current_user` values from the live
   connection.

It truncates only public tables matching `eos_[a-z0-9_]+`, uses quoted SQL
identifiers, restarts identities, and preserves `schema_migrations`. Any failed
operation is rolled back and returned through a stable error code without
exposing the database URL.

## P8-S09 Boundary

`eos_business_operation`, `eos_idempotency`, `eos_outbox`, shared JobQueue
tables, and domain write routes are not introduced here. P8-S09 owns the
BusinessOperation/Idempotency/Outbox transaction infrastructure.

## Verification

- Focused EOS S07/S08 regression: `38 passed`.
- Shared migration/database/tooling regression: `78 passed`.
- EOS Slice Gate: `38 passed`, protected smoke skipped by default, statement
  coverage `100%`, branch coverage `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Protected PostgreSQL smoke: `1 passed` against the actual
  `nex_eos_user@nex_eos_test` database.
- Actual dev migration: first run applied `2500`; second run skipped `2500`.
- Actual test migration: first run applied `2500`; second run skipped `2500`.
- The protected smoke created an isolated schema for fresh/re-run migration,
  proved transaction rollback, reset a disposable `eos_` table, preserved the
  baseline migration, and removed all probe tables and schemas.
- Final test DB inventory contained only public `schema_migrations` with the
  `2500_eos_schema_migrations_baseline` row.
- Remote model providers were not required.

The Platform Full Gate was not repeated. P8-S08 follows the agreed Slice Gate
cadence; the P8 wave-closing Slice will run the Full Gate.
