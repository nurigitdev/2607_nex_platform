# Slice 0114: Worker Stuck Job Issue Candidates

## Scope

Slice 0114 extends AG issue candidate projection with worker heartbeat
reconciliation when worker heartbeat stores are configured.

New rules:

- `stale_worker_heartbeat.v1`
- `active_job_without_fresh_worker.v1`

The rules remain opt-in through configured worker heartbeat sources. Existing
job/event-only issue projections keep their previous behavior.

## Detection

AG marks stale worker heartbeats using the same `stale_after_seconds` threshold
as `GET /admin/v1/operations/workers`.

For active job reconciliation, AG compares RUNNING jobs from dashboard active
jobs against fresh `BUSY` worker heartbeats with the same `service_id` and
`active_job_id`. QUEUED jobs are intentionally excluded because they are
expected to have no worker yet.

## Source Status

When worker sources are configured, issue candidate projection also returns
`worker_source_statuses`. Unavailable worker sources can produce the existing
`operations_source_unavailable.v1` issue candidate with `source_type=workers`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
