# Slice 0838: AG recovery notification PostgreSQL smoke evidence

## Objective

Prove that the protected recovery notification preview reads persisted
acknowledgement state from the actual `nex_ag_test` PostgreSQL database.

## Protected Flow

The opt-in smoke:

1. applies the current NeX-AG test-profile migrations;
2. writes one uniquely owned `SUPPRESSED` row to `ag_op_review_ack_state`;
3. verifies the selected backend and database with direct SQL;
4. calls the protected preview route with the smoke worker identifier;
5. confirms the persisted suppression produces a `SUPPRESSED` notification;
6. proves that no provider was invoked and no dispatch or operational event was
   persisted for the smoke trace;
7. verifies that the source row was not mutated by the preview;
8. deletes the owned row and confirms that zero owned rows remain.

The runner allocates its row identifier before execution so cleanup also runs
when a failure occurs after persistence.

## Command

```bash
NEX_AG_RECOVERY_NOTIFICATION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://.../nex_ag_test' \
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_postgres_smoke.py --summary
```

A skipped result is not accepted as live evidence.

## Verification

Focused result: `14 passed`, `1 warning`; smoke runner statement and branch
coverage are both `100%`.

Actual PostgreSQL result:

```text
ag_recovery_notification_postgres_smoke=pass database=nex_ag_test backend=postgresql plan=SUPPRESSED dispatches=0 events=0 cleaned=1
```

The result was not skipped. Current migrations ran, the protected route read a
persisted suppression, no provider/dispatch/event side effect occurred, and the
owned state row was removed.

Full regression result: `5566 passed`, `1 warning`.

- Statement coverage: `70341 / 71224` (`98.760249354150%`).
- Branch coverage: `16563 / 17214` (`96.218194492855%`).

The warning is the existing Starlette `TestClient` deprecation warning.
