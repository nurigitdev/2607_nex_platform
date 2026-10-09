# Slice 1498: S150 Risk and Waiver Governance

Status: Complete.

## Outcome

- Added fail-closed P0/P1 risk evaluation with explicit `no_open_p0` and
  `p1_waivers_valid` release gates.
- Required a P1 waiver to name a distinct owner and approver, bounded issue and
  expiry times, compensating control, rollback trigger, and review cadence.
- Capped waiver lifetime at 30 days and rejected duplicate or ineligible risk
  bindings.
- Preserved the current external-notification risk as `OPEN` and
  `REQUIRED_NOT_GRANTED`; the policy evaluation passes while release decision
  readiness remains `NO_GO`.
- Kept all five distributed-environment limitations in backlog rather than
  misclassifying them as v1.0 release risks.
