# Slice 0811: AG dispatch liveness acknowledgement expiry reconciliation boundary audit

## Objective

Start S82 by fixing the boundary for durable expiry reconciliation of persisted
dispatch-daemon liveness acknowledgement/suppression state.

## Decisions

- Reuse `ag_op_review_ack_state`; Slice 0811 creates no table and route.
- Reconcile only `SUPPRESSED` rows whose `suppressed_until` is at or before the
  observation time into persisted `EXPIRED` state.
- Require bounded batches, idempotency, and compare-and-set semantics so an
  operator `clear` or renewed suppression cannot be overwritten by a stale run.
- Keep `service_worker_heartbeats` as the liveness source of truth and never
  suppress or mutate its projection.
- Emit only safe operational-event summaries; raw comments, idempotency keys,
  provider payloads, tokens, and database URLs remain forbidden.
- Keep retention and physical deletion outside S82; the existing decision
  defers those concerns to S89.

## Planned Slices

- Slice 0812: reconciliation contract and transition.
- Slice 0813: candidate persistence adapter.
- Slice 0814: reconciliation worker.
- Slice 0815: protected manual API and audit event.
- Slice 0816: operations overlay.
- Slice 0817: OpenAPI/schema hardening.
- Slice 0818: real `nex_ag_test` PostgreSQL smoke.
- Slice 0819: privacy, concurrency, and runbook evidence.
- Slice 0820: S82 closure.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.py -q --tb=short
./.venv/bin/python scripts/smoke/run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.py --summary
```

Result: `9 passed`; boundary summary `pass`.

Full regression and coverage:

```bash
./.venv/bin/pytest -q --cov=services --cov=scripts --cov=providers --cov-branch
```

Result: `5359 passed, 1 warning`.

- Statement coverage: `68787 / 69670 = 98.732596526482%`.
- Branch coverage: `16339 / 16990 = 96.168334314303%`.
