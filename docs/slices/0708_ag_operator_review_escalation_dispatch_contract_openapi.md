# Slice 0708: AG operator review escalation dispatch contract/OpenAPI

## Intent

Harden the S71 escalation dispatch outbox as a canonical contract surface, not
just runtime routes.

## Scope

- Extend `operator_review_case.v1` with dispatch plan, dispatch record,
  dispatch list, and dispatch action mutation response definitions.
- Add indexed positive examples for create/list/action response shapes.
- Add a negative fixture that proves raw provider payloads cannot cross the
  contract boundary.
- Register the protected S71 dispatch create, list, detail, and action routes
  in `nex-ag.openapi.yaml`.
- Add regression tests that validate runtime builder output against the
  canonical schema and assert the OpenAPI route/component surface.

## Decision

The create route is contractually modeled as a dispatch plan response because
that is the actual runtime response shape. Dispatch records remain safe outbox
state: provider payload bodies, provider secrets, raw external incident payloads,
raw operator comments, raw source text, database URLs, tokens, and raw
idempotency keys are excluded from the contract.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

S71 dispatch clients can now rely on stable JSON Schema and OpenAPI surfaces for
plan creation, outbox list/detail reads, and state-machine action mutations.
