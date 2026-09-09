# Slice 0608: AG worker execution route/dashboard wiring

## Scope

Expose the Slice 0607 AG worker execution projection through a protected AG
admin route for operator dashboard use.

## Decision

- No new database table is introduced in Slice 0608.
- AG does not execute worker logic directly. The AG route delegates to the AE
  worker route through the AE artifact operations client.
- The AG route accepts either `operator_control_execution_state_id` or an
  `operator_control_execution_state` payload with a state id.
- The response is always the redacted AG worker projection, not the raw AE
  worker result.

## Implementation

- Added protected AG route:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-execution-workers`.
- Added request validation for service scope, state identity, and state payload
  shape.
- Wired the route to
  `run_artifact_retention_scheduler_daemon_operator_control_execution_worker`
  on the AE source client.
- Added route tests for seeded worker results, fallback worker results,
  authorization failure, invalid service scope, missing state id, invalid state
  payload, and AE source failures.

## Guardrails

- AG still cannot write AE execution tables.
- AG still cannot enqueue AE JobQueue work.
- AG still cannot start or stop AE subprocesses.
- AG returns no raw worker command, transition-plan, supervisor-result, storage,
  or persistence endpoint payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
```

- Targeted AG regression: `97 passed`.

## Next

- Slice 0609 should add protected AG-to-AE PostgreSQL smoke evidence for this
  route using the AE test database.
