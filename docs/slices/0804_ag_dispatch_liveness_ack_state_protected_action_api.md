# Slice 0804: AG dispatch liveness acknowledgement/suppression protected action API

## Objective

Expose the dispatch daemon liveness acknowledgement/suppression state machine
through a protected AG operations API without changing the underlying liveness
projection or invoking process control.

## Scope

- Added protected POST route:
  `/admin/v1/operator-review/dispatch-daemon/liveness/ack-state`.
- Wired the route into the AG runtime store selection so memory and DB-backed
  persistence profiles use the same API surface.
- The route derives service, worker, and liveness status from the current
  server-side dispatch daemon liveness projection.
- Added clear-by-`acknowledgement_key` support so operators can clear an
  existing acknowledgement even after the live heartbeat has recovered.
- Added audit events for applied, rejected, and failed action requests.
- Added API regression coverage for auth rejection, accepted TTL suppression,
  clear flow, action-matrix rejection, store persistence, and audit redaction.

## Decisions

- The route records acknowledgement/suppression state only; it does not suppress
  the source liveness projection and does not call daemon process-control APIs.
- Raw operator comments and idempotency keys are not stored in audit details.
  The persisted state keeps bounded previews and hashes only.
- PostgreSQL smoke for the persisted acknowledgement state remains a dedicated
  later Slice so it can connect to the real AG test DB and verify migrations.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack_api.py -q
```

Result: `11 passed, 1 warning in 0.68s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack.py tests/test_nex_ag_operator_review_liveness_ack_api.py -q --cov=nex_ag.operator_review_liveness_ack --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `28 passed, 1 warning in 4.23s`; acknowledgement state module
statement/branch coverage stayed at `100%`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_operator_review_liveness_ack.py tests/test_nex_ag_operator_review_liveness_ack_api.py -q --tb=short
```

Result: `233 passed, 1 warning in 5.07s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5309 passed, 1 warning in 321.18s`.

Coverage totals:

- Statement coverage: `98.72221579069229%` (`68221/69104`).
- Branch coverage: `96.14747307373653%` (`16247/16898`).
