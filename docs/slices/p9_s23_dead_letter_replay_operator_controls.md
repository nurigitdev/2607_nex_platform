# P9-S23: Dead-Letter, Replay, and Operator Controls

## Scope

NeX-WA now exposes the shared Platform Job control surface when durable WA
persistence is configured:

```text
GET  /internal/v1/jobs/{job_id}
POST /internal/v1/jobs/{job_id}/cancel
POST /internal/v1/jobs/{job_id}/retry
POST /internal/v1/jobs/{job_id}/replay
```

The implementation reuses `nex_runtime.JobQueue`, retry/dead-letter policy,
and `job_replay_lineage.v1`. Replay is permitted only for a terminal
dead-letter, requires an operator identity and reason, and creates a new Job
identity while leaving the original failed Job immutable. No WA-specific queue
or table was added.

Operator projections omit the Job payload and redact private error detail.
The replay response exposes only bounded source status/error code and explicit
operator lineage. When persistence is absent, the control routes are not
installed, avoiding a misleading non-durable surface.

## Verification

- attempt exhaustion and dead-letter behavior
- replay with new Job identity and immutable original
- operator identity/reason requirement
- service-claim protection
- payload and error-detail privacy
- canonical OpenAPI and contract validation
- NeX-WA Slice Gate

Results:

- focused WA/shared-control regression: `17 passed`
- NeX-WA Slice Gate: `269 passed, 9 skipped`
- statement coverage: `97.30%`
- branch coverage: `94.88%`
- shared Job control module statement/branch coverage: `100% / 100%`
- contract validation: `226` schemas, `290` examples, `241` negative
  examples, and `10` OpenAPI documents
