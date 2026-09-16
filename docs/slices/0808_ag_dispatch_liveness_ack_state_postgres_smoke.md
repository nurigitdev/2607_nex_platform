# Slice 0808: AG dispatch liveness acknowledgement/suppression PostgreSQL smoke

## Objective

Prove the S81 acknowledgement/suppression state path against the real
`nex_ag_test` PostgreSQL database instead of only SQLite/unit-level regression.

## Scope

- Added a protected smoke runner for
  `ag_op_review_ack_state` PostgreSQL persistence.
- The smoke runner executes `nex-ag` test-profile migrations through the shared
  migration runner before touching the database.
- The smoke exercises:
  - stale dispatch daemon heartbeat projection;
  - persisted `suppress_for_ttl` acknowledgement state;
  - `get`, `get_by_acknowledgement_key`, and filtered `list_states`;
  - recovery-plan overlay reading the persisted state;
  - persisted `clear` transition;
  - row-level SQL observations and cleanup.
- Added quality-gate wiring. The smoke remains opt-in via
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_ACK_STATE_POSTGRES_SMOKE=1`.

## Decisions

- The smoke uses `NEX_AG_TEST_DATABASE_URL` and `profile=test` so it cannot
  accidentally target the dev database through the default path.
- The runner preserves any pre-existing daemon heartbeat or ack-state row for
  the canonical dispatch daemon acknowledgement key, then restores it during
  cleanup.
- The raw smoke secret is only used as an idempotency key; the database evidence
  verifies that the raw value is not persisted or emitted.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py -q --tb=short
```

Result: `13 passed in 0.84s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py tests/test_nex_ag_operator_review_liveness_ack_api.py tests/test_nex_ag_operations.py tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py -q --tb=short
```

Result before the final helper-branch addition:
`258 passed, 1 warning in 3.07s`.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_ACK_STATE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<redacted nex_ag_test URL>' \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL backend=postgresql rows=1 overlay=STATE_PRESENT cleared=CLEARED deleted_ack_state_rows=1`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5335 passed, 1 warning in 332.53s`.

Coverage JSON: `/tmp/nex_platform_0808_coverage.json`

- Statement coverage: `68492 / 69375 = 98.7272072072072%`.
- Branch coverage: `16301 / 16952 = 96.15974516281264%`.
