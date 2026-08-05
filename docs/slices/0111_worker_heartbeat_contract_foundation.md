# Slice 0111: Worker Heartbeat Contract Foundation

## Scope

Slice 0111 adds a common worker heartbeat contract for service-owned workers.
This is the mock-first runtime signal that later AG projections can use to show
worker liveness, active job ownership, and stale heartbeat candidates.

## Runtime Contract

The shared runtime exposes:

- `build_worker_heartbeat()`
- `validate_worker_heartbeat()`
- `worker_heartbeat_is_stale()`
- `summarize_worker_heartbeats()`

The contract version is:

```text
worker_heartbeat.v1
```

Supported statuses are `STARTING`, `IDLE`, `BUSY`, `STOPPING`, `STOPPED`, and
`ERROR`. A `BUSY` heartbeat requires `active_job_id` so AG can later reconcile
running jobs with fresh worker ownership.

## Contract Fixtures

New fixtures:

- `contracts/schemas/common/worker_heartbeat.v1.schema.json`
- `contracts/examples/common/worker_heartbeat.busy.json`
- `contracts/tests/negative/common/worker_heartbeat.bad_status.json`

## Persistence

Slice 0111 is intentionally contract-only. Database-backed heartbeat storage is
reserved for the next slice so the API shape can be tested independently before
DDL and SQLAlchemy adapters are introduced.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_runtime_worker_heartbeats.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
