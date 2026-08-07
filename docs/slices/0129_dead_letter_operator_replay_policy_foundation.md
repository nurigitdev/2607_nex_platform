# Slice 0129: Dead-Letter Operator Replay Policy Foundation

## Scope

Slice 0129 adds a shared dead-letter replay planner for service JobQueue
operators.

Implemented:

- `JobReplayPolicy`
- `JobReplayDecision`
- `plan_dead_letter_replay()`
- `REPLAY_ACTION_CREATE_NEW_JOB`
- SQLAlchemy JobQueue payload readback for replay planning

## Policy

Dead-letter replay is modeled as a new queued job, not a mutation of the failed
source job.

The default policy requires:

```text
source.status=FAILED
source.error.dead_lettered=true
requested_by=<non-empty operator id>
reason=<non-empty operator reason, max 240 chars>
```

The replay job preserves source `job_type`, `trace_id`, `request_id`,
`subject_ref`, `links`, `max_attempts`, and payload. It resets
`attempt_count=0`, `status=QUEUED`, and `retryable=true`.

## Lineage

Replay jobs include a `replay_lineage` object with:

```text
lineage_schema_version=job_replay_lineage.v1
source_job_id
source_status
source_attempt_count
source_max_attempts
source_error_code
requested_by
reason
replayed_at
```

The lineage intentionally excludes source error detail and private payload
values. Service-local and AG operator projections must continue redacting job
payloads.

## Boundary

`plan_dead_letter_replay()` only creates a replay decision. The caller must
explicitly enqueue `decision.replay_job` through the target service-owned
JobQueue adapter. AG endpoint wiring and audit emission remain separate
operator workflow concerns.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_jobs.py
```

