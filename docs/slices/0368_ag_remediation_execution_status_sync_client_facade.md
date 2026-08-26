# Slice 0368: AG Remediation Execution Status Sync Client/Facade

## Scope

Add the AG-side foundation for following up on a remediation execution after it
has been dispatched to CX. AG can now read CX's remediation execution detail
read model and reconcile the CX execution status back into the AG remediation
task state machine.

This slice does not expose a new AG HTTP route, add database schema, run
PostgreSQL smoke evidence, or call live remote providers. The protected API
surface and PostgreSQL evidence are deferred to Slice 0369.

## Implemented

- Extended `HttpCxRemediationExecutionClient` with
  `get_remediation_execution_detail(...)`.
- Added `CxRemediationExecutionStatusClient` as a separate Protocol so tests
  and future route wiring can inject a read-model client without requiring POST
  dispatch behavior.
- Added `cx_remediation_execution_detail.v1` response schema validation on the
  AG client boundary.
- Added
  `sync_generation_remediation_execution_status(...)` in
  `nex_ag.generation_remediation_execution`.
- The sync facade:
  - loads the AG remediation task by `remediation_action_id`;
  - collapses wrong-generation lookups to the same not-found response as
    missing tasks;
  - calls CX detail using the task's `cx_generation_id`;
  - validates the CX detail envelope and embedded
    `cx_remediation_execution_result.v1`;
  - maps CX statuses through the existing AG planner:
    `ACCEPTED/RUNNING -> WAITING_ON_CX`,
    `SUCCEEDED -> COMPLETED`,
    `FAILED -> FAILED`,
    `CANCELLED -> CANCELLED`;
  - keeps same-status sync idempotent with `sync_status=UNCHANGED`;
  - persists only planned AG task updates when a status transition is needed.
- Added regression coverage for HTTP GET request shape, optional trace headers,
  problem/timeout/schema failures, status completion, idempotent no-op sync,
  invalid detail envelopes, client failures, store failures, missing tasks, and
  wrong-generation collapse.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
client_method=HttpCxRemediationExecutionClient.get_remediation_execution_detail
facade=sync_generation_remediation_execution_status
next_slice=0369_ag_remediation_execution_status_sync_api_and_smoke
```

## Evidence

Targeted regression and coverage:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_handoff.py tests/test_nex_ag_generation_remediation_execution.py -q --cov=nex_ag.generation_remediation_handoff --cov=nex_ag.generation_remediation_execution --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_execution_status_sync_0368_cov.json
52 passed, 1 warning in 1.47s
nex_ag.generation_remediation_handoff statement_coverage=100% branch_coverage=100%
nex_ag.generation_remediation_execution statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2599 passed, 1 warning in 70.20s
statement_coverage=98.59% threshold=95.00%
branch_coverage=95.90% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
cx_remediation_execution_read_model_postgres_smoke=skipped reason=NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE
```
