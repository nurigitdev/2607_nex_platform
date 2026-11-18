# CP-M1-E2E-FX-01B.6B.5A.3A.3 Replay, Failure, and Compatibility Gate

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_3A_Advisory_Product_Planning_Proposal_and_Deterministic_Execution_Boundary_v1.0.md`
- Database migration: none
- Remote provider: not required; live acceptance remains deferred to
  `CP-M1-E2E-FX-01B.7`
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.4`

## Replay Boundary

The public Product planning router now checks the existing durable Product
preparation before calling the provider PLAN stage. An exact started
checkpoint returns its stored proposal or fallback reference and does not
recall the provider. Restart and approval-event redelivery therefore reuse the
same Product lineage instead of generating a second advisory proposal.

Only bounded references are replayed:

- admitted proposal hash and private candidate reference; or
- the exact named deterministic fallback reference admitted by the immutable
  Product planning policy.

A changed proposal, changed fallback, ambiguous proposal-plus-fallback
selection, malformed persisted reference, or an already-advanced begin
checkpoint fails closed.

## Failure Policy

- `DETERMINISTIC_ONLY` never invokes provider PLAN and rejects proposal or
  fallback injection.
- `PROVIDER_ASSISTED_REQUIRED` fails closed when the provider or admitted
  proposal is unavailable.
- `PROVIDER_ASSISTED_OPTIONAL` uses only its registered named fallback and only
  for explicit retryable provider-unavailability errors.
- malformed provider output, low confidence, private-data injection,
  authority-bearing output, and lineage drift never trigger silent fallback.
- provider proposals remain advisory; the deterministic Product materializer
  is the sole execution authority.

No new queue, worker, executor, table, migration, or public API field was
introduced.

## Compatibility

- ordinary IA semantic admission remains unchanged;
- claimed-work delegation and non-Product planning retain the existing PLAN
  flow;
- legacy Product runtimes without replay lookup remain compatible and return
  no replay candidate;
- existing generalized wait/event, WorkResult, NSL, approval resume, and
  deterministic scheduling mechanics remain intact.

## Verification

- focused replay/failure tests: `68 passed`
- adjacent `01B.6B` regression: `212 passed`, `4 skipped`
- AE Slice Gate: `6744 passed`, `51 skipped`
  - statement coverage: `96.38%`
  - branch coverage: `94.64%`
  - commands: `6/6`
- active product coverage: statement `97.01%`, branch `94.94%`
- targeted module coverage:
  - `m1_product_preparation_coordinator.py`: `97%` in focused testing and
    `100%` in the full AE gate
  - `product_planning_runtime.py`: `100%`
- contract validation: `274` schemas, `320` examples, `260` negative examples,
  `10` OpenAPI documents
- Golden Journey transition, demo/product dependency, and AE ownership audits:
  PASS
- lint, compile, and diff checks: PASS
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a3a3-ae-slice-gate.json`
  - `reports/coverage/mybee-w70-cp-m1-01b6b5a3a3-ae-slice-gate.report_ae_coverage_ownership.json`

## Closure

`CP-M1-E2E-FX-01B.6B.5A.3A.3` is closed. Product planning now has a
fail-closed, replay-safe provider proposal boundary while deterministic Product
authority and all non-Product runtime behavior remain unchanged.
