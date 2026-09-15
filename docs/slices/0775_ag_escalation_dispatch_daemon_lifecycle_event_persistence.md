# Slice 0775: AG dispatch daemon lifecycle event persistence

## Intent

Persist safe lifecycle evidence for AG dispatch daemon process execution through
the existing shared operational event store.

## Implementation

- Added `build_dispatch_execution_daemon_lifecycle_event_details`.
- Added `emit_dispatch_execution_daemon_lifecycle_event`.
- Lifecycle details include process run id, worker id, process/runtime status,
  loop status, stop reason, safe counters, source table, and liveness source.
- Added optional lifecycle emitter wiring to the executable CLI facade.
- When an emitter is supplied, `run_once` emits started and completed or blocked
  lifecycle events through `service_operational_events`.
- No process-specific database table is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `64 passed in 1.26s`.

Coverage for `nex_ag.operator_review_dispatch_execution`: statement `100%`,
branch `100%`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_daemon_cli.py -q --cov=nex_ag.operator_review_dispatch_daemon --cov-branch --cov-report=term-missing
```

Result: `8 passed in 0.94s`.

Coverage for `nex_ag.operator_review_dispatch_daemon`: statement `100%`,
branch `100%`.
