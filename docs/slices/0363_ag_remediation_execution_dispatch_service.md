# Slice 0363: AG Remediation Execution Dispatch Service

## Scope

Wire the Slice 0362 AG handoff planner into a service-level dispatch function.
The function loads an AG remediation task, submits it to the CX remediation
execution client, applies the planned AG status updates, and saves each update
through the existing remediation task store.

This slice does not expose a route, add database schema, run PostgreSQL smoke,
or call live providers. Route wiring and PostgreSQL evidence are deferred to
the next slices.

## Implemented

- Added `dispatch_generation_remediation_execution(...)`.
- Added `ag_generation_remediation_execution_dispatch.v1`.
- The dispatch service:
  - loads the task by `remediation_action_id`;
  - collapses generation mismatch to the same not-found boundary;
  - calls the injected CX remediation execution client;
  - builds a handoff plan from the CX result;
  - applies and saves sequential AG status updates;
  - returns final task state, result ref, and redaction-safe plan evidence.
- Client and store failures are mapped to
  `GenerationRemediationExecutionError` while preserving retryability for
  dependency failures.
- Added regression coverage for successful `WAITING_ON_CX` and `COMPLETED`
  dispatches, missing tasks, generation mismatch, client failure, store get/save
  failures, and the existing handoff planner branches.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
dispatch_schema=ag_generation_remediation_execution_dispatch.v1
next_slice=0364_ag_remediation_execution_dispatch_api
```

## Evidence

Targeted regression and coverage:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py -q
29 passed in 0.37s

./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py -q --cov=nex_ag.generation_remediation_execution --cov-report=term-missing --cov-report=json:/tmp/ag_generation_remediation_execution_0363_cov.json
29 passed in 0.91s
nex_ag.generation_remediation_execution statement_coverage=100% branch_coverage=100%
```
