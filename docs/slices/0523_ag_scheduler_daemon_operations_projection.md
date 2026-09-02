# Slice 0523: AG Scheduler Daemon Operations Projection

## Scope

Add the AG-side scheduler daemon operations projection on top of the AE daemon
client adapter from Slice 0522.

## Decision

- AG projects AE daemon config/control responses as metadata-only operator
  evidence.
- AG does not expose storage paths, database endpoints, raw artifact payloads,
  or tick execution internals in the projection.
- `manual_tick_once` is the only future dispatch path that AG should surface to
  operators; `start_daemon` and continuous-loop execution remain blocked.
- This slice adds projection and summary logic only. Protected AG routes and
  dispatch guardrails remain staged for later S53 slices.

## Implementation

- Added `ag_artifact_operation_retention_daemon_projection.v1`.
- Added a projection builder for AE daemon config and optional daemon dispatch
  responses.
- Added a compact summary for daemon runtime, lease repository, JobQueue
  posture, supported action readiness, and last dispatch outcome.
- Normalized AE redaction flags into AG-safe vocabulary so forbidden fragments
  such as database endpoint names or storage reference labels do not appear in
  operator projections.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Result:

```text
57 passed
services/nex-ag/nex_ag/artifact_operations.py 99%
```

## Next

Slice 0524 should expose this projection through a protected AG operations route
without adding AG-side persistence writes or direct JobQueue dispatch.
