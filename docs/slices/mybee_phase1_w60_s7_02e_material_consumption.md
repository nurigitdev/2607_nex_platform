# W60-S7-02E Material Consumption Release and Cost Reconciliation

## Status

- Slice: `W60-S7-02E`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: 2026-11-15
- Owner: NeX-EOS

## Decision

This Slice closes the narrow material lifecycle between purchase-time inventory
commitment and consumption-time Project actual cost without introducing a
warehouse or inventory-valuation system.

The original `eos_material_commitment` and `eos_material_attribution` rows
remain immutable. An approved issue or consumption appends a consumption
header and one or more release lines against exact commitment attributions.
The release reduces only the remaining Project Cost Outlook commitment.

Confirmed actual material cost is never derived from the purchase ASSET line or
from the caller's release amount. It comes only from an already admitted
`PURCHASE + DIRECT + ALLOCATED` expense `eos_cost_source_pool`. The existing
Project P&L direct-cost path therefore remains the sole actual-cost path and
prevents duplicate recognition.

## Persistence

Migration `2547_eos_material_consumption.sql` adds:

- `eos_material_consumption`
  - deterministic issue/consumption identity and exact replay hash;
  - one-to-one linkage to the recognized POSTED expense SourcePool;
  - consuming Project UUID and user-facing Project Code;
  - issue quantity, recognized cost, released carrying value, and explicit
    valuation difference;
  - approval, evidence, policy, period, currency, and reconciliation lineage.
- `eos_material_release`
  - ordered release lines against exact commitment attribution lines;
  - released quantity and acquisition carrying amount;
  - deterministic line hash and cumulative capacity protection.

Both structures are append-only in PostgreSQL. Table, index, trigger, and
constraint names remain below PostgreSQL's identifier limit.

## Admission Invariants

- Consumption requires an existing `PURCHASE` expense SourcePool with
  `DIRECT`, `ALLOCATED`, positive amount, and exact Project identity.
- A SourcePool can be bound to only one consumption event.
- Every released commitment must be `VERIFIED`, use the same material, unit,
  and currency, and have remaining quantity and carrying value.
- A Project-attributed commitment cannot be consumed by another Project or
  work-code target. An explicit `UNASSIGNED` attribution may be released by the
  approved consuming Project.
- Release quantities sum exactly to consumed quantity.
- Cumulative release quantity and carrying value cannot exceed the immutable
  source attribution under concurrent execution.
- POSTED recognized cost may differ from released carrying value; the
  difference is retained as `valuation_variance_functional` rather than
  rewriting acquisition history or adding a second P&L actual component.
- Only `VERIFIED` reconciliation is admitted in this narrow Slice. Missing or
  unverified valuation fails closed.
- Consumption time must be timezone-aware and no later than server observation
  time.
- Stable source replay is idempotent; semantic drift and race ambiguity fail
  closed.

## Project P&L Integration

`SqlAlchemyEosProjectPnlProjectionSource` now loads release facts by acquisition
period and projection `as_of`. `EosProjectPnlProjector` validates release
identity, source presence, reconciliation state, and cumulative conservation.

For a Project attribution:

```text
remaining commitment = attributed acquisition value - verified released value
confirmed actual      = existing POSTED PURCHASE SourcePool cost
```

Partial consumption retains only the remaining `MATERIAL_COMMITTED` component.
Full release removes that commitment component. The release hashes and
remaining amount participate in the material watermark and component semantic
hash, so rebuild and replay converge without editing prior projection rows.

Shared `MANAGEMENT_ALLOCATION`, return, cancellation, transfer, impairment,
scrap, and full FIFO/weighted-average valuation remain later controlled
extensions. This Slice preserves compatible lineage without claiming those
authorities.

The EOS contract catalog version is `mybee-w60-s7-02e`.

## Verification

Focused SQLite regression and branch hardening:

```text
67 passed
material_consumptions.py coverage=98%
```

Protected PostgreSQL smoke against the actual `nex_eos_test` database:

```text
1 passed
```

The smoke created an isolated schema, applied migration `2547`, admitted an
immutable commitment and a pre-admitted direct material cost SourcePool,
verified exact replay, Project P&L transition from `4000.0000` commitment to
`3000.0000` remaining commitment plus `1100.0000` POSTED direct material cost,
proved append-only trigger enforcement, and removed the schema with zero
residue.

Final NeX-EOS Slice Gate:

```text
2201 passed, 63 skipped
statement_coverage=96.98% (threshold 95.00%)
branch_coverage=95.26% (threshold 94.00%)
contract_validation=pass
golden_journey_transition_audit=pass
demo_product_dependency_audit=pass
tiered_quality_gate=pass
```

Evidence: `reports/quality/mybee_phase1_w60_s7_02e_slice_gate.json`.

The pre-existing non-blocking Starlette/httpx deprecation warning remains.
