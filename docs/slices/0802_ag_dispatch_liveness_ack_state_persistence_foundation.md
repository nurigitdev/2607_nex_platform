# Slice 0802: AG dispatch liveness acknowledgement/suppression state persistence foundation

## Objective

Add the AG-owned persistence foundation for operator acknowledgement and TTL
suppression state around dispatch daemon liveness recovery.

## Scope

- Added `nex_ag.operator_review_liveness_ack`.
- Added `database/nex-ag/migrations/0802_ag_liveness_ack_state.sql`.
- Created the short table `ag_op_review_ack_state`.
- Kept `service_worker_heartbeats` as the liveness source of truth.
- Kept `service_operational_events` as the action-history source.
- Stored only safe overlay state:
  - `comment_hash` and bounded `comment_preview`.
  - `idempotency_key_hash`.
  - bounded `reason_codes`.
  - operator identity and TTL fields.
- Added in-memory and SQLAlchemy store implementations.
- Added SQLite regression for upsert/select/list/delete behavior.

## Decisions

- `ag_op_review_ack_state` stores the current operator overlay per
  acknowledgement key; action history remains in operational events.
- Slice 0802 does not expose a mutation route.
- Slice 0802 does not alter dashboard or issue-candidate overlays.
- Route wiring starts in Slice 0804 after the Slice 0803 state machine.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py -q
```

Result: `11 passed in 0.39s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py -q --cov=nex_ag.operator_review_liveness_ack --cov-branch --cov-report=term-missing
```

Result: `11 passed in 0.97s`; module statement/branch coverage `100%`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py tests/test_db_migration_runner.py -q
```

Result: `29 passed in 0.51s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5292 passed, 1 warning in 304.97s`.

Coverage totals:

- Statement coverage: `98.71889735219442%` (`68042/68925`).
- Branch coverage: `96.13649851632047%` (`16199/16850`).
