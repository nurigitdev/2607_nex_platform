# Slice 0800: S80 AG dispatch daemon liveness recovery closure checkpoint

## Scope

- Added
  `scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py`.
- Added a closure test that verifies required S80 files and token checks for
  Slice 0791 through Slice 0800.
- Registered the S80 closure runner in `scripts/quality/run_quality_gate.sh`.
- Indexed the closure document in `docs/README.md`.

## Closure Boundary

- Boundary:
  `ag_owned_operator_review_escalation_dispatch_daemon_liveness_recovery`.
- Source tables:
  - `service_worker_heartbeats`
  - `service_operational_events`
- New tables: none.
- Protected routes:
  - `GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/process-controls`
- Closed surfaces:
  - boundary audit.
  - recovery action-plan contract.
  - protected recovery-plan route.
  - safe recovery audit event.
  - operations dashboard `daemon_recovery`.
  - liveness issue acknowledgement/suppression policy.
  - real `nex_ag_test` PostgreSQL smoke evidence.
  - privacy/runbook and acknowledgement state decision evidence.
  - static OpenAPI/schema hardening.
- Acknowledgement/suppression state:
  - current state is not persisted in S80.
  - future table candidate is `ag_op_review_ack_state`.

## Verification

```bash
./.venv/bin/pytest tests/test_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py -q
```

Result: `5 passed in 0.06s`.

```bash
./.venv/bin/python scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py --summary
```

Result:
`s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure=pass slice_range=0791-0800 required_files=26 boundary=ag_owned_operator_review_escalation_dispatch_daemon_liveness_recovery route=GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan smoke=test_db_service_worker_heartbeats_liveness_recovery_audit_dashboard_issue ack_state=ag_op_review_ack_state`.

```bash
./.venv/bin/pytest tests/test_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py -q --cov=run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure --cov-branch --cov-report=term-missing
```

Result: `5 passed in 0.14s`; script coverage statement/branch `100%`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5273 passed, 1 warning in 313.67s`.

Coverage totals from `/tmp/nex_platform_0800_coverage.json`:

- statement coverage: `98.71357808857809%` (`67757/68640`)
- branch coverage: `96.125%` (`16149/16800`)
