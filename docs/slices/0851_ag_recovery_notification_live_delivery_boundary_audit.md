# Slice 0851: AG recovery notification live delivery boundary audit

## Objective

Start S86 by fixing the boundary for explicitly opted-in live HTTP delivery of
S85 recovery notifications.

## Decision

- Reuse the S85 recovery notification handoff and `ag_op_esc_dispatches`.
- Reuse the S74 live HTTP transport, provider router, timeout/retry policy, and
  safe execution-result projection.
- Keep the generic escalation planner closed to live channels by default. A
  later Slice may open it only through an explicit internal flag whose default
  remains `false`.
- Keep the S85 MOCK execution adapter unchanged and add a separate targeted
  live execution adapter.
- Require both the existing live-provider enable environment guard and an
  injected transport before any network call.
- Limit S86 to `NOTIFICATION`, `EMAIL`, and `WEBHOOK`. Recovery notifications
  do not use the incident channel.
- Use a local loopback HTTP server for protected smoke. A real external
  notification endpoint remains deferred until the full system is available.
- Add no table; the existing table name `ag_op_esc_dispatches` is 20 characters
  and remains within the 30-character project guideline.

## Planned Slices

- Slice 0852: live delivery admission/configuration contract.
- Slice 0853: live dispatch handoff wiring.
- Slice 0854: protected live delivery API guardrails.
- Slice 0855: targeted live execution and result projection.
- Slice 0856: contract and operations hardening.
- Slice 0857: local loopback HTTP transport smoke.
- Slice 0858: actual `nex_ag_test` PostgreSQL plus loopback smoke.
- Slice 0859: privacy, failure-mode, and operator runbook evidence.
- Slice 0860: S86 closure.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_live_delivery_boundary_audit.py \
  --summary
./.venv/bin/pytest -q --tb=short \
  tests/test_ag_recovery_notification_live_delivery_boundary_audit.py \
  --cov=run_ag_recovery_notification_live_delivery_boundary_audit \
  --cov-branch --cov-report=term-missing
```
