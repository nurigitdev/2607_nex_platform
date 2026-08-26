# Slice 0353: AG to CX Remediation Handoff Client Foundation

## Scope

Add the AG-side handoff foundation that converts an AG remediation task record
into the CX remediation execution request contract from Slice 0352.

This slice does not expose a new AG route, implement the CX runtime endpoint,
change a database schema, or call a remote provider. The HTTP client is covered
with deterministic fake responses.

## Implemented

- Added `nex_ag.generation_remediation_handoff`.
- Added `build_cx_remediation_execution_request(...)` to produce
  `cx_remediation_execution_request.v1`.
- Added `HttpCxRemediationExecutionClient` for:
  - `POST /api/v1/generations/{cx_generation_id}/remediation-executions`;
  - AG service-token headers;
  - trace/request propagation;
  - response schema-version checks;
  - problem, timeout, malformed JSON, non-object JSON, and wrong-schema
    response handling.
- Added `build_default_cx_remediation_execution_client(...)` with:
  - `NEX_CX_BASE_URL`;
  - `NEX_AG_TO_CX_SERVICE_TOKEN`;
  - `NEX_AG_CX_REMEDIATION_TIMEOUT_SECONDS`.
- Added handoff redaction checks that allow false redaction flags but reject
  raw prompt/output/source/evidence fields, provider endpoint details,
  credentials, tokens, model paths, and storage paths.

## Boundary Notes

- Only `retry_generation`, `retrieval_repair`, and `citation_repair` are
  executable by CX.
- AG-only actions such as `prompt_policy_review`, `operator_followup`, and
  `mark_accepted` are rejected before HTTP handoff.
- The outgoing request always sets
  `parent_generation_mutation_allowed=false` and
  `provider_boundary=cx_to_mo_service_api_only`.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
next_slice=0354_cx_remediation_execution_service_api_foundation
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_handoff.py -q
9 passed in 0.36s

./.venv/bin/pytest tests/test_nex_ag_generation_remediation_handoff.py -q --cov=nex_ag.generation_remediation_handoff --cov-report=json:/tmp/handoff_cov.json --cov-report=term-missing
9 passed in 1.61s
nex_ag.generation_remediation_handoff statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2441 passed, 1 warning in 81.01s
statement_coverage=98.53% threshold=95.00%
branch_coverage=95.75% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
