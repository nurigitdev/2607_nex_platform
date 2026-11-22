# W60-S7-02D Material Commitment and Inventory Attribution Foundation

## Status

- Slice: `W60-S7-02D`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: 2026-11-14
- Owner: NeX-EOS

## Decision

Material purchase or receipt remains a balance-sheet inventory event. It must
not enter `eos_cost_source_pool` merely to make it visible to Project P&L.
Instead, this Slice adds an append-only material commitment ledger that links
an exact POSTED, non-monetary ASSET Journal line to:

1. one or more Project-attributed inventory amounts; and
2. one explicit `UNASSIGNED` inventory remainder when the target is not yet
   known.

Only Project-attributed lines appear in a Project P&L projection as
`MATERIAL_COMMITTED`. They are non-confirmed commitment components and do not
change posted revenue, direct cost, allocated cost, or operating result.
Company-level unassigned inventory is retained in the commitment ledger and is
not assigned to an arbitrary Project.

Consumption, issue, return, valuation adjustment, commitment release, and
actual material-cost recognition remain a later Slice. Those transitions must
be represented by new append-only events rather than mutation of the records
introduced here.

## Persistence

Migration `2546_eos_material_commitment.sql` adds:

- `eos_material_commitment`
  - exact Journal and Journal-line lineage;
  - material, lot, quantity, functional amount, evidence, approval, policy,
    and reconciliation lineage;
  - assigned and unassigned quantity/value conservation totals;
  - deterministic source identity and semantic hash.
- `eos_material_attribution`
  - ordered `PROJECT` or `UNASSIGNED` attribution lines;
  - Project UUID plus user-facing Project Code for Project lines;
  - optional FL work code and approved attribution basis;
  - immutable line hash.

Both tables reject UPDATE and DELETE in PostgreSQL. Table and constraint names
remain below the PostgreSQL identifier limit.

## Admission Invariants

- Source Journal must exist and be `POSTED`.
- Source line must be a positive debit on a non-monetary `ASSET` account.
- Company account policy must be approved and effective on recognition date.
- Multiple acquisition components may reference one Journal line, but their
  combined amount cannot exceed its positive functional debit.
- Every Project target must be `ACTIVE` or `CLOSING`, have the exact canonical
  Project Code, and have an effective approved company binding.
- Attributed quantity equals acquired quantity exactly.
- Attributed functional amount equals acquisition functional amount exactly.
- At most one `UNASSIGNED` line is accepted and it cannot carry Project or work
  identity.
- The same source identity is exact-replay safe; semantic drift is rejected.

## Runtime Integration

- `EosMaterialCommitmentService` is composed in the canonical EOS dependency
  graph and exposed through application state for later API and worker slices.
- `SqlAlchemyEosProjectPnlProjectionSource` loads commitment facts by period
  and as-of time.
- `EosProjectPnlProjector` emits only the requesting Project's attributed
  commitment lines and records a deterministic
  `material_commitment_watermark`.
- `PENDING` and `BLOCKED` material reconciliation states propagate to the
  Project P&L reconciliation status.
- EOS contract catalog version is `mybee-w60-s7-02d`.

## Verification

Focused SQLite regression:

```text
25 passed
```

Protected PostgreSQL smoke against `nex_eos_test`:

```text
1 passed
```

The smoke test verified actual migration through `2546`, DB identity,
POSTED-ASSET admission, Project and unassigned conservation, exact replay,
Project P&L commitment projection, zero posted-cost impact, append-only trigger
enforcement, and temporary-schema zero residue.

Final NeX-EOS Slice Gate:

```text
2168 passed, 62 skipped
statement_coverage=96.95% (threshold 95.00%)
branch_coverage=95.23% (threshold 94.00%)
contract_validation=pass
golden_journey_transition_audit=pass
demo_product_dependency_audit=pass
tiered_quality_gate=pass
```

Evidence: `reports/quality/mybee_phase1_w60_s7_02d_slice_gate.json`.

The remaining warning is the pre-existing non-blocking Starlette/httpx
deprecation warning.
