# Slice 0364: AG Remediation Execution Dispatch API

## Scope

Expose the AG remediation execution dispatch facade as a protected service API.
The route lets AG operators or automation dispatch an existing remediation task
to CX execution while preserving the AG task transition planner from Slice 0362.

This slice does not add database schema, PostgreSQL smoke evidence, or live
provider calls. The route supports injected CX clients for regression and keeps
PostgreSQL evidence deferred to Slice 0365.

## Implemented

- Added `register_generation_remediation_execution_routes(...)`.
- Added:
  - `POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}/execute`.
- Registered the route in `nex-ag/main.py` using the same remediation task
  store as the create/list/get/patch task API.
- Request body supports safe optional controls:
  - `requested_at`;
  - `planned_at`;
  - `idempotency_key`.
- Route responses use `ag_generation_remediation_execution_dispatch.v1`.
- Auth failures, task-not-found, client dependency failures, and invalid
  dispatch state are returned through the standard problem response shape.
- Updated `contracts/openapi/nex-ag.openapi.yaml` with route and component
  schemas.
- Added regression coverage for route success, auth protection, not-found
  collapse, client failure mapping, static OpenAPI contract, and the dispatch
  service branches.

## Refactoring Checkpoint

```text
external_api_changed=true
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
dispatch_route=POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}/execute
next_slice=0365_ag_remediation_execution_dispatch_postgresql_smoke
```

## Evidence

Targeted regression and coverage:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_execution.py -q --cov=nex_ag.generation_remediation_execution --cov-report=term-missing --cov-report=json:/tmp/ag_generation_remediation_execution_0364_cov.json
33 passed, 1 warning in 1.20s
nex_ag.generation_remediation_execution statement_coverage=100% branch_coverage=100%
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
```
