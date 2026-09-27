# Slice 1007: AE database and migration drift audit

## Goal

Verify the static AE migration chain, repository/table traceability, migration
runner readiness, and PostgreSQL identifier safety before comparing the actual
test database in Slice 1010.

## Decision

- Versioned SQL plus `schema_migrations` remains the canonical migration path.
- Alembic is not configured for AE. Exactly one canonical history must be kept;
  this must be revisited before introducing the next schema change.
- The migration chain and core persisted-table references are complete.
- Historical daemon supervisor DDL contains explicit identifiers longer than
  PostgreSQL's 63-byte limit. PostgreSQL truncates these names, while a later
  migration adds short canonical indexes without removing the old duplicates.
- Canonical names and duplicate indexes must be reconciled before the next
  schema change; S101 records the drift but does not mutate existing schema.
- Actual `nex_ae_test` comparison remains mandatory in Slice 1010.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ae_database_drift_audit.py --summary
./.venv/bin/pytest -q tests/test_ae_database_drift_audit.py \
  --cov=nex_ae_api.database_drift_audit \
  --cov=run_ae_database_drift_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

- Audit: PASS for `22` migrations, `38` declared tables, `15` core tables,
  and `158` SQL identifiers; evidence issues `0`.
- Identifier drift: `8` source identifiers exceed the `63`-byte PostgreSQL
  limit; the longest is `70` bytes. One classified remediation finding remains.
- Focused tests: `5 passed`; the audit module and runner both reached `100%`
  statement and branch coverage.
- Slice Gate: `1,887 passed`; statement coverage `97.75%`; branch coverage
  `95.42%`.
- Contract validation: `92` schemas, `145` examples, `109` negative examples,
  and `7` OpenAPI documents passed.
