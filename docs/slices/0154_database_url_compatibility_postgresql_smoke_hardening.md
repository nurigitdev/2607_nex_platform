# Slice 0154: Database URL Compatibility and PostgreSQL Smoke Evidence Hardening

## Scope

Slice 0154 hardens the PostgreSQL test smoke path after proving that humans can
reasonably mix two valid URL shapes:

- `postgresql://...` for direct `psycopg` connections
- `postgresql+psycopg://...` for SQLAlchemy engines and Alembic config

Implemented:

- `nex_runtime.database.psycopg_database_url(...)`
- `nex_runtime.database.sqlalchemy_database_url(...)` used by Alembic config
- readiness normalization for SQLAlchemy-style PostgreSQL URLs before direct
  `psycopg.connect(...)`
- migration runner normalization before direct `psycopg.connect(...)`
- readiness evidence fields in the PostgreSQL smoke suite:
  - `configured_url_drivername`
  - `connection_url_drivername`
  - `url_normalized_for_psycopg`

## Compatibility Rule

Runtime code preserves configured database URLs at service settings boundaries.
The adapter that opens the connection is responsible for converting the URL to
the shape it needs.

```text
SQLAlchemy / Alembic path:
postgresql://... -> postgresql+psycopg://...

direct psycopg path:
postgresql+psycopg://... -> postgresql://...
```

This keeps existing `.env.local` values compatible while preventing PostgreSQL
smoke failures caused only by driver-name shape.

## Evidence Boundary

The full quality gate still runs PostgreSQL smokes in skipped mode by default.
Live write/read PostgreSQL execution remains opt-in and restricted to the
`test` profile.

Optional PostgreSQL suite execution:

```bash
NEX_POSTGRES_TEST_SMOKE_SUITE=1 \
NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE=test \
NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE=nex-cx \
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

When service test DB URLs are available, the same suite can validate readiness,
migrations, and all child smoke stages for all five service databases.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest \
  tests/test_nex_runtime_database.py \
  tests/test_db_migration_runner.py \
  tests/test_smoke_helpers.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

PostgreSQL smoke suite:

```text
postgres_test_smoke_suite=pass services=5 profile=test primary=nex-cx stages=13
```

