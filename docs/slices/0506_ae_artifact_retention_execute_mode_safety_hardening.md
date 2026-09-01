# Slice 0506: AE Artifact Retention Execute-Mode Safety Hardening

## Scope

Slice 0506 hardens the AE artifact retention physical purge boundary before
storage and database adapters are expanded.

## Behavior

- Execute-mode purge now requires an explicit operator approval snapshot in
  addition to the existing delete, storage mutation, and database row deletion
  guard flags.
- Approval snapshots are scoped to `tenant_id`, `workspace_id`, and
  `owner_user_id` so a reviewed dry-run plan cannot be reused across another
  owner boundary.
- Missing approval with all delete guards enabled returns a metadata-only
  `BLOCKED` execution with `blocked_reason=operator_approval_required`; no
  artifact rows or rendered storage files are deleted.
- Successful execute records include the normalized approval snapshot inside
  the existing execution JSON payload. No PostgreSQL DDL change is required in
  this slice.

## Guardrails

- Dry-runs cannot carry delete flags or operator approval.
- Successful execute requires all delete flags and matching operator approval.
- Operator approval must be metadata-only and must not contain storage refs,
  DB URLs, passwords, or raw rendered content.
- Existing retention history list/read-model surfaces continue to avoid
  exposing raw execution payloads.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py tests/test_ae_artifact_retention_purge_postgres_smoke.py -q --cov=nex_ae_api.artifacts --cov=run_ae_artifact_retention_purge_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_PURGE_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_purge_postgres_smoke.py --summary
NEX_AE_ARTIFACT_RETENTION_HISTORY_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_history_postgres_smoke.py --summary
NEX_AE_ARTIFACT_RETENTION_HISTORY_QUERY_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py --summary
```
