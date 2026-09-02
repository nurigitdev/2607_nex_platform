# Slice 0515: AE Scheduler Tick-Once PostgreSQL Smoke

## Scope

Add protected PostgreSQL smoke evidence for the Slice 0514 manual scheduler
tick-once runner.

## Smoke

`scripts/smoke/run_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py`
is disabled by default and runs only when:

```text
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_POSTGRES_SMOKE=1
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_POSTGRES_SMOKE_PROFILE=test
NEX_AE_TEST_DATABASE_URL=<test database URL>
```

The smoke runner:

- applies current `nex-ae-api` migrations before execution;
- creates rendered, logically deleted artifacts through AE API routes;
- runs the SQLAlchemy-backed scheduler tick-once path against `nex_ae_test`;
- verifies a released scheduler lease row;
- verifies a completed scheduled retention job row;
- verifies one dry-run retention execution history row;
- verifies artifact and storage rows are retained;
- cleans up artifacts, handoffs, jobs, history rows, and the smoke lease row.

## Guardrails

- The smoke is restricted to the `test` database profile.
- Evidence redacts database URLs, database passwords, local storage roots, raw
  rendered payloads, source content, and storage refs.
- Scheduler daemon auto-start and continuous loop execution remain disabled.
- Physical delete automation remains disabled.

## Evidence

Regression tests cover:

- disabled-by-default skip behavior;
- non-test profile rejection;
- missing DB URL and migration failure reporting;
- SQLite harness pass path for the script shape;
- failed-check reporting;
- redaction and helper edge cases;
- quality gate registration.

Live evidence should be captured with the protected smoke command in a test DB
environment.
