# Slice 0980: CX Worker Operations PostgreSQL Smoke

## Goal

Prove the S98 worker concurrency and recovery controls against the actual
`nex_cx_test` PostgreSQL database rather than an SQLite approximation.

## Protected Evidence

- Runs every current NeX-CX migration before executing the write probe.
- Refuses mutation unless the target is `nex_cx_user@nex_cx_test` and no
  unrelated `RUNNING` service job exists.
- Starts six concurrent PostgreSQL claims and verifies six unique job and lock
  owners through `FOR UPDATE SKIP LOCKED` behavior.
- Verifies lease renewal compare-and-swap and rejection of a stale renewal.
- Preserves a renewed lease and a fresh-heartbeat worker while reconciling four
  expired leases into three bounded retries and one dead letter.
- Exercises protected readiness, reconciliation, cancellation, and dead-letter
  API routes with persisted metadata-only operational events.
- Deletes all probe jobs, heartbeat rows, and events, then verifies zero
  residue.
- Does not require a DGX provider.

## Execution

```bash
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
NEX_CX_WORKER_OPERATIONS_POSTGRES_SMOKE=1 \
NEX_CX_WORKER_OPERATIONS_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python \
  scripts/smoke/run_cx_worker_operations_postgres_smoke.py --summary
```

The unredacted local password is supplied only through the process environment
and is never written to evidence or committed files.

## Observed Result

- target: `nex_cx_user@nex_cx_test`
- migration: all `21` planned CX migrations recorded; no pending migration
- concurrent claim: `6/6` jobs with `6` distinct lock owners
- restart reconciliation: `4` expired leases applied as `3` bounded retries
  and `1` dead letter
- protected states retained: `2` running jobs, one by renewed lease and one by
  fresh heartbeat
- cancellation: `1` queued probe persisted as `CANCELLED`
- operational events: cancellation and reconciliation events persisted
- cleanup: `residue=0`
- Slice Gate: `2029 passed`
- statement coverage: `98.95%`
- branch coverage: `97.96%`
- smoke module: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents
