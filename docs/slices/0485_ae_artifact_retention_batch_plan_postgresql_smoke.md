# Slice 0485: AE artifact retention batch plan PostgreSQL smoke

Add protected PostgreSQL evidence for the retention batch plan API against the
real AE test database.

## Scope

- Added
  `scripts/smoke/run_ae_artifact_retention_batch_plan_postgres_smoke.py`.
- Registered the runner in the default quality gate as skipped until explicitly
  enabled.
- Added SQLite-harness regression coverage for runner skip, profile guard,
  missing DB URL, migration failure, execution failure, successful route/DB
  cross-checks, cleanup, summary output, and redaction.

## Protected Smoke Behavior

The runner executes only when
`NEX_AE_ARTIFACT_RETENTION_BATCH_PLAN_POSTGRES_SMOKE=1` is set and the resolved
AE database profile is `test`.

When enabled, it:

- resolves `NEX_AE_TEST_DATABASE_URL`;
- applies current `nex-ae-api` migrations;
- creates three rendered artifacts in `nex_ae_test`;
- marks all three logically deleted and ages two beyond the 30-day cutoff;
- calls `GET /api/v1/artifact-retention/batch-plan`;
- verifies route counts and direct DB counts agree;
- confirms rows and materialized files are retained because the endpoint is a
  read-model only;
- cleans up generated artifacts and handoffs.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_batch_plan_postgres_smoke.py -q --cov=scripts/smoke/run_ae_artifact_retention_batch_plan_postgres_smoke.py --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_BATCH_PLAN_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<test-db-url> ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_batch_plan_postgres_smoke.py --summary
scripts/quality/run_quality_gate.sh
```
