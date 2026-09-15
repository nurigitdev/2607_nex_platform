# Slice 0773: AG dispatch daemon process metadata contract

## Intent

Define the metadata and runtime-state contract that future executable,
process-control API, dashboard, and PostgreSQL smoke slices can share.

## Implementation

- Added `build_dispatch_execution_daemon_process_metadata`.
- Added `build_dispatch_execution_daemon_process_runtime_state`.
- Metadata includes the daemon worker id, optional process id, entrypoint,
  bounded loop settings, provider mode, source table, lifecycle event source,
  and liveness source.
- Runtime state maps metadata plus optional loop results into safe operator
  statuses: `DISABLED`, `READY`, `DEGRADED`, `STOPPED`, or `UNKNOWN`.
- The contract explicitly reuses `service_operational_events` and
  `service_worker_heartbeats`; no process-specific table is introduced.
- Raw provider payloads, database URLs, tokens, and idempotency keys remain
  excluded from the metadata/state shape.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `60 passed in 1.49s`.

Coverage for `nex_ag.operator_review_dispatch_execution`: statement `100%`,
branch `100%`.
