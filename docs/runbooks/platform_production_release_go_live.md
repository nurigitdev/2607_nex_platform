# Platform Production Release and Go-live Runbook

## Supported Topology

This runbook applies only to NeX Platform v1.0 on one managed Docker Compose
host with OA, AE API/Web, CX, MO, AG, workers/daemons, Traefik, OpenBao, RustFS,
five service-owned PostgreSQL databases, and three remote provider
capabilities. It does not authorize distributed-topology claims.

## Evidence Preparation

1. Build and inspect the complete six-image OCI release set without pushing it.
2. Run the S149 target workload, under-load fault/recovery acceptance, evidence
   admission, and closure for that exact release set.
3. Run Full Gate and confirm statement coverage is at least 95 percent and
   branch coverage is at least 94 percent.
4. Generate the S150 manifest and freshness admission. Never edit evidence
   JSON manually.

## Immediate Preflight

Run `run_s150_immediate_preflight.py --execute` only with the `test` profile,
all five test database URLs, the three DGX provider settings, live MO provider
and observability modes, and explicit activation. The accepted report must show
five databases, three providers, generation reasoning disabled, mock incident
delivery, and zero residue. It expires after four hours.

## Cutover And Rollback

Run `run_s150_cutover_rollback_rehearsal.py` after a fresh preflight. Confirm
all six cutover phases and six rollback components, exact last-known-good
restoration, committed-data preservation, recovery within five minutes, and
zero residue. This is a dry-run control exercise and performs no cutover.

## Decision Evaluation

Run `run_s150_release_decision.py`, then
`run_s150_protected_acceptance.py --execute`. Inspect all ten named gates and
the exact release candidate/digest. The only valid outcomes are `GO` and
`NO_GO`; successful evaluation does not imply `GO`.

## GO Procedure

A `GO` requires all ten gates to pass, including a valid external-notification
P1 waiver or activated protected delivery evidence, all four human approvals,
and an active change window. Record authorization metadata, then hand off to a
separately invoked human deployment procedure. S150 never runs that procedure.

## NO_GO Procedure

Keep the release immutable and do not deploy. For the current candidate:

1. Create a named, time-bounded waiver document at
   `reports/deployment/s150-p1-waivers.json` with distinct owner and approver,
   compensating control, rollback trigger, expiry, and review cadence.
2. Create `reports/deployment/s150-release-approvals.json` with the release
   manager, operations owner, security owner, data owner, and active change
   window. The deployment actor must differ from the release manager.
3. Re-run risk governance, approval governance, immediate preflight if expired,
   cutover/rollback rehearsal, decision evaluation, protected acceptance, Full
   Gate, and closure in that order.

## Failure Triage

- Identity or digest drift: stop and rebuild/re-admit the release candidate.
- Stale evidence: rerun only the owning protected boundary; do not change its
  timestamp manually.
- P0 open: stop. P0 risk is not waivable.
- P1 or approval failure: retain `NO_GO` until governance evidence is valid.
- Provider/model drift: stop at MO readiness/calibration and do not promote.
- Residue: quarantine the candidate and clean the owning test resource before
  any rerun.

## Cleanup And Zero Residue

Confirm temporary database rows, RustFS objects/versions, jobs, leases,
processes, route overrides, provider rehearsal records, Compose projects, and
volumes are zero. Protected reports contain only metadata and digests.

## Distributed Backlog

Multi-node service failover, PostgreSQL automatic failover, object-store node
loss, GPU autoscaling/failover, and external dead-man monitoring remain
`NOT_APPLICABLE_SINGLE_HOST` backlog. Do not report them as v1.0 passes.

## Deployment Separation

Every S150 runner sets production deployment approval to false and issues no
deployment command. A future valid `GO` is authorization metadata only. The
deployment actor must execute a separately reviewed procedure inside the
approved change window, with the rollback deadline and last-known-good release
available.
