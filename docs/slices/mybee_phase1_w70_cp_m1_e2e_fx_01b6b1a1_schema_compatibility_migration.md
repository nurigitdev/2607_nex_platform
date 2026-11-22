# CP-M1-E2E-FX-01B.6B.1A.1 Schema Compatibility Migration

## Status

- Date: `2026-11-17`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: `2517_ae_product_preparation_resume`
- Actual database: `nex_ae_test`
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.1A.2`

## Implemented Boundary

Migration `2517` generalizes the existing AE resume persistence without
introducing a second wait, inbox, queue, daemon, or Product-specific worker.

- `ae_wait_registration` gains `resume_target_kind` and
  `wait_contract_ref`.
- `ae_external_event_inbox` gains `event_family` and admits the two Product
  Preparation approval event types.
- existing WorkResult and NSL rows are backfilled as executable-step resume
  records;
- existing WorkResult and NSL writers remain compatible through bounded
  insert-time projections;
- Product Preparation adds only immutable
  `ae_product_prep_checkpoint`, `ae_product_prep_wait_binding`, and
  `ae_product_prep_event_binding` structures;
- Product waits and events require their typed binding through deferred
  constraints;
- checkpoint versions are append-only, hash-bound, and linked to the exact
  WorkIntent, AgentContext, capability, coordinator, and source identities.

The compatibility projections infer values only from existing admitted event
and wait types. Product Preparation still requires explicit
`PRODUCT_COORDINATOR` / `PRODUCT_PREPARATION` values and a valid typed
binding.

## Compatibility Defect Found and Closed

The first actual PostgreSQL compatibility run found that legacy WorkResult and
NSL repositories did not yet write the new non-null projection columns. The
database correctly rejected those inserts. Migration `2517` was hardened with
two narrow `BEFORE INSERT` projection triggers and the same protected tests
then passed.

This is a migration compatibility bridge, not a second runtime path. Runtime
routing remains unchanged in this Slice and Product Preparation remains
`CONTRACT_ONLY`.

## Verification

- migration contract tests: `7 passed`
- default protected-test behavior: `7 passed, 1 skipped`
- actual Product Preparation PostgreSQL smoke: `1 passed`
- actual WorkResult, NSL wait/event, and Product Preparation PostgreSQL
  compatibility matrix: `24 passed`
- related legacy focused regression: `65 passed, 2 skipped`
- rollback residue in checkpoint, wait, and event tables: `0 / 0 / 0`
- AE Slice Gate: `6538 passed, 48 skipped`
- AE statement coverage: `96.45%` (threshold `95.00%`)
- AE branch coverage: `94.65%` (threshold `94.00%`)
- contract validation: `PASS`
- AE coverage ownership: `PASS`

Machine-readable Gate evidence:

```text
reports/quality/
mybee-w70-cp-m1-e2e-fx-01b6b1a1-ae-slice-gate.json
```

## Remaining Boundary

This Slice does not generalize the runtime handler. `RESUME_EXECUTION` still
uses the existing executable-step behavior. The next Slice must introduce the
generic wait/event persistence API and typed Product Preparation repository
surface while preserving the schema and compatibility constraints closed
here.
