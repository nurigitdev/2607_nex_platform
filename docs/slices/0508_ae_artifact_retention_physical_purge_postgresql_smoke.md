# Slice 0508: AE Artifact Retention Physical Purge PostgreSQL Smoke

## Scope

Slice 0508 adds protected PostgreSQL smoke evidence for the Slice 0506/0507
physical purge safety and adapter boundary.

## Behavior

- Added `run_ae_artifact_retention_physical_purge_postgres_smoke.py`.
- The smoke is skipped by default and only runs when
  `NEX_AE_ARTIFACT_RETENTION_PHYSICAL_PURGE_POSTGRES_SMOKE=1` is set.
- When enabled, it delegates to the existing purge PostgreSQL smoke against
  `NEX_AE_TEST_DATABASE_URL`, then verifies:
  - the operator approval gate blocks execute before deletion,
  - rendered storage files are deleted,
  - child artifact graph rows are deleted,
  - handoff lineage remains retained,
  - cleanup completes against the real test DB.

## Guardrails

- Only the `test` profile is accepted.
- Evidence is redacted and must not expose DB URLs, passwords, storage roots,
  `storage_ref`, `content_base64`, or rendered payloads.
- The default quality gate runs the smoke in protected skip mode.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_physical_purge_postgres_smoke.py tests/test_ae_artifact_retention_purge_postgres_smoke.py -q --cov=run_ae_artifact_retention_physical_purge_postgres_smoke --cov=run_ae_artifact_retention_purge_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_PHYSICAL_PURGE_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_physical_purge_postgres_smoke.py --summary
```
