# Slice 0545: AE scheduler daemon bounded-loop PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE scheduler daemon bounded-loop
adapter.

## Implementation

- `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py`
  is opt-in through
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_POSTGRES_SMOKE=1`.
- The smoke requires the `test` profile, resolves `NEX_AE_TEST_DATABASE_URL`,
  verifies it is a test database URL, runs AE migrations, seeds deleted artifact
  rows, executes a two-cycle bounded loop, reads PostgreSQL state back, and then
  cleans up the seeded rows.
- The evidence verifies JobQueue rows, retention-history rows, scheduler lease
  state, daemon heartbeat state, route-based daemon runtime observation,
  storage-file retention, and DRY_RUN behavior.

## Guardrails

- Default quality gate behavior is an explicit skip until the smoke is opted in.
- The smoke must use a test database profile.
- Bounded loop work still delegates to one-cycle execution and JobQueue workers.
- Physical delete automation remains disabled; database rows and storage files
  are retained during the smoke and removed only by smoke cleanup.
- Evidence redacts raw database URLs, passwords, local data paths, storage refs,
  and rendered payloads.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py -q
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<test-db-url> ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```
