# Slice 1012: AE Durable Workspace and Chat Boundary Audit

## Goal

Freeze the S102 boundary before changing workspace or chat runtime behavior.

## Findings

- Workspace state and activity remain process-local and disappear on restart.
- Chat interactions already have a PostgreSQL adapter, but they are not linked
  to a durable workspace record.
- Workspace and chat routes still use the legacy service-only authorization
  helper, while the shared facade helper already supports OA browser claims.
- Chat final records are durable, but workspace-bound admission and activity
  orchestration are not yet one owner-checked lifecycle.

## Frozen Decisions

- Add only `ae_workspaces` and `ae_workspace_activities`; extend the existing
  `ae_chat_interactions` table with a nullable `workspace_id` for legacy service
  compatibility.
- Browser owner scope comes only from a validated OA claim. Service calls keep
  an explicit owner scope. Cross-owner reads remain indistinguishable from
  missing records.
- PostgreSQL stores metadata, hashes, summaries, and bounded previews only; it
  does not gain a raw private-message body column.
- Reuse the current versioned SQL plus `schema_migrations` runner and the shared
  AE facade authentication boundary.
- Remote model providers are not required for S102. Actual `nex_ae_test`
  evidence is required in Slice 1020.

## Slice Plan

1. `1012`: boundary audit.
2. `1013`: shared owner-scope contract.
3. `1014`: workspace/activity schema and chat workspace link.
4. `1015`: SQLAlchemy workspace repository.
5. `1016`: owner-scoped workspace API and Checkpoint Gate.
6. `1017`: owner-scoped chat repository and API.
7. `1018`: durable workspace-bound chat orchestration.
8. `1019`: contract, OpenAPI, privacy, and observability hardening.
9. `1020`: actual PostgreSQL integration smoke.
10. `1021`: S102 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_durable_workspace_chat_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_durable_workspace_chat_boundary_audit.py \
  --smoke scripts/smoke/run_ae_durable_workspace_chat_boundary_audit.py
```

The audit performs no database mutation or provider call.

## Observed Evidence

- Slice Gate: `1921 passed` with one known warning.
- Repository statement coverage: `97.79%`.
- Repository branch coverage: `95.47%`.
- Boundary runner statement/branch coverage: `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Audit result: seven foundations, eight planned gaps, eight open gaps, zero
  issues, next Slice `1013`.
