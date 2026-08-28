# Slice 0406: AE Artifact PostgreSQL Smoke Evidence

## Scope

Add a protected PostgreSQL smoke runner for the AE artifact runtime persistence
path and prove the persisted route flow against `nex_ae_test`.

## Decisions

- The smoke is protected by `NEX_AE_ARTIFACT_POSTGRES_SMOKE=1` and only allows
  the `test` profile, because it creates and deletes rows in a real database.
- The runner applies `nex-ae-api` migrations before execution, then exercises
  handoff create/read, artifact create/read, version list, render job creation,
  file metadata, preview, download, DB observation, and cleanup.
- A real PostgreSQL run exposed that `ae_artifact_handoffs` needed the same
  `trace_id` and `request_id` correlation columns already used by the runtime
  store and SQLite regression harness. The 0402 fresh schema now includes those
  columns, and the 0406 migration backfills already-applied databases.
- Evidence redaction rejects raw database URLs, database passwords, local
  storage roots, raw source text, and private prompt fragments.
- The default quality gate keeps the smoke skipped unless explicitly enabled;
  live DB proof is captured as a separate protected evidence step.

## Evidence

- `./.venv/bin/pytest tests/test_database_schema_foundation.py tests/test_nex_ae_artifacts.py tests/test_ae_artifact_postgres_smoke.py tests/test_ae_artifact_runtime_persistence_storage_boundary_audit.py -q`
  - `79 passed, 1 warning`
- Protected PostgreSQL smoke against `NEX_AE_TEST_DATABASE_URL`
  - `ae_artifact_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL rows=8 markdown_files=1 deleted_artifacts=1 deleted_handoffs=1`
- `scripts/quality/run_quality_gate.sh`
  - `2930 passed, 1 warning`
  - `statement_coverage=98.69% threshold=95.00%`
  - `branch_coverage=96.13% threshold=85.00%`
  - default protected smoke state: `ae_artifact_postgres_smoke=skipped reason=NEX_AE_ARTIFACT_POSTGRES_SMOKE`
