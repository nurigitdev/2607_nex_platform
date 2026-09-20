# Slice 0907: CX database and migration drift audit

## Goal

Verify the declared CX migration chain, repository table references, and
PostgreSQL identifier safety before comparing the actual test database.

## Findings

- Thirteen versioned SQL migrations form the current canonical chain.
- Every migration is transaction wrapped and records its own version in
  `schema_migrations`.
- All sixteen core CX tables are declared or intentionally renamed, and the
  repository references each one.
- Table, index, and constraint identifiers remain below PostgreSQL's 63-byte
  identifier limit. New table naming must preserve this guardrail.
- The migration runner contains an Alembic config builder, but
  `database/nex-cx/alembic` is not configured. The active migration path is the
  versioned SQL runner.

## Decision

Static readiness is `STATIC_CHAIN_CLEAN_RUNTIME_DATABASE_PENDING`. The actual
`nex_cx_test` ledger/schema comparison belongs to Slice 0909.

Before the next schema change, retain exactly one canonical migration history:
either continue the current versioned SQL chain or deliberately activate and
baseline Alembic. Do not maintain two independent histories.

This slice adds no table or migration.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_cx_database_drift_audit.py --summary
./.venv/bin/pytest -q tests/test_cx_database_drift_audit.py \
  --cov=nex_cx.database_drift_audit \
  --cov=run_cx_database_drift_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
audit: PASS migrations=13 core_tables=16 max_identifier=51 issues=0
focused tests: 5 passed; target statement/branch coverage: 100%
aggregate regression: 6307 passed, 1 known warning
statement=75968/76849=98.85359601296048%
branch=17682/18332=96.45428758455161%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
