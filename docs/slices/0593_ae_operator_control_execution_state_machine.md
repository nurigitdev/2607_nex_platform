# Slice 0593: AE operator-control execution state machine

## Scope

Add the AE-owned operator-control execution state machine and idempotency
contract before wiring routes or invoking any supervisor adapter.

## Decision

- Execution state consumes the validated Slice 0592 execution request.
- READY facade requests in `fake_dry_run_supervisor_persistent_dispatch` mode
  become `ADMITTED` states with bounded next statuses: `EXECUTING` or
  `BLOCKED`.
- `contract_only`, BLOCKED facade, and NOOP facade requests become terminal
  metadata-only states.
- Existing execution evidence is handled through idempotency:
  - same request hash returns a `REPLAYED` terminal state and blocks duplicate
    dispatch;
  - mismatched prior key/hash returns a `CONFLICT` terminal state.
- State transitions are explicit metadata contracts. Slice 0593 allows only
  `ADMITTED -> EXECUTING` and `ADMITTED -> BLOCKED`; later S60 slices can add
  persisted dispatch evidence and terminal execution snapshots.

## Implementation

- Added
  `ae_artifact_retention_scheduler_daemon_operator_control_execution_state.v1`.
- Added
  `ae_artifact_retention_scheduler_daemon_operator_control_execution_state_transition.v1`.
- Added builders, validators, summaries, and summary-line helpers for state and
  transition evidence in the AE daemon contract module.
- Added regression coverage for admitted, blocked, noop, replayed, conflict,
  allowed transition, rejected transition, guardrail, metadata, source-scope,
  idempotency, and deterministic-id validation edges.

## Guardrails

- Slice 0593 does not add a route.
- Slice 0593 does not invoke the supervisor adapter.
- Slice 0593 does not persist supervisor results/events.
- Slice 0593 does not write PostgreSQL rows, enqueue jobs, run workers, start
  subprocesses, stop subprocesses, or enable physical deletion.
- Database URLs, service tokens, local storage paths, raw artifact payloads, raw
  execution payloads, and raw supervised process snapshots remain excluded.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_contract.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0594 should add the protected AE API route wiring for this
  metadata-only execution state machine without enabling real supervisor
  dispatch.
