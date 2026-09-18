# Slice 0831: AG recovery notification policy boundary audit

## Objective

Start S84 by fixing the ownership and safety boundary for dispatch-daemon
recovery notification policy without sending an external notification.

## Decisions

- NeX-AG owns policy evaluation and redacted notification previews.
- Inputs are the existing liveness recovery plan and persisted
  acknowledgement/suppression overlay.
- S84 defines explicit severity, eligibility, suppression, and redaction rules.
- Delivery remains disabled by default.
- Existing S73/S74 notification provider adapters are reserved for a later
  delivery requirement and are not invoked by S84.
- `ag_op_review_ack_state` and `service_operational_events` are read/reused; no
  table is added.
- Dispatch persistence, retries, external HTTP calls, retention, and physical
  deletion remain outside S84.

## Planned Slices

- Slice 0832: policy configuration contract.
- Slice 0833: notification eligibility evaluation.
- Slice 0834: redacted notification plan.
- Slice 0835: protected policy preview API.
- Slice 0836: operations policy projection.
- Slice 0837: OpenAPI and schema hardening.
- Slice 0838: actual `nex_ag_test` PostgreSQL smoke.
- Slice 0839: privacy and operator runbook evidence.
- Slice 0840: S84 closure.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_policy_boundary_audit.py --summary
./.venv/bin/pytest \
  tests/test_ag_recovery_notification_policy_boundary_audit.py -q --tb=short
```

Boundary result:
`ag_recovery_notification_policy_boundary=pass owner=nex-ag provider_call=False new_table=False next=Slice_0832_policy_configuration_contract`.

Focused regression result: `6 passed`.

Full regression result: `5501 passed, 1 warning`.

- Statement coverage: `70009 / 70892 = 98.754443378660%`.
- Branch coverage: `16497 / 17148 = 96.203638908328%`.
- Boundary runner statement coverage: `100%`.
