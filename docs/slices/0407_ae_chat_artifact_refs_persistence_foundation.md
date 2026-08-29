# Slice 0407: AE Chat Artifact Refs Persistence Foundation

## Scope

Persist AE chat interaction records and attached artifact references through a
SQLAlchemy-backed store while preserving the existing in-memory route behavior
for mock regression tests.

## Decisions

- `SqlAlchemyChatInteractionStore` maps the existing chat interaction response
  shape onto `ae_chat_interactions`.
- Attached artifact cards are stored in `ae_chat_artifact_refs`, keyed by
  `(chat_interaction_id, artifact_id, artifact_version_id)` to keep repeated
  attach calls idempotent.
- The child table keeps indexed owner, chat, artifact, and source-generation
  columns while storing UI-oriented lists/maps such as formats, routes, quality
  summary, and actions as JSONB.
- SQLAlchemy persistence is selected automatically only when the service app has
  `app.state.nex_persistence.api_session_factory`; explicit test stores still
  override defaults.
- SQLite regression uses the same store methods with JSON stored as text.

## Evidence

- `./.venv/bin/pytest tests/test_nex_ae_chat.py tests/test_database_schema_foundation.py -q --cov=nex_ae_api.chat --cov-branch --cov-report=term-missing`
  - `67 passed, 1 warning`
  - `services/nex-ae-api/nex_ae_api/chat.py` coverage `99%`
- `NEX_AE_TEST_DATABASE_URL=... ./.venv/bin/python scripts/db/run_migrations.py --service nex-ae-api --profile test`
  - `applied=0407_ae_chat_artifact_refs_foundation`
- `scripts/quality/run_quality_gate.sh`
  - `2940 passed, 1 warning`
  - `statement_coverage=98.70% threshold=95.00%`
  - `branch_coverage=96.17% threshold=85.00%`
