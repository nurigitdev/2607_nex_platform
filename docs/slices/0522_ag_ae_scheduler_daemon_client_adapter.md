# Slice 0522: AG AE Scheduler Daemon Client Adapter

## Scope

Add the AG-side AE artifact retention scheduler daemon client adapter before
introducing new AG projections or routes.

## Decision

- AG calls AE-owned daemon APIs instead of touching AE persistence or JobQueue
  directly.
- `GET /api/v1/artifact-retention/scheduler-daemon-config` is the source for
  daemon runtime, lease repository, supported actions, and guardrail posture.
- `POST /api/v1/artifact-retention/scheduler-daemon-controls` is the only AG
  transport path for future operator-mediated `manual_tick_once` dispatch.
- Slice 0522 adds transport shape only; AG route policy, projection summaries,
  and manual dispatch guardrails remain for later S53 slices.

## Implementation

- Extended `AeArtifactOperationsClient` with daemon config/control methods.
- Added matching methods to `HttpAeArtifactOperationsClient`.
- Added in-memory daemon config/control fallbacks for regression tests and
  future AG route work.
- Preserved service-token auth, request id, traceparent, timeout, and
  idempotency-key propagation.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Result:

```text
55 passed
services/nex-ag/nex_ag/artifact_operations.py 99%
```

## Next

Slice 0523 should add a metadata-only AG daemon operations projection on top of
this adapter.
