# Slice 0119: AG Worker Observability Smoke Evidence

## Scope

Slice 0119 extends the mock-first AG operations dashboard smoke so worker
observability is part of the default evidence pack.

The smoke now seeds:

- one running CX processing job
- one matching BUSY `worker_heartbeat.v1`
- one matching `cx.worker.lifecycle.busy` operational event

## Covered Endpoints

The smoke adds coverage for:

```text
GET /admin/v1/operations/workers
GET /admin/v1/operations/workers/{service_id}/{worker_id}
```

It validates the worker runtime projection, the worker detail projection, active
job correlation, lifecycle event correlation, and redaction preservation.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

Expected summary:

```text
ag_operations_dashboard_smoke=pass endpoints=15 jobs=2 workers=1 events=1 logs=1 issues=3
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
