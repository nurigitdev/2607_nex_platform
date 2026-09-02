# Slice 0526: AG-to-AE scheduler daemon PostgreSQL smoke evidence

## Scope

- Add protected PostgreSQL smoke evidence for the AG scheduler-daemon operations
  surface introduced in S53.
- Drive AG's protected daemon config and manual tick-once routes while AG calls
  AE's daemon config/control routes through the AG client boundary.
- Prove AE remains the owner of scheduler leases, JobQueue enqueue/execution,
  artifact retention history, and artifact persistence effects.

## Runtime Path

The smoke is opt-in:

```bash
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://.../nex_ae_test \
./.venv/bin/python \
  scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py \
  --summary
```

When enabled, the smoke:

- runs the current `nex-ae-api` migrations against the configured test database;
- seeds three logically purged AE artifacts through AE API routes;
- queries AG's daemon operations route;
- dispatches AG's guarded `manual_tick_once` route with worker execution
  confirmation;
- validates AE route calls, released scheduler lease, succeeded JobQueue row,
  written retention history row, retained database rows, and retained storage
  files;
- cleans all smoke rows before returning evidence.

## Evidence Contract

The returned evidence is metadata-only and redaction guarded:

- the raw database URL, database password, storage root, `/data/nex-platform`,
  `storage_ref`, `content_base64`, and `rendered_payloads` must not appear;
- AG evidence records route status for both AG routes and AE source routes;
- AE evidence records daemon dispatch and tick-once status without exposing
  artifact payloads or local storage internals.

The default quality gate invokes the script without enabling the smoke env var,
so it reports `SKIPPED` unless an operator explicitly opts into the PostgreSQL
write smoke.

## Regression

- `tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py`
  exercises skip/failure paths, redaction, check failure reporting, CLI summary,
  and a SQLite-backed full harness for the AG-to-AE route flow.
- `scripts/quality/run_quality_gate.sh` now includes the optional smoke runner.
