# Slice 1020: AE Workspace Chat PostgreSQL Smoke

## Goal

Prove that the S102 workspace/chat lifecycle runs against the actual
`nex_ae_test` database rather than an in-memory or SQLite substitute.

## Guardrails

- Execution requires `NEX_AE_WORKSPACE_CHAT_POSTGRES_SMOKE=1`.
- The URL is accepted only for `nex_ae_user@nex_ae_test` and is redacted in
  evidence.
- The canonical versioned SQL migration runner is executed before domain work.
- CX generation uses a deterministic mock; this Slice verifies AE persistence,
  not remote model behavior.
- Every synthetic workspace, activity, chat, and operational-event row is
  deleted and a zero-row cleanup query is required for success.

## Verified Flow

1. Apply or confirm all `23` AE migrations through
   `1014_ae_workspace_activity_persistence`.
2. Insert one owner-scoped workspace and its initial activity.
3. Call the protected chat API and persist `PENDING` then `COMPLETED` state.
4. Recreate repository instances and read one workspace, three ordered
   activities, and one workspace-linked chat record.
5. Confirm a different owner receives `404` and cannot read the row directly.
6. Retry the same interaction and verify one provider call, one chat row, three
   activities, and two metadata-only operational events.
7. Delete all scoped rows and verify no synthetic row remains.

## Verification

```bash
NEX_AE_WORKSPACE_CHAT_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<test database URL>' \
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_workspace_chat_postgres_smoke.py \
  --test tests/test_nex_ae_workspace_persistence.py \
  --test tests/test_nex_ae_chat.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_persistence.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py \
  --smoke scripts/smoke/run_ae_workspace_chat_postgres_smoke.py
```

## Observed Evidence

- Actual target: `nex_ae_user@nex_ae_test`; execution state `EXECUTED`.
- Migrations: `23`, latest `1014_ae_workspace_activity_persistence`.
- Domain checks: `13/13` passed.
- Scoped rows before cleanup: workspace/activity/chat/event `1/3/1/2`.
- Cleanup remaining rows: `0`.
- Slice Gate: `1980 passed`; statement coverage `97.75%`, branch coverage
  `95.56%`.
- Target coverage: workspace repository statement/branch `100%`/`100%`; chat
  runtime statement `97.62%`, branch `98.78%`.
