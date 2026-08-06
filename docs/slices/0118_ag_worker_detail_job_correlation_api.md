# Slice 0118: AG Worker Detail Job Correlation API

## Scope

Slice 0118 adds an AG worker detail projection for debugging one worker across
heartbeat, active job, and lifecycle event sources.

New AG endpoint:

```text
GET /admin/v1/operations/workers/{service_id}/{worker_id}
```

The endpoint requires the same AG service-token authorization as the existing
operations APIs.

## Projection

`ag_worker_detail_projection.v1` includes:

- the selected `worker_heartbeat.v1` record with stale evaluation
- `active_job`, resolved from `worker.active_job_id` when present
- `worker_lifecycle_timeline`, matched by worker subject reference or
  `details.worker_id`
- `source_statuses` for worker, job, and event sources

Missing worker records return `ag.worker_not_found`. Unavailable or missing
correlation sources are represented as `DEGRADED` projections so AG can still
show the heartbeat context that is available.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
