# Slice 0520: S52 AE Scheduler Daemon Closure

## Scope

Close S52 by verifying that the AE artifact retention scheduler daemon boundary
is connected from audit through lease persistence, manual tick-once execution,
service API wiring, and protected PostgreSQL smoke evidence.

## Implementation

- Added `scripts/smoke/run_s52_ae_scheduler_daemon_closure.py`.
- The closure checks required files for Slice 0511 through Slice 0520.
- It validates token coverage for scheduler daemon guardrails, lease
  persistence, tick-once runtime, daemon service routes, protected PostgreSQL
  smoke hooks, and documentation anchors.
- It is wired into `scripts/quality/run_quality_gate.sh`.

## Evidence

```bash
./.venv/bin/pytest tests/test_s52_ae_scheduler_daemon_closure.py -q --cov=run_s52_ae_scheduler_daemon_closure --cov-branch --cov-report=term-missing
```

Expected summary:

```text
s52_ae_scheduler_daemon_closure=pass slice_range=0511-0520
```

## Closure Position

- Daemon auto-start remains disabled.
- Continuous loop execution remains deferred.
- `manual_tick_once` is the only execution path wired through daemon controls.
- The runtime requires a lease before planning/enqueueing.
- PostgreSQL evidence covers migration, daemon route dispatch, lease readback,
  JobQueue readback, history readback, and cleanup against the AE test DB.
- AG remains read-only with respect to AE persistence and should call AE APIs
  for daemon visibility/control.
