# Slice 0781: AG dispatch daemon liveness/heartbeat boundary audit

## Objective

Start S79 by fixing the AG operator review escalation dispatch daemon liveness
boundary before adding heartbeat emission, liveness read models, protected
routes, dashboard stale-state integration, or PostgreSQL smoke evidence.

## Scope

- Added
  `run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py`.
- Verified S78 closure as the baseline for liveness work.
- Confirmed Slice 0781 introduces no new database table, no heartbeat emission,
  no protected liveness route, no dashboard liveness mutation, and no process
  start/stop mutation.
- Locked the liveness contract to reuse:
  - `service_worker_heartbeats` as the liveness source,
  - `WorkerHeartbeatEmitter` and `SqlAlchemyWorkerHeartbeatStore` for future
    emission and PostgreSQL smoke,
  - `worker_heartbeat_is_stale` with the shared default stale threshold,
  - `service_operational_events` for lifecycle evidence,
  - `ag_op_esc_dispatches` for dispatch work state.
- Kept the daemon worker identity stable:
  - `service_id`: `nex-ag`
  - `worker_id`: `ag-dispatch-execution-daemon`
  - `worker_type`: `operator_review_dispatch_daemon`
- Added the audit runner to `scripts/quality/run_quality_gate.sh`.
- Indexed the slice in `docs/README.md`.

## Follow-Up Slices

- Slice 0782: heartbeat contract/wire shape for the dispatch daemon.
- Slice 0783: heartbeat emission from the executable daemon boundary.
- Slice 0784: liveness read-model foundation.
- Slice 0785: protected liveness route.
- Slice 0786: operations dashboard liveness/stale integration.
- Slice 0787: stale daemon issue-candidate integration.
- Slice 0788: PostgreSQL smoke evidence against the real test DB.
- Slice 0789: privacy/runbook evidence.
- Slice 0790: S79 closure.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit --cov-branch --cov-report=term-missing
```

Result: `7 passed in 0.15s`.

Coverage for the Slice 0781 audit runner: statement `100%`, branch `100%`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_boundary_audit.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_boundary=pass boundary=ag_owned_operator_review_escalation_dispatch_daemon_liveness new_table=False heartbeat_source=service_worker_heartbeats worker_id=ag-dispatch-execution-daemon contract=Slice_0782 read_model=Slice_0784`.

```bash
bash -n scripts/quality/run_quality_gate.sh
```

Result: passed.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5201 passed, 1 warning in 293.70s`.

Coverage totals: statement `98.69%` (`66631/67514`), branch `96.07%`
(`15881/16530`).
