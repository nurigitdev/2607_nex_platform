# Slice 1014: AE Workspace and Activity Persistence Schema

## Goal

Add the smallest durable PostgreSQL schema needed for workspace state, activity,
and chat-to-workspace lineage.

## Implementation

- Added `ae_workspaces` for owner-scoped workspace metadata, runtime defaults,
  chat document identity, trace/request lineage, and activity summary counters.
- Added `ae_workspace_activities` for bounded metadata-only workspace events.
- Added nullable `ae_chat_interactions.workspace_id` with `ON DELETE SET NULL`
  so existing service interactions remain compatible during rollout.
- Added short owner/time, activity/time, and chat workspace/owner/time indexes;
  every new identifier remains below PostgreSQL's 63-byte limit.
- Excluded raw prompt/output, source bytes, credentials, and provider secrets.

The migration uses the canonical versioned SQL plus `schema_migrations` history.
No runtime route writes are enabled in this Slice.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_workspace_schema_contract.py \
  --test tests/test_database_schema_foundation.py \
  --coverage-target scripts/smoke/run_ae_workspace_schema_contract.py \
  --smoke scripts/smoke/run_ae_workspace_schema_contract.py
```

Observed evidence:

- Focused schema and migration regression: `55 passed`.
- Slice Gate: `1957 passed` with one known warning.
- Repository statement/branch coverage: `97.80%`/`95.48%`.
- Schema runner statement/branch coverage: `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Schema contract: checks `10/10`, two new tables, maximum new identifier
  length 25 bytes; migration dry-run planned all 23 AE migrations.
