# Slice 0352: CX Remediation Execution Contract/Schema Foundation

## Scope

Add the first CX remediation execution contracts after the S36 boundary audit.
This slice is contract-only: no runtime endpoint implementation, database
migration, PostgreSQL smoke, or remote provider call is introduced here.

## Implemented

- Added `cx_remediation_execution_request.v1`.
- Added `cx_remediation_execution_result.v1`.
- Registered positive examples for citation repair request/result handoff.
- Registered negative examples that reject raw prompt and provider endpoint
  leaks.
- Added the future CX OpenAPI route shape:
  `POST /api/v1/generations/{cx_generation_id}/remediation-executions`.
- Added contract regression coverage that checks:
  - CX only accepts `retry_generation`, `retrieval_repair`, and
    `citation_repair`;
  - parent generation mutation is explicitly forbidden;
  - CX calls MO service APIs only, not provider endpoints;
  - result refs are `source_service=nex-cx`, `ref_type=repair_execution`, and
    `relation=result_of`;
  - raw prompt/output/provider detail flags stay false.

## Boundary Notes

- AG remains responsible for remediation orchestration and operator workflow.
- CX receives a raw-safe execution request and creates a child repair execution
  result; it does not mutate the parent generation record.
- Raw prompts, raw generation output, source document text, feedback comments,
  operator notes, provider endpoints, credentials, model paths, and storage
  paths are excluded by schema property-name guards and explicit redaction
  fields.

## Refactoring Checkpoint

```text
external_api_changed=contract_only
database_schema_changed=false
remote_provider_required=false
next_slice=0353_ag_to_cx_remediation_handoff_client_foundation
```

## Evidence

Targeted contract regression:

```text
./.venv/bin/pytest tests/test_contract_validation.py::test_nex_cx_remediation_execution_contracts_preserve_cx_boundary -q
1 passed in 0.20s

./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2432 passed, 1 warning in 67.12s
statement_coverage=98.52% threshold=95.00%
branch_coverage=95.72% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
