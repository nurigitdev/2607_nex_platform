# CP-M1-E2E-FX-01B.6B.2 Durable Preparation and Approval Resume

## Status

- Date: `2026-11-17`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: none; migration `2517` is reused
- Actual database: `nex_ae_test`
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.3`

## Implemented Boundary

This Slice connects the registered M1 Product Coordinator contract to the
existing proposal and VoucherCandidate preparation adapter without adding a
Product-specific queue, worker, or inbox.

- `InstalledM1ProductPlanningCoordinator` validates exact WorkIntent,
  AgentContext, AgentExecution, capability snapshot, coordinator registration,
  and business-context lineage before any provider-side mutation.
- `begin()` resolves fresh owner authority, invokes the existing proposal
  preparation adapter, appends the first immutable Product Preparation
  checkpoint, and registers the corresponding shared wait envelope.
- approval notifications are persisted as bounded Product events and typed
  bindings. They carry references and evidence identifiers, not raw business
  prompt content.
- `resume_approval()` accepts only events already matched by the shared runtime
  matcher and queued through the existing `RESUME_EXECUTION` RuntimeJob path.
  A direct Product-specific resume bypass is rejected.
- business approval advances to `WAITING_ACCOUNTING_APPROVAL`; accounting
  approval advances to `READY_FOR_D04` through the existing adapter.
- fresh authority is resolved again at each approval boundary.
- exact begin replay, notification replay, and approval ACK-loss replay return
  the existing durable result without duplicate proposal or VoucherCandidate
  mutation.
- stale, out-of-order, cross-lineage, malformed, and semantically drifted
  requests fail closed.
- deterministic UUIDs and semantic hashes bind every checkpoint and wait to
  tenant, execution, coordinator, capability, and prior-checkpoint lineage.

M1 remains `CONTRACT_ONLY` in the global Product Coordinator Registry. This
Slice completes the product service used by the generic handler; installed
composition and process activation remain assigned to `6B.5`.

## Compatibility And Ownership

1. The shared generalized wait/event persistence and `RESUME_EXECUTION`
   mechanics remain the only runtime resume path.
2. Existing WorkResult and NSL approval behavior is unchanged.
3. No migration, queue, daemon, worker, public API, or remote-provider call is
   introduced.
4. The AE-to-MyBee runtime ownership inventory now explicitly admits the new
   coordinator module. Its fail-closed audit remains active.
5. `READY_FOR_D04` materialization, AgentPlan persistence, and scheduling are
   not performed here; they remain the `6B.3` boundary.

## Verification

- focused coordinator behavior and branch coverage: `24 passed`
- new coordinator module: statement `100%`, branch `100%`
- focused M1 preparation/resume and VoucherCandidate regression:
  `305 passed, 6 skipped`
- actual `nex_ae_test` shared persistence/restart smoke: `3 passed`
- PostgreSQL rollback residue for the Slice tenant namespace: `0`
- runtime ownership audit after canonical inventory reconciliation:
  `13 passed`
- AE Slice Gate: `6618 passed, 50 skipped`
- AE statement coverage: `96.43%` (threshold `95.00%`)
- AE branch coverage: `94.70%` (threshold `94.00%`)
- AE product ownership coverage: statement `97.07%`
- contract validation: `PASS`
- golden-journey transition audit: `PASS`
- demo/product dependency audit: `PASS`
- AE coverage ownership: `PASS`, active graph `96`, conflicts `0`

Machine-readable Gate evidence:

```text
reports/quality/
mybee-w70-cp-m1-e2e-fx-01b6b2-ae-slice-gate.json
```

## Closure Decision

`CP-M1-E2E-FX-01B.6B.2` is implementation-closed. The two owner-authoritative
M1 approval waits are now represented by immutable Product Preparation
checkpoints and resumed only through the generalized runtime event path.

The next Slice is `CP-M1-E2E-FX-01B.6B.3: READY_FOR_D04 Plan Persistence and
Scheduling`. It may invoke the existing `.5` materializer only after the
durable `READY_FOR_D04` checkpoint and must reuse the existing AgentPlan,
PlanValidation, ExecutablePlan, and scheduler stores.
