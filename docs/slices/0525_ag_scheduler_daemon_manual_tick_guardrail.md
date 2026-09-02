# Slice 0525: AG Scheduler Daemon Manual Tick Guardrail

## Scope

Add the protected AG manual tick-once dispatch route for AE artifact retention
scheduler daemon operations.

## Decision

- AG exposes only
  `POST /admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once`
  for daemon dispatch.
- The route requires `confirm_dispatch=true` and rejects every action except
  `manual_tick_once`.
- AG rechecks AE daemon config before dispatch and calls AE only when the
  `manual_tick_once` action is `READY`.
- `run_worker=true` is accepted only with `confirm_worker_run=true`; otherwise
  AG returns a guarded conflict response.
- AG still does not write AE persistence, acquire leases directly, enqueue
  JobQueue rows directly, start a daemon, or start a continuous loop.

## Implementation

- Added the protected manual tick-once AG route.
- Added request validation for operator confirmation, action, owner scope,
  retention days, scan/delete limits, worker-run confirmation, idempotency-key
  precedence, and safe `requested_by` forwarding.
- Added route regression coverage for success, auth, service filter, missing
  scope, invalid limits, invalid worker flag, worker confirmation, AE config
  readiness block, AE config source failure, and AE dispatch source failure.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Result:

```text
62 passed
services/nex-ag/nex_ag/artifact_operations.py 99%
```

## Next

Slice 0526 should add protected PostgreSQL smoke evidence for the AG-to-AE
daemon route path against the AE test database.
