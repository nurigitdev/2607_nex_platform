# Slice 0625: AG Operator Review Note PostgreSQL Smoke

Slice 0625 adds protected PostgreSQL smoke evidence for the AG-owned operator
review note route and persistence boundary.

## Scope

- Runs `nex-ag` migrations against `NEX_AG_TEST_DATABASE_URL`.
- Drives protected `POST /admin/v1/operator-review/notes` with an admin
  user-token and `Idempotency-Key`.
- Verifies idempotency replay through the same protected route.
- Reads list/detail routes through the same app boundary.
- Checks the real `ag_op_notes` row directly in PostgreSQL for table presence,
  JSONB column types, idempotency hash metadata, and raw idempotency absence.
- Cleans up the inserted smoke row.

## Guardrail

The smoke is disabled by default and only runs when:

```bash
NEX_AG_OPERATOR_REVIEW_NOTE_POSTGRES_SMOKE=1
```

Evidence redaction rejects raw database URLs, raw operator note text, and raw
idempotency keys.

## Verified Evidence

On 2026-09-10, the smoke was executed against the real `nex_ag_test` database:

```text
ag_operator_review_note_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL operator_note_id=90dd199e-1f03-580d-afd3-8722a0a15a8e row_count=1 deleted_rows=1
```

## Command

```bash
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
NEX_AG_OPERATOR_REVIEW_NOTE_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_ag_operator_review_note_postgres_smoke.py --summary
```
