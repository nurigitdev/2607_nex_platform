# Slice 0638: AG Operator Review Workbench PostgreSQL Smoke

Slice 0638 adds protected PostgreSQL smoke evidence for the AG operator review
workbench read model, rollup, dashboard section, and issue-candidate
correlation path.

## Scope

- Runs `nex-ag` migrations against `NEX_AG_TEST_DATABASE_URL`.
- Creates one protected operator review note through
  `POST /admin/v1/operator-review/notes`.
- Creates one protected redacted evidence export through
  `POST /admin/v1/operator-review/evidence-exports`.
- Reads `/admin/v1/operator-review/workbench` and
  `/admin/v1/operator-review/workbench/rollups` with target, note-status, and
  export-status filters.
- Reads `/admin/v1/operations/dashboard` and
  `/admin/v1/operations/issue-candidates` to confirm the workbench projection is
  visible through AG operations.
- Verifies the real `ag_op_notes` and `ag_ev_exports` rows directly in
  PostgreSQL for table presence, row counts, JSONB column shape, active high
  note state, and failed export state.
- Cleans up both inserted smoke rows.

## Guardrail

The smoke is disabled by default and only runs when:

```bash
NEX_AG_OPERATOR_REVIEW_WORKBENCH_POSTGRES_SMOKE=1
```

Evidence redaction rejects raw database URLs, raw operator note text, and raw
idempotency keys.

## Verified Evidence

On 2026-09-10, the smoke was executed against the real `nex_ag_test` database:

```text
ag_operator_review_workbench_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL target_id=ag-op-workbench-smoke-target-ffa5b9fe36bd notes=1 exports=1 deleted_notes=1 deleted_exports=1
```

## Command

```bash
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
NEX_AG_OPERATOR_REVIEW_WORKBENCH_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py --summary
```
