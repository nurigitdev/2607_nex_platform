# CP-M1-E2E-FX-01B.7G: AE Product Resume Worker Lease Budget Hardening

## Status

- Date: `2026-11-19`
- Status: `LIVE_BLOCKED`; source and regression boundary passed, protected live
  rerun exposed a missing Product RuntimeJob settlement boundary
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Public API or RuntimeJob schema change: none
- Remote provider: required only for the final installed journey

## Failure Reconciliation

The protected `.7F` journey proved the complete authority receipt path before
the resumed Product execution:

- WC `BUSINESS_FORMAL` approval reached `APPROVED`;
- the WC approval outbox reached `DELIVERED`;
- EOS document signoff reached `APPROVED` and persisted one evidence record
  and one immutable envelope;
- AE matched the generalized Product wait and enqueued the existing
  `RESUME_EXECUTION` RuntimeJob.

The remaining execution did not fail at an authority, event, or provider
boundary. The installed AE worker inherited the general 60-second RuntimeJob
lease while synchronous Product resume work can include the admitted
Qwen3.5-9B semantic planning path. Runtime evidence showed four consecutive
`LEASE_EXPIRED` attempts followed by a fifth running attempt. Continuing that
run would have created repeated work without distinguishing Product behavior
from an undersized installed lease budget, so the journey was stopped and all
eight isolated database schemas and Compose resources were removed.

## Decision

- Preserve the general AE worker default lease of 60 seconds for development
  and non-installed profiles.
- Set the canonical installed Product worker lease to 600 seconds through
  `NEX_AE_AGENT_WORKER_LEASE_SECONDS`.
- Keep the existing bounded configuration maximum of 3,600 seconds.
- Preserve synchronous planning and the existing RuntimeJob claim, retry,
  heartbeat, and completion semantics.
- Do not add lease renewal, a new queue, an asynchronous ACK path, a database
  migration, or a scenario-specific branch in this Slice.

The 600-second value aligns the installed AE Product worker with the already
admitted WC handoff lease budget and provides bounded margin for the known
three-stage synchronous semantic path. It is an installed runtime policy, not
a claim that every Product operation should consume the full interval.

## Implementation

- Canonical Compose explicitly binds the AE Agent Runtime worker to a
  600-second lease.
- Source and rendered-Compose admission reject a missing or drifted installed
  lease.
- The Product runtime deployment audit rejects any value other than the
  admitted 600-second policy.
- The current background-process manifest declares the lease environment
  variable as part of the packaged AE worker contract.
- Worker startup/readiness evidence exposes the effective `lease_seconds`
  value so operators can verify the active budget without inspecting secrets
  or process internals.
- Regression tests preserve the 60-second library default, prove custom
  configuration propagation, admit the 600-second installed profile, and
  reject a 60-second canonical drift.

## Verification

- Ruff and diff checks: `PASS`
- focused worker, Compose, process-manifest, installed-configuration, and
  deployment-audit regression: `104 passed`
- Product runtime deployment audit: `PASS`; no fixture runtime use or lease
  policy drift
- canonical Compose source admission: `PASS`
- actual Docker Compose render admission: `PASS`
  - services: `18`
  - immutable images: `9`
  - secrets in evidence: none
- AE Slice Gate: `6884 passed`, `52` protected skips, commands `6/6`
  - statement coverage: `96.45%`
  - branch coverage: `94.71%`
  - active Product coverage: statement `97.07%`, branch `95.00%`
  - report:
    `reports/quality/mybee-w70-cp-m1-01b7g-ae-slice-gate.coverage.json`

## Protected Live Result

The exact-head protected journey ran on an idle DGX window with the actual
eight PostgreSQL databases, installed Compose topology, signed trust, and live
generation, embedding, and reranking providers.

- the installed AE worker reported `lease_seconds=600`;
- the Product `RESUME_EXECUTION` claim received the expected 600-second lease;
- all six observed generation requests returned HTTP 200;
- the authority receipt was matched, the Product wait reached
  `RESUME_QUEUED`, and AgentPlan/ExecutablePlan persistence was observed;
- no Product assignment path completed the claimed RuntimeJob;
- at exactly 600 seconds attempt 1 became `LEASE_EXPIRED` and attempt 2 was
  claimed;
- the run was intentionally interrupted before duplicate work could continue;
- all Compose resources and all eight isolated database schemas were removed.

Source reconciliation confirmed that
`InstalledProductCoordinatorAssignmentHandler` resumes and activates the
Product coordinator but never calls `SqlAlchemyRuntimeJobQueue.complete()` or
`fail()`. The generic worker lifecycle only emits heartbeat state and explicitly
leaves lease settlement to the RuntimeJob authority. The installed 600-second
policy therefore exposed, rather than caused, the missing settlement boundary.

The next corrective boundary must add lease-token-fenced success and failure
settlement for Product coordinator assignments, including retryable failure,
stale lease, replay, restart, and ACK-loss coverage. Increasing the lease again
or rerunning the same journey cannot close this defect.

## Protected Live Rule

The exact-head installed rerun must prove:

1. worker startup/readiness reports `lease_seconds=600`;
2. the resumed Product RuntimeJob receives a 600-second lease;
3. the job does not create lease-expiry retry attempts during the admitted
   semantic planning and controlled WRITE path;
4. authority receipt replay and restart remain idempotent;
5. the IA result is published and the journey reaches its terminal success;
6. all isolated database schemas and Compose resources are removed.

This Slice closes only the configuration, admission, and regression boundary.
The protected live acceptance and parent `.7` journey remain blocked until the
Product RuntimeJob settlement corrective boundary is implemented and the same
journey passes without a lease-expiry retry.
