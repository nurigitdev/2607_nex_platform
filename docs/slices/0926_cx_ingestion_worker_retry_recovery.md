# Slice 0926: CX ingestion worker retry and recovery

## Goal

Execute admitted CX ingestion jobs through durable checkpoints and recover
retryable or lease-expired work without storing private payloads in worker
state.

## Implementation

- Claims only `cx.document_ingestion` jobs from the shared durable JobQueue.
- Resolves the corresponding `cx_ingest_runs` record by its unique `job_id`
  through an internal worker repository lookup.
- Claims a bounded 120-second run lease, executes the six checkpointed steps,
  and completes the queue job only after the run reaches `SUCCEEDED`.
- Converts retryable step failures into synchronized JobQueue backoff and
  `WAITING_RETRY` run state. Non-retryable or exhausted work becomes terminal.
- Requeues the same failed step after its retry deadline and preserves all
  preceding successful checkpoints.
- Provides explicit expired-lease recovery for a `RUNNING` job/run pair; it
  does not introduce a background loop.
- Returns metadata-only worker results containing IDs, statuses, checkpoint,
  retry time, and safe error code.

No table or migration is added. PostgreSQL execution remains protected until
Slice 0929, and DGX Spark is not required for queue/retry durability.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_worker.py \
  tests/test_nex_cx_ingestion_orchestration_repository.py \
  tests/test_cx_ingestion_worker_retry_recovery_smoke.py
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_worker_retry_recovery_smoke.py --summary
```

Observed on 2026-09-21:

- Focused worker/repository/smoke suite: `27 passed`; worker statement and
  branch coverage: `100%`.
- Related ingestion regression: `199 passed`.
- Deterministic worker smoke: `PASS`, `10/10` checks, queue/run terminal
  `SUCCEEDED`, checkpoint version `7`.
- Full quality gate: `6641 passed`; statement coverage
  `98.83451643759754%`; branch coverage `96.410746522247%`.
- PostgreSQL and DGX Spark were not invoked. Actual test-database worker,
  restart, and owner-isolation evidence is reserved for Slice 0929.
