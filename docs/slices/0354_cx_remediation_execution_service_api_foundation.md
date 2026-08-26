# Slice 0354: CX Remediation Execution Service API Foundation

## Scope

Implement the first CX runtime API boundary for remediation execution requests.
This slice accepts the Slice 0352 request contract, verifies the parent
generation boundary, and records an `ACCEPTED` remediation execution result in
memory.

This slice does not run MO generation, create a child generation record, add a
database migration, perform PostgreSQL smoke testing, or call remote providers.

## Implemented

- Added `nex_cx.remediation_execution`.
- Added `POST /api/v1/generations/{cx_generation_id}/remediation-executions`.
- Added parent generation existence checks against the CX generation store.
- Added path/body parent mismatch handling.
- Added CX remediation execution request validation for:
  - `cx_remediation_execution_request.v1`;
  - CX-executable actions only;
  - canonical `action_type -> lineage_type` mapping;
  - `parent_generation_mutation_allowed=false`;
  - `provider_boundary=cx_to_mo_service_api_only`;
  - `raw_evidence_stored=false`;
  - raw/provider/credential/storage redaction.
- Added in-memory `RemediationExecutionStore` and route-level persistence of
  `cx_remediation_execution_result.v1` with `execution_status=ACCEPTED`.
- Registered the route in the CX service app using the same
  `DEFAULT_GENERATION_STORE` as the generation routes.

## Refactoring Checkpoint

```text
external_api_changed=true
database_schema_changed=false
remote_provider_required=false
next_slice=0355_cx_repair_attempt_lineage_persistence_foundation
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py -q
6 passed, 1 warning in 0.43s

./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py -q --cov=nex_cx.remediation_execution --cov-report=json:/tmp/cx_remediation_execution_cov.json --cov-report=term-missing
6 passed, 1 warning in 1.02s
nex_cx.remediation_execution statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2447 passed, 1 warning in 70.08s
statement_coverage=98.53% threshold=95.00%
branch_coverage=95.78% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
