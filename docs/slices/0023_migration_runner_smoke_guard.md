# Slice 0023 Migration Runner Smoke Guard

Status: Implemented.

Backlog candidate: `S3-003` service-owned migration runner and smoke guard.

Requirement coverage: `TRACE-PLAT-001`, `QA-FR-001`, `DEV-FR-001`.

## Scope

Slice 0023 adds a minimal PostgreSQL migration runner for service-owned
databases:

- Discovers migrations under `database/<service>/migrations/`.
- Reads service database URLs from `.env.local` through existing env loading.
- Keeps a per-service `schema_migrations` table.
- Skips versions that are already applied.
- Supports `--dry-run` for planning without connecting to PostgreSQL.
- Adds baseline `schema_migrations` migrations for OA, AG, and MO so all five
  service databases now have explicit migration directories.

The runner does not store database passwords in source or logs. `.env.local`
remains the local-only place for real credentials.

## Commands

```bash
./.venv/bin/python scripts/db/run_migrations.py --service nex-cx --dry-run
./.venv/bin/python scripts/db/run_migrations.py --all
```

## Files

- `scripts/db/run_migrations.py`
- `database/nex-oa/migrations/0023_schema_migrations_baseline.sql`
- `database/nex-ag/migrations/0023_schema_migrations_baseline.sql`
- `database/nex-mo/migrations/0023_schema_migrations_baseline.sql`
- `tests/test_db_migration_runner.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover migration sorting, SQL shape validation, dry-run
behavior, already-applied migration skipping, and safe missing-env errors.
