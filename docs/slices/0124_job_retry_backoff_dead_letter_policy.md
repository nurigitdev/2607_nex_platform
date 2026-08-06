# Slice 0124: Job Retry, Backoff, and Dead-Letter Policy

## Scope

Slice 0124 adds common retry/backoff/dead-letter semantics to service JobQueue
adapters and connects handler failures in the shared worker runner to that
policy.

Implemented:

- `JobRetryPolicy`
- `JobRetryDecision`
- `build_job_error()`
- `plan_job_retry()`
- `JobQueue.retry_job()`
- In-memory retry scheduling
- SQLAlchemy retry scheduling using existing `available_at` and `error` columns
- worker runner handler-failure retry integration

## Runtime Behavior

Retryable RUNNING jobs are moved back to `QUEUED` with a future `available_at`
timestamp. The next `claim_next_job()` call ignores the job until that timestamp
is reached.

Backoff defaults:

```text
initial_delay_seconds=30
max_delay_seconds=900
backoff_multiplier=2.0
```

The delay is based on the failed attempt count. A first failed attempt waits 30
seconds, then 60 seconds, then 120 seconds, capped by the max delay.

## Dead-Letter Decision

The common job status enum remains unchanged. Exhausted and non-retryable jobs
are represented as:

```text
status=FAILED
retryable=false
error.dead_lettered=true
```

This avoids a DDL/status enum migration while still giving AG and service APIs a
stable dead-letter signal to project later.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_jobs.py tests/test_nex_runtime_worker_runner.py tests/test_nex_cx_processing.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
