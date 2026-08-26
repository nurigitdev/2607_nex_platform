# Slice 0362: AG Remediation Execution Handoff State Planner

## Scope

Freeze the AG-side state planner that maps CX remediation execution responses
back onto AG remediation task status updates.

This slice does not add a route, database schema, PostgreSQL smoke, or live
provider call. It is a refactoring checkpoint before wiring an executable AG
task action because the status transition path must stay deterministic and
redaction-safe.

## Implemented

- Added `nex_ag.generation_remediation_execution`.
- Added `ag_generation_remediation_execution_handoff_plan.v1`.
- Planned CX execution statuses into AG remediation task statuses:
  - `ACCEPTED` and `RUNNING` -> `WAITING_ON_CX`;
  - `SUCCEEDED` -> `COMPLETED`;
  - `FAILED` -> `FAILED`;
  - `CANCELLED` -> `CANCELLED`.
- Preserved the existing AG transition policy by using intermediate
  `IN_PROGRESS` updates when needed, for example
  `PROPOSED -> IN_PROGRESS -> WAITING_ON_CX`.
- Built canonical redaction-safe `repair_execution` result refs for AG task
  storage.
- Added an apply helper that turns a plan into sequential AG task records using
  the existing `update_generation_remediation_action_status(...)` function.
- Added regression coverage for success paths, terminal/invalid status
  failures, mismatched CX result ids, redaction guard failures, invalid plan
  shapes, and unreachable transition handling.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
state_planner=ag_generation_remediation_execution_handoff_plan.v1
next_slice=0363_ag_remediation_execution_dispatch_service
```

## Evidence

Targeted regression and coverage:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py -q
23 passed in 0.35s

./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py -q --cov=nex_ag.generation_remediation_execution --cov-report=term-missing --cov-report=json:/tmp/ag_generation_remediation_execution_0362_cov.json
23 passed in 0.90s
nex_ag.generation_remediation_execution statement_coverage=100% branch_coverage=100%
```
