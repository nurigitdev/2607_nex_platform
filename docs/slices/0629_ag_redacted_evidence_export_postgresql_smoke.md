# Slice 0629: AG Redacted Evidence Export PostgreSQL Smoke

Slice 0629 adds protected PostgreSQL smoke evidence for the AG-owned redacted
evidence export route and persistence boundary.

## Scope

- Runs `nex-ag` migrations against `NEX_AG_TEST_DATABASE_URL`.
- Drives protected `POST /admin/v1/operator-review/evidence-exports` with an
  admin user-token and `Idempotency-Key`.
- Verifies idempotency replay through the same protected route.
- Reads list/detail routes through the same app boundary.
- Checks the real `ag_ev_exports` row directly in PostgreSQL for table
  presence, JSONB column types, idempotency hash metadata, manifest redaction
  flags, evidence hash shape, and evidence item count.
- Cleans up the inserted smoke row.

## Guardrail

The smoke is disabled by default and only runs when:

```bash
NEX_AG_REDACTED_EVIDENCE_EXPORT_POSTGRES_SMOKE=1
```

Evidence redaction rejects raw database URLs, raw evidence body text, and raw
idempotency keys.

## Verified Evidence

On 2026-09-10, the smoke was executed against the real `nex_ag_test` database:

```text
ag_redacted_evidence_export_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL export_id=99e3ac4b-910a-59b2-8bb7-ee0f9a7a8e70 row_count=1 deleted_rows=1
```

## Command

```bash
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
NEX_AG_REDACTED_EVIDENCE_EXPORT_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py --summary
```
