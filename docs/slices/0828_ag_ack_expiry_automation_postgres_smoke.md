# Slice 0828: AG acknowledgement expiry automation PostgreSQL smoke

## Objective

Prove the S83 executable automation path against the actual `nex_ag_test`
PostgreSQL database rather than an in-memory or SQLite substitute.

## Protected flow

The opt-in smoke:

1. runs all NeX-AG test-profile migrations;
2. writes one uniquely owned, earliest-expiring acknowledgement state;
3. verifies that PostgreSQL selects it as the batch-limit-one candidate;
4. invokes the executable CLI `plan` path;
5. invokes confirmed `run-once` through the same CLI entry point;
6. directly selects the persisted `EXPIRED` state and two lifecycle events;
7. deletes only the smoke-owned state and events and verifies zero remain.

No new table is introduced. Database URLs, comments, and idempotency keys are
excluded from evidence.

## Command

```bash
NEX_AG_ACK_EXPIRY_AUTOMATION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://.../nex_ag_test' \
./.venv/bin/python \
  scripts/smoke/run_ag_ack_expiry_automation_postgres_smoke.py --summary
```

The command must report `pass`; a skipped result is not accepted as live
evidence.

## Verification

Unit result: `12 passed`; smoke script statement/branch coverage: `100% / 100%`.

Actual PostgreSQL result:

```text
ag_ack_expiry_automation_postgres_smoke=pass database=nex_ag_test backend=postgresql applied=1 events=2 cleaned=1
```

The result was not skipped. It applied current migrations, selected and expired
one owned row, persisted two lifecycle events, and verified cleanup.

Full regression result: `5482 passed, 1 warning`.

- Statement coverage: `69754 / 70637 = 98.749946911675%`.
- Branch coverage: `16479 / 17130 = 96.199649737303%`.
