# Slice 0803: AG dispatch liveness acknowledgement/suppression state machine

## Objective

Define the deterministic state machine for AG dispatch daemon liveness
acknowledgement and TTL suppression state before adding protected API routes.

## Scope

- Extended `nex_ag.operator_review_liveness_ack` with transition helpers.
- Added deterministic acknowledgement keys and state ids.
- Added action matrix validation:
  - `MISSING`/`STALE`: `acknowledge_once`, `suppress_for_ttl`.
  - `SOURCE_NOT_CONFIGURED`/`SOURCE_UNAVAILABLE`:
    `acknowledge_source_attention`, `suppress_source_attention_for_ttl`.
  - `clear`: requires an existing state.
- Added TTL handling:
  - default suppression TTL: `1800` seconds.
  - maximum suppression TTL: `86400` seconds.
  - deterministic `suppressed_until` calculation when only TTL seconds are
    provided.
- Added effective-status projection so expired suppression can be read without
  mutating the source row.

## Decisions

- State transitions still do not call process-control or daemon lifecycle APIs.
- Expiration is a read-model/effective-status concern until a later cleanup job
  persists or prunes old state.
- Route wiring starts in Slice 0804 and will call these transition helpers.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py -q
```

Result: `17 passed in 0.43s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py -q --cov=nex_ag.operator_review_liveness_ack --cov-branch --cov-report=term-missing
```

Result: `17 passed in 0.99s`; module statement/branch coverage `100%`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py tests/test_db_migration_runner.py -q
```

Result: `35 passed in 0.52s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5298 passed, 1 warning in 311.93s`.

Coverage totals:

- Statement coverage: `98.72047529343574%` (`68127/69010`).
- Branch coverage: `96.14290792747956%` (`16227/16878`).
