# CP-M1-E2E-FX-01B.6B.3 READY_FOR_D04 Plan Persistence and Scheduling

## Status

- Date: `2026-11-17`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: none; existing AgentPlan, PlanValidation, ExecutablePlan, and RuntimeJob stores are reused
- Actual database: `nex_ae_test` shared persistence/restart smoke
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.4`

## Implemented Boundary

This Slice activates the existing deterministic M1 plan materializer only
after the durable Product Preparation state has reached the exact
`READY_FOR_D04` checkpoint.

- `InstalledM1ProductPlanningCoordinator.load_ready_checkpoint()` reloads the
  latest immutable checkpoint, validates the complete WorkIntent,
  AgentContext, AgentExecution, capability, coordinator, and business-context
  lineage, and rejects every non-READY state without mutation.
- `InstalledM1PlanActivation` invokes the existing `.5` transaction-plan
  materializer and accepts only its deterministic D12 then D04 plan lineage.
- the materialized AgentPlan, PlanValidation, and ExecutablePlan are persisted
  in that order through their existing repositories.
- the existing scheduler is called only after all three authoritative plan
  records have been persisted or exactly replayed.
- provider PLAN output remains non-authoritative evidence. It is not promoted
  into executable financial authority by this activation boundary.
- exact replay returns the existing plan lineage and lets the existing
  scheduler deduplicate RuntimeJob creation.
- semantic drift in any persisted plan record, invalid execution version,
  stale checkpoint, registration mismatch, or materializer lineage mismatch
  fails closed before scheduling.
- crash recovery is supported after each persistence boundary by exact replay
  of the immutable repositories; no Slice-local recovery state is introduced.

## Compatibility And Ownership

1. No generic compiler, scheduler, dispatcher, or worker receives an M1-only
   branch.
2. No migration, queue, daemon, worker, inbox, public API, or model-provider
   dependency is added.
3. Existing WorkResult, NSL approval, generalized wait/event, and
   `RESUME_EXECUTION` behavior remains unchanged.
4. M1 remains globally `CONTRACT_ONLY`; installed product composition and
   process activation remain assigned to `6B.5`.
5. The actual multi-service PostgreSQL activation, replay, restart, and
   approval ACK-loss protected Gate remains the canonical `6B.4` boundary.

## Verification

- focused 6B.3 activation behavior: `37 passed`
- new activation module: statement `100%`, branch `100%`
- focused 6B.2 and 6B.3 coverage regression: `61 passed`
- M1 plan and runtime repository regression: `269 passed`
- actual `nex_ae_test` shared persistence/restart smoke: `3 passed`
- PostgreSQL rollback residue for the Slice tenant namespace: `0`
- AE Slice Gate: `6655 passed, 50 skipped`
- AE statement coverage: `96.44%` (threshold `95.00%`)
- AE branch coverage: `94.71%` (threshold `94.00%`)
- AE product ownership coverage: statement `97.08%`, branch `95.01%`
- contract validation: `PASS`
- golden-journey transition audit: `PASS`
- demo/product dependency audit: `PASS`
- AE coverage ownership: `PASS`, active graph `96`, conflicts `0`

Machine-readable Gate evidence:

```text
reports/quality/
mybee-w70-cp-m1-e2e-fx-01b6b3-ae-slice-gate.json
```

## Closure Decision

`CP-M1-E2E-FX-01B.6B.3` is implementation-closed. A durable
`READY_FOR_D04` checkpoint now produces and persists one deterministic plan
lineage before the existing scheduler may create executable work.

The next Slice is `CP-M1-E2E-FX-01B.6B.4`. It must prove the installed
PostgreSQL replay, restart, approval ACK-loss, scheduling, and zero-residue
boundary without introducing fixture-derived business authority.
