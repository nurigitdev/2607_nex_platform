# Slice 0541: AE scheduler daemon process boundary audit

## Scope

Start S55 by freezing the AE scheduler daemon process model before adding any
bounded loop, runtime state store, lifecycle transition, graceful shutdown, or
continuous process entrypoint.

## Boundary Decision

- `nex-ae-api` remains the scheduler daemon system of record.
- The daemon process is an AE-owned coordinator process, not a long-running
  JobQueue job.
- Actual artifact retention work must continue to enter through the existing
  JobQueue admission and finite worker execution path.
- The AE API remains the control/read boundary for daemon config, runtime
  observation, and control requests.
- AG remains read-only and metadata-only: it may observe runtime state and
  request AE-owned controls, but must not write AE persistence or enqueue AE
  jobs directly.
- Long-running loops must not be embedded inside the large AE artifact route
  module.
- Continuous loop execution remains blocked until runtime state, bounded loop
  behavior, graceful shutdown, and protected PostgreSQL evidence are in place.

## Refactoring Checkpoint

The next implementation should treat the daemon as a coordinator around the
existing one-cycle runner. Each daemon iteration should plan first, acquire AE
lease/fencing through the existing path, enqueue finite retention work through
JobQueue, optionally run a bounded worker path only when explicitly requested,
emit heartbeat metadata, and then return to the daemon process loop.

## Planned S55 Slices

- Slice 0542: daemon runtime state contract/schema.
- Slice 0543: daemon CLI entrypoint foundation.
- Slice 0544: bounded loop adapter.
- Slice 0545: bounded loop PostgreSQL smoke evidence.
- Slice 0546: graceful shutdown/state transition.
- Slice 0547: retry/backoff/circuit guard.
- Slice 0548: AG daemon lifecycle projection.
- Slice 0549: AG-to-AE lifecycle PostgreSQL smoke evidence.
- Slice 0550: S55 closure checkpoint.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_scheduler_daemon_process_boundary_audit.py -q --cov=run_ae_scheduler_daemon_process_boundary_audit --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ae_scheduler_daemon_process_boundary_audit.py --summary
```
