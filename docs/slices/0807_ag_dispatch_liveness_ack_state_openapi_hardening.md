# Slice 0807: AG dispatch liveness acknowledgement/suppression OpenAPI hardening

## Objective

Close the static contract gap for S81 acknowledgement/suppression APIs by
hardening the NeX-AG OpenAPI spec and contract validation checks.

## Scope

- Added OpenAPI paths for:
  - `POST /admin/v1/operator-review/dispatch-daemon/liveness/ack-state`.
  - `GET /admin/v1/operator-review/dispatch-daemon/liveness/ack-states`.
  - `GET /admin/v1/operator-review/dispatch-daemon/liveness/ack-states/{ack_state_id}`.
- Added OpenAPI schemas for acknowledgement state request, mutation, list,
  detail, state item, and recovery overlay projections.
- Added the recovery-plan `acknowledgement_state_overlay` requirement to the
  OpenAPI recovery-plan schema.
- Extended contract validation tests to pin operation ids, parameters, schema
  refs, action enum values, state table name, and non-suppression guardrails.

## Decisions

- The OpenAPI schemas stay intentionally safe and projection-oriented:
  `additionalProperties` remains true for nested operational payloads that may
  evolve, while route-level required fields and redaction/non-suppression flags
  are pinned.
- PostgreSQL smoke evidence remains Slice 0808.

## Regression

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q --tb=short
```

Result: `28 passed in 2.50s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py tests/test_nex_ag_operator_review_liveness_ack_api.py -q --tb=short
```

Result: `257 passed, 1 warning in 9.52s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5322 passed, 1 warning in 332.67s`.

Coverage JSON: `/tmp/nex_platform_0807_coverage.json`

- Statement coverage: `68303 / 69186 = 98.7237302344405%`.
- Branch coverage: `16269 / 16920 = 96.15248226950355%`.
