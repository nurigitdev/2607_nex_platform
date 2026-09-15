# Slice 0798: AG dispatch liveness recovery privacy/runbook evidence

## Objective

Close the privacy/runbook evidence gap for S80 dispatch daemon liveness recovery
and record the acknowledgement/suppression state persistence decision without
creating a new table in this slice.

## Scope

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py`.
- Verified recovery surfaces remain redaction-safe:
  - stale and missing recovery plans,
  - dashboard `daemon_recovery`,
  - planned recovery audit details,
  - liveness issue candidates,
  - runbook/action matrix,
  - acknowledgement/suppression persistence decision.
- Confirmed runtime recovery-plan route exposure:
  `GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan`.
- Recorded the persistence decision:
  - no acknowledgement/suppression state table in Slice 0798,
  - current state remains non-persistent,
  - future candidate table name: `ag_op_review_ack_state`,
  - table name length remains below the 30-character review limit.
- Added the 0797 protected smoke and 0798 evidence scripts to the quality gate.

## Deferred

- Slice 0799: static OpenAPI/schema hardening for recovery routes.
- Slice 0800: S80 recovery foundation closure checkpoint.
- Future operator action-state slice: implement persisted acknowledgement and TTL
  suppression semantics after operator identity/reason-code policy is finalized.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py -q
```

Result: `7 passed in 0.52s`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook=pass surfaces=8 privacy=True runbooks=True ack_state=ag_op_review_ack_state persisted_now=False`.

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence --cov-branch --cov-report=term-missing
```

Result: `7 passed in 1.29s`; script coverage statement/branch `100%`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5268 passed, 1 warning in 310.13s`.

Coverage totals from `/tmp/nex_platform_0798_coverage.json`:

- statement coverage: `98.71290303772375%` (`67721/68604`)
- branch coverage: `96.12361557699178%` (`16143/16794`)
