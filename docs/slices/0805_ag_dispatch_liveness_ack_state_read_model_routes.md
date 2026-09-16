# Slice 0805: AG dispatch liveness acknowledgement/suppression read-model routes

## Objective

Expose persisted dispatch daemon liveness acknowledgement/suppression state as a
protected read model before dashboard, issue-candidate, and recovery-plan
overlays use it.

## Scope

- Added protected list route:
  `/admin/v1/operator-review/dispatch-daemon/liveness/ack-states`.
- Added protected detail route:
  `/admin/v1/operator-review/dispatch-daemon/liveness/ack-states/{ack_state_id}`.
- Added read-time effective-status projection for stored acknowledgement state.
- Added strict `observed_at` parsing for read-model effective TTL status checks.
- Preserved the S81 boundary: read routes do not mutate stored state and do not
  suppress the source liveness projection.
- Added API regression coverage for list/detail success, auth guard, missing
  state, invalid observed timestamp, store-unavailable failure, redaction, and
  non-mutating expiry projection.

## Decisions

- Stored `state_status` and read-time `effective_status` are both exposed so
  operators can see the durable row and the current effective interpretation.
- Expired TTL suppression remains a read-model condition in this slice; cleanup
  or persisted expiration is deferred to later retention work.
- No PostgreSQL smoke was added in this slice. The dedicated S81 PostgreSQL
  evidence remains Slice 0808.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack_api.py -q --tb=short
```

Result: `20 passed, 1 warning in 2.11s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_operator_review_liveness_ack.py tests/test_nex_ag_operator_review_liveness_ack_api.py -q --tb=short
```

Result: `242 passed, 1 warning in 7.15s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5318 passed, 1 warning in 321.89s`.

Coverage totals from `/tmp/nex_platform_0805_coverage.json`:

- Statement coverage: `68277 / 69160 = 98.72325043377676%`.
- Branch coverage: `16261 / 16912 = 96.15066225165563%`.
