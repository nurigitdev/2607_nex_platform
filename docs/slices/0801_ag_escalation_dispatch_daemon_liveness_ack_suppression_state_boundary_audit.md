# Slice 0801: AG dispatch liveness acknowledgement/suppression state boundary audit

## Objective

Start S81 by fixing the boundary for persisted operator acknowledgement and TTL
suppression state for AG dispatch daemon liveness recovery.

## Scope

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py`.
- Confirmed S81 begins only after S80 closure.
- Reserved the short future table name `ag_op_review_ack_state`.
- Confirmed Slice 0801 creates no table and opens no mutation route.
- Fixed the storage boundary:
  - allowed: safe operator overlay state, bounded reason codes, comment hash,
    comment preview, idempotency-key hash, TTL fields, metadata.
  - forbidden: raw comments, raw provider/notification/incident/heartbeat
    payloads, database URLs, tokens, storage paths, raw idempotency keys.
- Confirmed persisted state must not hide the current liveness projection.
- Planned S81 continuation:
  - Slice 0802: persistence foundation.
  - Slice 0803: state machine.
  - Slice 0804: protected action API.
  - Slice 0805: persisted read model.
  - Slice 0806: dashboard/issue/recovery overlay.
  - Slice 0807: contract/OpenAPI hardening.
  - Slice 0808: PostgreSQL smoke evidence.
  - Slice 0809: privacy/runbook evidence.
  - Slice 0810: closure checkpoint.

## Decisions

- `service_worker_heartbeats` remains the liveness source of truth.
- `service_operational_events` remains the safe action-history source.
- `ag_op_review_ack_state` will store only AG-owned operator overlay state.
- Acknowledgement/suppression may affect dashboard, issue-candidate, and
  recovery-plan overlays, but it must not mutate or suppress the source liveness
  projection.
- TTL suppression uses the S80 policy values:
  - default: `1800` seconds.
  - maximum: `86400` seconds.
- Retention cleanup remains deferred to the later recovery-retention work.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py -q
```

Result: `8 passed in 0.08s`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary=pass boundary=ag_owned_operator_review_dispatch_daemon_liveness_ack_suppression_state table=ag_op_review_ack_state new_table=False projection_suppressed=False default_ttl=1800 next=Slice_0802`.

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit --cov-branch --cov-report=term-missing
```

Result: `8 passed in 0.14s`; script coverage statement/branch `100%`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5281 passed, 1 warning in 283.84s`.

Coverage totals:

- Statement coverage: `98.71513176083698%` (`67840/68723`).
- Branch coverage: `96.1259223994287%` (`16153/16804`).
