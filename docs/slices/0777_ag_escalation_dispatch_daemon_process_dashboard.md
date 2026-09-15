# Slice 0777: AG dispatch daemon process operations dashboard

## Intent

Surface AG dispatch daemon process readiness, runtime metadata, and protected
process-control entrypoints in the operations dashboard without introducing a
new persistence table or raw provider data exposure.

## Implementation

- Added `daemon_process` to the `operator_review_escalation_dispatches`
  dashboard section.
- The dashboard subsection exposes:
  - process status and runtime state status
  - enabled/dry-run flags
  - loop mode, cycle limit, and interval seconds
  - effective provider mode
  - process-control route path
  - CLI entrypoint
  - source/liveness references for `service_operational_events` and
    `service_worker_heartbeats`
- Extended the AG operations projection JSON Schema and dashboard example.
- Added OpenAPI parity coverage for
  `POST /admin/v1/operator-review/dispatch-daemon/process-controls`.
- No new database table is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term
```

Result: `193 passed, 1 warning in 10.70s`.

Coverage for `nex_ag.operations`: statement/branch aggregate `98%`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 2.99s`.
