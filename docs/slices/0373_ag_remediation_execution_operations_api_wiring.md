# Slice 0373: AG Remediation Execution Operations API Wiring

## Scope

Expose the Slice 0372 remediation execution operations projection through a
protected AG operations API.

This slice does not change database schema, run PostgreSQL smoke evidence, add
dashboard issue candidates, or call remote providers. It wires the route,
runtime store selection, service bootstrap, and static OpenAPI contract so
operators can query the read-only projection through AG.

## Implemented

- Added `GET /admin/v1/operations/remediation-executions`.
- Added service-token authorization with `aud=nex-ag`.
- Added query filters:
  - `cx_generation_id`;
  - `remediation_action_id`;
  - `action_status`;
  - `execution_status`;
  - `trace_id`;
  - `request_id`;
  - `since`, `until`, `sort`, `cursor`, and `limit`.
- Added validation for AG remediation task statuses and CX remediation
  execution statuses.
- Added environment-backed execution operation store construction for
  `nex-cx` using the existing AG operations source mode/profile conventions.
- Wired the route into `services/nex-ag/nex_ag/main.py`.
- Updated `contracts/openapi/nex-ag.openapi.yaml` with the route, operationId,
  query parameters, and projection schema enum.

## Refactoring Checkpoint

```text
external_api_changed=true
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
next_slice=0374_ag_remediation_execution_dashboard_issue_candidate_integration
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_remediation_execution_operations.py tests/test_contract_validation.py::test_nex_ag_openapi_includes_worker_and_service_log_contracts -q --cov=nex_ag.remediation_execution_operations --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_execution_operations_0373_cov.json
20 passed, 1 warning in 1.51s
services/nex-ag/nex_ag/remediation_execution_operations.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2656 passed, 1 warning in 87.81s
statement_coverage=98.62% threshold=95.00%
branch_coverage=96.00% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
