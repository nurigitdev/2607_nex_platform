# Slice 0082: Service migration profile and Alembic foundation

## Intent

Slice 0082 prepares database migration execution for the user-created dev and
test databases. It keeps the current service-owned SQL migrations as the
authoritative execution format while adding the profile and Alembic foundation
needed for later SQLAlchemy model work.

## Runtime Behavior

- `scripts/db/run_migrations.py` now supports `--profile dev` and
  `--profile test`.
- `dev` uses `NEX_OA_DATABASE_URL`, `NEX_AG_DATABASE_URL`,
  `NEX_AE_DATABASE_URL`, `NEX_CX_DATABASE_URL`, and `NEX_MO_DATABASE_URL`.
- `test` uses the matching `NEX_*_TEST_DATABASE_URL` values.
- Database URL lookup reuses the shared `nex_runtime.database` placeholder
  guard instead of duplicating password checks.
- Dry-run still does not require a database URL or open a connection.

## Alembic Boundary

Existing migrations remain SQL files in `database/<service>/migrations/`. The
runner now exposes `ServiceMigrationSettings` and `build_alembic_config` so each
service has a stable Alembic config shape:

- service id
- database profile
- database env name
- SQLAlchemy URL
- future `database/<service>/alembic/` script location

No Alembic revision files are generated in this slice.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_db_migration_runner.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
