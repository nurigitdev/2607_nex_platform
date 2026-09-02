# Slice 0524: AG Scheduler Daemon Operations Route

## Scope

Expose the AG scheduler daemon operations projection through a protected AG
operator route.

## Decision

- `GET /admin/v1/operations/artifact-retention/scheduler-daemon` is the AG
  read-only operator surface for AE scheduler daemon posture.
- The route calls AE's daemon config API through the AG AE-client adapter and
  returns the metadata-only projection added in Slice 0523.
- AG still does not write AE persistence, acquire leases, enqueue JobQueue
  rows, or start a daemon loop.
- Manual dispatch remains intentionally out of scope for this slice and is kept
  for a separate guardrail slice.

## Implementation

- Added the protected AG scheduler daemon operations route.
- Preserved AG service-token authorization and optional `service_id` filtering.
- Propagated request id and trace context to the AE source client.
- Added route regression coverage for success, valid service filtering,
  unauthorized access, invalid service filters, and AE source failures.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Result:

```text
59 passed
services/nex-ag/nex_ag/artifact_operations.py 99%
```

## Next

Slice 0525 should add the protected manual tick-once dispatch route with
operator confirmation and strict no-start-daemon guardrails.
