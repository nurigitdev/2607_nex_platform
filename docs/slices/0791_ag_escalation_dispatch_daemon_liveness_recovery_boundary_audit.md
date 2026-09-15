# Slice 0791: AG dispatch liveness recovery boundary audit

## Objective

Start S80 by fixing the AG operator review escalation dispatch daemon liveness
recovery boundary before adding recovery action-plan contracts, protected
recovery routes, recovery audit events, dashboard integration, acknowledgement
or suppression policy, PostgreSQL smoke evidence, or OpenAPI/schema hardening.

## Scope

- Added
  `run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py`.
- Verified S79 closure as the baseline for recovery planning.
- Confirmed Slice 0791 introduces no new database table, no recovery-plan
  route, no recovery mutation, and no daemon subprocess start/stop mutation.
- Locked the recovery boundary to reuse:
  - `service_worker_heartbeats` as the liveness source,
  - `/admin/v1/operator-review/dispatch-daemon/liveness` as the evidence route,
  - `/admin/v1/operator-review/dispatch-daemon/process-controls` as the later
    guarded process-control route,
  - `service_operational_events` as the future recovery audit source,
  - `ag_op_esc_dispatches` as the dispatch work source.
- Kept recovery planning as a pure read model for S80 entry:
  - `STALE` maps first to `inspect_stale_dispatch_daemon_heartbeat`.
  - `MISSING` maps first to `start_or_inspect_dispatch_daemon_process`.
  - heartbeat source configuration or availability failures remain inspection
    actions, not direct process mutation.
- Added the audit runner to `scripts/quality/run_quality_gate.sh`.
- Indexed the slice in `docs/README.md`.

## Follow-Up Slices

- Slice 0792: liveness recovery action-plan contract.
- Slice 0793: protected liveness recovery-plan route.
- Slice 0794: recovery action audit event emission.
- Slice 0795: operations dashboard recovery action integration.
- Slice 0796: liveness issue acknowledgement/suppression policy.
- Slice 0797: PostgreSQL smoke evidence against the real test DB.
- Slice 0798: privacy/runbook evidence.
- Slice 0799: contract/OpenAPI/schema hardening.
- Slice 0800: S80 closure.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit --cov-branch --cov-report=term-missing
```

Result: `7 passed in 0.16s`.

Coverage for the Slice 0791 audit runner: statement `100%`, branch `100%`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary_audit.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_recovery_boundary=pass boundary=ag_owned_operator_review_escalation_dispatch_daemon_liveness_recovery new_table=False mutation=False liveness_source=service_worker_heartbeats plan=Slice_0792 route=Slice_0793`.

```bash
bash -n scripts/quality/run_quality_gate.sh
```

Result: passed.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5242 passed, 1 warning in 300.38s`.

Coverage totals: statement `98.70%` (`67191/68076`), branch `96.09%`
(`16008/16660`).
