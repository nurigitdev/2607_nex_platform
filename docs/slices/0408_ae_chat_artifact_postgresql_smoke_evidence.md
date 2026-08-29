# Slice 0408: AE Chat Artifact PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE chat-to-artifact reference
runtime path introduced in Slice 0407.

## Decisions

- The smoke is protected by `NEX_AE_CHAT_ARTIFACT_POSTGRES_SMOKE=1` and only
  allows the `test` profile because it writes to a real database.
- The runner applies `nex-ae-api` migrations, boots the AE chat routes with the
  SQLAlchemy-backed persistence factory, creates a chat interaction, attaches
  an artifact reference twice to prove idempotence, reads the chat record and
  artifact links, observes PostgreSQL tables/indexes/JSONB types, and deletes
  its own rows.
- Evidence redaction rejects raw database URLs, database passwords, local data
  paths, raw source text, and private prompt fragments.
- The smoke is wired into the default quality gate as a skipped protected check
  and into the PostgreSQL test smoke suite as an enabled child stage.

## Evidence

- `./.venv/bin/pytest tests/test_ae_chat_artifact_postgres_smoke.py tests/test_smoke_helpers.py tests/test_nex_ae_chat.py tests/test_database_schema_foundation.py -q --cov=run_ae_chat_artifact_postgres_smoke --cov=run_postgres_test_smoke_suite --cov=nex_ae_api.chat --cov-branch --cov-report=term-missing`
  - `278 passed, 1 warning`
  - `scripts/smoke/run_ae_chat_artifact_postgres_smoke.py` coverage `100%`
- Protected PostgreSQL smoke against `NEX_AE_TEST_DATABASE_URL`
  - `ae_chat_artifact_postgres_smoke=pass service=nex-ae-api db_env=NEX_AE_TEST_DATABASE_URL interaction_id=6031d293-1f26-4323-8970-b29c7acb04bd artifact_id=artifact-chat-smoke-280b81c56124 rows=2 deleted_interactions=1 deleted_artifact_refs=1`
- `scripts/quality/run_quality_gate.sh`
  - `2952 passed, 1 warning`
  - `statement_coverage=98.70% threshold=95.00%`
  - `branch_coverage=96.18% threshold=85.00%`
  - default protected smoke state: `ae_chat_artifact_postgres_smoke=skipped reason=NEX_AE_CHAT_ARTIFACT_POSTGRES_SMOKE`
