# Slice 0388: AE Repaired Handoff User Decision Service API Wiring

## Scope

Wire the repaired response user decision contract into AE service routes.

This slice keeps PostgreSQL smoke execution out of scope. It exercises the
runtime route boundary with in-memory stores and leaves the real AE test DB
evidence to Slice 0389.

## Implemented

- Registered repaired response decision routes in `nex-ae-api`.
- Added `POST /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{handoff_id}/decisions`.
- Added decision list and detail routes under the same handoff path.
- Reused AE service-token authorization and problem-response shape.
- Enforced handoff existence, interaction scope, and decision handoff scope
  before storing or returning decision records.
- Added a decision collection projection for list responses.
- Covered success, unauthorized, missing handoff, invalid payload, sensitive
  payload, missing decision, and detail/list scope failure paths.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q --cov=nex_ae_api.repaired_response_decisions --cov-branch --cov-report=term-missing
67 passed, 1 warning in 2.78s
repaired_response_decisions.py statement_coverage=100% branch_coverage=100%
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2831 passed, 1 warning in 91.31s
statement_coverage=98.67% threshold=95.00%
branch_coverage=96.12% threshold=85.00%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

Recommended next slice:

```text
Slice 0389: AE repaired handoff decision PostgreSQL smoke evidence
```
