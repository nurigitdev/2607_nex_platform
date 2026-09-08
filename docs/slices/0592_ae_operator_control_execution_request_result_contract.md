# Slice 0592: AE operator-control execution request/result contract

## Scope

Add the AE-owned execution request/result contract for supervised scheduler
daemon operator control.

## Decision

- Execution requests must consume the validated S59 operator-control facade.
- The request contract carries only safe metadata: facade ids, action, status,
  operator subject, idempotency key, reason hash, command count, and supervisor
  actions.
- The first executable mode is reserved as
  `fake_dry_run_supervisor_persistent_dispatch`, but this Slice does not invoke
  the supervisor adapter yet.
- `contract_only` remains the default mode and returns BLOCKED execution
  evidence with `execution_contract_only`.
- BLOCKED/NOOP facade decisions are preserved without dispatch.
- Restart-ready requests preserve the stop-then-start supervisor command
  sequence from the S59 preview.

## Implementation

- Added
  `ae_artifact_retention_scheduler_daemon_operator_control_execution_request.v1`.
- Added
  `ae_artifact_retention_scheduler_daemon_operator_control_execution_result.v1`.
- Added builder, validator, summary, and summary-line helpers in the AE daemon
  contract module.
- Added regression coverage for ready, contract-only, fake-ready, blocked,
  noop, restart stop-then-start, source-scope, guardrail, metadata, and
  dispatch-result validation edges.

## Guardrails

- Slice 0592 does not add a route.
- Slice 0592 does not invoke a supervisor adapter.
- Slice 0592 does not persist supervisor results/events.
- Slice 0592 does not write PostgreSQL rows, enqueue jobs, run workers, start
  subprocesses, stop subprocesses, or enable physical deletion.
- Database URLs, service tokens, local storage paths, raw artifact payloads, raw
  execution payloads, and raw supervised process snapshots remain excluded.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_contract.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_contract.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
```

## Next

- Slice 0593 should add the execution state machine and idempotency/admission
  transitions before any route or real supervisor dispatch is enabled.
