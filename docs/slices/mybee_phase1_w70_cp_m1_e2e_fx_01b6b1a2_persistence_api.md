# CP-M1-E2E-FX-01B.6B.1A.2 Persistence API and Typed Binding Repository

## Status

- Date: `2026-11-17`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: none; reuses `2517_ae_product_preparation_resume`
- Actual database: `nex_ae_test`
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.1A.3`

## Implemented Boundary

This Slice adds the source-backed repository surface for the generalized
wait/event schema introduced by `6B.1A.1`. It does not introduce a second
inbox, queue, daemon, or Product-specific worker.

- `SqlAlchemyProductPreparationCheckpointRepository` provides append, exact
  replay, point read, and latest-version read for immutable Product
  Preparation checkpoints.
- `SqlAlchemyGeneralizedWaitEventRepository` registers shared wait envelopes,
  accepts shared external events, and loads their typed Product Preparation
  resume contexts.
- Product waits and events persist their typed binding atomically with the
  shared envelope.
- checkpoint, wait binding, and event binding are sealed with canonical
  SHA-256 semantic hashes.
- exact replay returns the original projection; changed replay fails closed
  without mutation.
- existing `WORK_RESULT` and `NSL_APPROVAL` envelopes remain admitted with
  their previous executable-step semantics.
- Product bindings cannot be attached to legacy envelopes, and Product
  resume context loading rejects missing, mixed-family, or incomplete
  lineage.
- malformed JSON and scalar validation failures are normalized to the AE
  persistence domain error contract.

M1 remains `CONTRACT_ONLY`. Runtime event routing, wait satisfaction,
`RESUME_EXECUTION` scheduling, and Product Coordinator activation are not
implemented in this Slice.

## Persistence and Replay Invariants

1. Checkpoint history is append-only and hash-bound to WorkIntent,
   AgentContext, capability, coordinator, and source identities.
2. Product wait/event typed bindings and their shared envelopes commit in one
   transaction.
3. Exact replays ignore timestamp-only differences but reject any semantic
   drift.
4. Legacy WorkResult and NSL persistence contracts remain compatible.
5. Cross-family binding, authority, notification, checkpoint, or execution
   drift fails closed.
6. No new table, migration, queue, or worker is introduced.

## Verification

- focused persistence and ownership regression: `39 passed`
- persistence unit tests: `32 passed`
- existing/new actual PostgreSQL compatibility matrix: `25 passed`
- final actual `nex_ae_test` checkpoint plus repository smoke: `2 passed`
- PostgreSQL rollback residue across checkpoint, wait, and event rows: `0`
- AE Slice Gate: `6570 passed, 49 skipped`
- AE statement coverage: `96.39%` (threshold `95.00%`)
- AE branch coverage: `94.64%` (threshold `94.00%`)
- new persistence module statement coverage: `91.90%`
- new persistence module branch coverage: `93.86%`
- contract validation: `PASS`
- AE coverage ownership: `PASS`, `185` modules, `0` conflicts

Machine-readable Gate evidence:

```text
reports/quality/
mybee-w70-cp-m1-e2e-fx-01b6b1a2-ae-slice-gate.json
```

## Remaining Boundary

`6B.1A.3` may generalize runtime event matching, wait satisfaction, and
resume-handler routing over this repository. It must keep one shared runtime
primitive, preserve the existing WorkResult/NSL behavior, and add Product
Coordinator routing without activating M1 business orchestration early.
