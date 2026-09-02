# Slice 0521: AG Scheduler Daemon Operations Boundary Audit

## Scope

Start S53 by freezing how AG will observe and request AE artifact retention
scheduler daemon operations.

## Decision

- AE remains the system of record for daemon config, daemon controls, leases,
  JobQueue dispatch, artifact records, and retention history.
- AG may expose operator-facing daemon operations only through AE APIs.
- AG must not write AE persistence directly.
- AG must not enqueue AE retention jobs directly.
- `manual_tick_once` is the only executable daemon control path for this track.
- `start_daemon` remains blocked by AE policy.
- Continuous daemon loop execution remains deferred.

## Implementation

- Added `scripts/smoke/run_ag_scheduler_daemon_operations_boundary_audit.py`.
- The audit checks the closed S52 baseline, AE daemon API surface, AE daemon
  runtime guardrails, existing AG retention operations, PostgreSQL daemon smoke
  evidence, and documentation/quality-gate wiring.
- The audit records the planned S53 sequence from AG client adapter through
  PostgreSQL smoke and closure.

## Evidence

```bash
./.venv/bin/pytest tests/test_ag_scheduler_daemon_operations_boundary_audit.py -q --cov=run_ag_scheduler_daemon_operations_boundary_audit --cov-branch --cov-report=term-missing
```

Expected summary:

```text
ag_scheduler_daemon_operations_boundary_audit=pass control=ae_api_only next=Slice_0522
```

## Next

Slice 0522 should add AG client adapter methods for AE daemon config and
controls before adding new AG routes or dispatch behavior.
