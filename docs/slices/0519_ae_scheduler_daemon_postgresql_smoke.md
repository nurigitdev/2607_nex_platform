# Slice 0519: AE Scheduler Daemon PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE scheduler daemon service API
surface introduced in Slice 0518.

## Implementation

- Added `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py`.
- The smoke is skipped by default and only runs when
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1`.
- The smoke refuses non-test profiles before write execution.
- When enabled, it migrates `nex-ae-api`, builds an AE TestClient backed by the
  real service session factory, seeds deleted artifacts through AE APIs, calls
  the daemon config route, verifies blocked daemon start, and dispatches
  `manual_tick_once` through the daemon controls route.
- The route dispatch is verified by reading back PostgreSQL lease, JobQueue,
  retention history, and artifact row observations before cleanup.

## Evidence

Regression harness:

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_postgres_smoke.py -q --cov=scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py --cov-branch --cov-report=term-missing
```

Protected live smoke:

```bash
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL=<test-db-url> \
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py --summary
```

Expected summary:

```text
ae_artifact_retention_scheduler_daemon_postgres_smoke=pass
```

## Guardrails

- The smoke requires the test database URL guard before writing.
- `start_daemon` remains blocked by policy.
- `manual_tick_once` is the only dispatched runtime path.
- Evidence redacts database URLs, database passwords, local storage roots, and
  raw artifact payload fields.
