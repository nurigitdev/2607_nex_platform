# Slice 0113: AG Worker Runtime Projection

## Scope

Slice 0113 exposes service worker liveness through AG operations:

```text
GET /admin/v1/operations/workers
```

The projection reads `WorkerHeartbeatStore` sources, applies service/type/status
filters, supports the standard operations time window and pagination controls,
marks stale heartbeats, and reports per-service worker source status.

## Source Registry

`OperationsSource` now carries `worker_heartbeat_store` beside job and event
sources. PostgreSQL operations source mode wraps the SQLAlchemy heartbeat store
with `ReadOnlyWorkerHeartbeatStore`, preserving the AG read-only boundary.

Source readiness now reports the `workers` capability and the concrete heartbeat
store class.

## Contract

The AG operations contract family now includes:

```text
ag_worker_runtime_projection.v1
```

New fixtures:

- `contracts/examples/operations/ag_worker_runtime_projection.mock_success.json`
- `contracts/tests/negative/operations/ag_worker_runtime_projection.missing_workers.json`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
