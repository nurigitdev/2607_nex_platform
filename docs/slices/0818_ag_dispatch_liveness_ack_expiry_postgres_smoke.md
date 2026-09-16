# Slice 0818: AG dispatch liveness acknowledgement expiry PostgreSQL smoke

## Objective

Prove S82 expiry reconciliation against the real `nex_ag_test` PostgreSQL
database, including migration, indexed candidate selection, CAS mutation,
idempotent rerun, conflict protection, and scoped cleanup.

## Guardrails

- The smoke creates two uniquely identified rows and deletes only those rows.
- SQL candidate selection is executed against `ag_op_review_ack_state`.
- The worker receives only the smoke-owned target row, so unrelated expired
  test data cannot be mutated.
- A renewed second row rejects a stale CAS update and remains `SUPPRESSED`.
- Database URLs are redacted from persisted and console evidence.

## Verification

```bash
NEX_AG_DISPATCH_LIVENESS_ACK_EXPIRY_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://.../nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_dispatch_liveness_ack_expiry_postgres_smoke.py --summary
```

Real PostgreSQL result: `PASS` against `nex_ag_test`.

- Applied migration: `0813_ag_ack_expiry_index`.
- Verified table/index: `ag_op_review_ack_state` /
  `idx_ag_ack_state_expiry`.
- Selected two smoke-owned expiry candidates and applied one reconciliation.
- Verified an idempotent rerun with zero candidates.
- Rejected a stale CAS update and preserved the renewed suppression state.
- Deleted both smoke-owned rows and verified zero remaining rows.

Focused regression result: `26 passed`.

Full regression result: `5398 passed, 1 warning`.

- Statement coverage: `69084 / 69967 = 98.737976474624%`.
- Branch coverage: `16389 / 17040 = 96.179577464789%`.
- New smoke runner statement/branch coverage: `100% / 100%`.
