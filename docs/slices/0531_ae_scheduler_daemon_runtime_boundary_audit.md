# Slice 0531: AE scheduler daemon runtime boundary audit

## Scope

Start S54 by freezing the AE scheduler daemon runtime enablement boundary before
adding runtime config expansion, loop planning, one-cycle execution, start/stop
controls, or AG runtime projections.

## Boundary Decision

- `nex-ae-api` remains the scheduler daemon system of record.
- The daemon remains disabled by default.
- Runtime enablement is limited to the test profile and explicit opt-in until
  protected PostgreSQL evidence proves the one-cycle path.
- Continuous loop execution remains blocked until a pure state machine,
  one-cycle runner, lease/fencing checks, batch-window checks, and heartbeat
  read-model are in place.
- Scheduler execution remains `DRY_RUN` by default.
- Physical delete automation remains disabled.
- `nex-ag` may observe or request daemon actions only through AE APIs and must
  not write AE persistence or enqueue AE jobs directly.

## Refactoring Checkpoint

Long-running loop behavior should not be added to the large artifact route
surface. S54 should first add explicit runtime config, then a pure state machine,
then a one-cycle runner, then protected PostgreSQL smoke evidence, and only then
consider guarded start/stop control.

## Planned S54 Slices

- Slice 0532: runtime config expansion.
- Slice 0533: loop planner state machine.
- Slice 0534: one-cycle runner adapter.
- Slice 0535: start/stop control guardrail.
- Slice 0536: one-cycle PostgreSQL smoke evidence.
- Slice 0537: runtime heartbeat observability.
- Slice 0538: AG runtime operations projection.
- Slice 0539: AG runtime attention and issue candidates.
- Slice 0540: S54 closure checkpoint.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_scheduler_daemon_runtime_boundary_audit.py -q --cov=run_ae_scheduler_daemon_runtime_boundary_audit --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ae_scheduler_daemon_runtime_boundary_audit.py --summary
```
