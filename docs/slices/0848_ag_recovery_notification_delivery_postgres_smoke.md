# Slice 0848: AG recovery notification delivery PostgreSQL smoke evidence

## Objective

Prove the S85 delivery persistence and targeted MOCK execution path against the
actual `nex_ag_test` PostgreSQL database.

## Smoke Flow

The opt-in smoke runner:

1. runs current `nex-ag` migrations;
2. verifies the PostgreSQL backend and exact `nex_ag_test` database;
3. persists one owned operator review case and escalation;
4. persists one S85 delivery in the existing `ag_op_esc_dispatches` outbox;
5. directly observes the `PENDING` row and S85 delivery metadata marker;
6. runs the confirmed exact-ID `mock_first_only` execution adapter;
7. directly observes `SUCCEEDED`, attempt count, and safe execution metadata;
8. deletes only the smoke-owned dispatch, escalation, and case rows;
9. confirms no owned rows remain.

The runner is protected by
`NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_POSTGRES_SMOKE=1` and reads the URL from
`NEX_AG_TEST_DATABASE_URL`. It is registered in the quality gate and remains
skipped unless explicitly enabled.

## Guardrails

- The smoke requires the database name to be exactly `nex_ag_test`.
- It uses the existing `ag_op_cases`, `ag_op_escalations`, and
  `ag_op_esc_dispatches` tables; no migration or table was added.
- Execution is bounded to one exact dispatch ID and uses no external network.
- Raw idempotency values, provider tokens, and database URLs are rejected from
  evidence and checked against persisted JSON fields.
- Cleanup is idempotent and runs after success or failure.

## Evidence

```bash
NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_delivery_postgres_smoke.py \
  --summary
```

Observed result:

```text
ag_recovery_notification_delivery_postgres_smoke=pass database=nex_ag_test backend=postgresql dispatches=1 succeeded=1 metadata=1 cleaned=True
```

A direct post-cleanup PostgreSQL query confirmed all three tables exist and
the count of S85 smoke-owned dispatch rows is `0`.

- Smoke runner unit tests: `13 passed`.
- Smoke runner statement/branch coverage: `100% / 100%`.
- Full regression: `5668 passed, 1 warning`.
- Statement coverage: `70966 / 71849` (`98.771033695667%`).
- Branch coverage: `16689 / 17340` (`96.245674740484%`).

The warning is the existing Starlette `TestClient` deprecation warning.
