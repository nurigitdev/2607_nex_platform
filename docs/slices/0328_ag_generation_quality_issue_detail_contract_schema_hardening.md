# Slice 0328: AG Generation Quality Issue Detail Contract Schema Hardening

## Scope

Freeze the Slice 0326-0327 generation quality issue detail API response shape as
a contract package artifact.

## Implemented

- Added JSON Schema:
  - `ag_generation_quality_issue_detail_projection.v1`
- Added positive example:
  - metadata-gap warning runbook projection
- Added negative example:
  - `raw_content_included: true` redaction violation
- Registered the examples in contract indexes.
- Added OpenAPI `200` response schema wiring for:
  - `GET /admin/v1/generation-audit/generations/{cx_generation_id}/quality-issue-detail`
- Added regression coverage that validates the Python projection against the
  JSON Schema and checks the OpenAPI response schema reference.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py -q
176 passed, 1 warning
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=52 examples=84 negative_examples=61 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2217 passed, 1 warning
statement_coverage=98.55%
branch_coverage=95.48%
contract_validation=pass schemas=52 examples=84 negative_examples=61 openapi=7
```
