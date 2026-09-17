# Slice 0820: S82 AG dispatch liveness acknowledgement expiry closure

## Purpose

Close S82 by proving that acknowledgement expiry reconciliation is complete,
reproducible, and operationally bounded from repository evidence.

## Closure

- Reuses `ag_op_review_ack_state`; no new table was introduced.
- Adds only the short candidate index `idx_ag_ack_state_expiry`.
- Reconciles durable `SUPPRESSED` rows to `EXPIRED` in bounded batches.
- Protects concurrent renewal through compare-and-set semantics.
- Exposes one protected reconciliation API plus read-only dashboard and issue
  overlays.
- Freezes runtime behavior in static OpenAPI and operations JSON Schema.
- Records actual `nex_ag_test` migration, candidate selection, transition,
  idempotent rerun, stale-CAS rejection, and scoped cleanup evidence.
- Records privacy, redacted audit, concurrency, and operator runbook evidence.

## Guardrails

- Source heartbeat/liveness projections are never mutated or suppressed.
- Reconciliation results and audit events contain no raw comments,
  idempotency keys, credentials, provider keys, or database URLs.
- Retention and physical deletion remain outside S82.
- This closure adds no runtime mutation surface or database object.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py --summary
./.venv/bin/pytest tests/test_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py -q --tb=short
```

Closure result:
`s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure=pass slice_range=0811-0820 table=ag_op_review_ack_state index=idx_ag_ack_state_expiry postgres=True privacy=True`.

Contract validation result:
`contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

S82 regression bundle result: `61 passed, 1 warning`.

Full regression result: `5411 passed, 1 warning`.

- Statement coverage: `69285 / 70168 = 98.741591608711%`.
- Branch coverage: `16407 / 17058 = 96.183608863876%`.
- New closure runner statement/branch coverage: `100% / 100%`.
