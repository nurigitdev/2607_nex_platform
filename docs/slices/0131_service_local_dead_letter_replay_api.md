# Slice 0131: Service-Local Dead-Letter Replay API

## Scope

Slice 0131 adds the service-local internal API that turns a terminal
dead-letter job into a new queued replay job.

Implemented:

- `POST /internal/v1/jobs/{job_id}/replay`
- `build_service_job_replay_response()`
- `controls.can_replay`
- `allowed_actions=[read, replay]` for failed dead-letter jobs
- payload-redacted replay response metadata

## Request

The replay request is intentionally explicit:

```text
replay_job_id=<new job id>
idempotency_key=<new replay idempotency key>
requested_by=<operator id>
reason=<operator reason>
observed_at=<optional replay timestamp>
```

The endpoint calls `plan_dead_letter_replay()` and then explicitly enqueues
`decision.replay_job` through the target service-owned JobQueue adapter.

## Response

The response keeps the existing `service_job_control.v1` envelope:

```text
action=replay
job=<payload-redacted replay job projection>
controls=<controls for the replay job>
replay.source_job=<safe source job summary>
replay.lineage=<job_replay_lineage.v1>
```

The replay response does not expose job payloads or source error detail. Source
job metadata includes the source `error_code` and dead-letter flag only.

## Boundary

This slice adds the target service capability. AG operator-facing dispatch,
audit wiring, and OpenAPI freeze remain separate follow-up slices.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_job_control.py
```

