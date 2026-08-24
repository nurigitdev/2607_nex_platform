# Slice 0333: AE Generation Feedback Intake API Regression

## Scope

Wire the Slice 0332 feedback contract into AE API routes with in-memory
regression coverage. PostgreSQL persistence is deferred to Slice 0334.

## Implemented

- Added AE feedback routes:
  - `POST /api/v1/chat/interactions/{interaction_id}/feedback`;
  - `GET /api/v1/chat/interactions/{interaction_id}/feedback`;
  - `GET /api/v1/chat/interactions/{interaction_id}/feedback/{feedback_id}`.
- Added `GenerationFeedbackStore` for route-level regression and default local
  runtime wiring.
- Registered the route in `nex_ae_api.main`.
- Enforced route/payload `interaction_id` match.
- Mapped sensitive payload, validation, not-found, and auth failures to problem
  responses.
- Added OpenAPI path entries with inline safe response schema hints.
- Expanded regression coverage for create/list/read, auth, mismatch, sensitive
  payload rejection, and wrong-scope reads.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_generation_feedback.py -q
25 passed, 1 warning
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=53 examples=85 negative_examples=62 openapi=7
```

Next slice:

```text
Slice 0334: AE feedback PostgreSQL smoke evidence
```
