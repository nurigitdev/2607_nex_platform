# CP-M1-E2E-FX-01B.6A.1 Refresh Contract and Source Resolver

## Status

- Date: `2026-11-17`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6A_EOS_Allocation_to_PnL_Projection_Activation_Boundary_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice:
  `CP-M1-E2E-FX-01B.6A.2: Deterministic Projection Activation Service`

This Slice closes the canonical refresh contract and the EOS-owned source
resolution boundary. It does not activate the route or invoke the Project P&L
projector. Those product mutations, replay semantics, and protected route
wiring remain assigned to `.6A.2`.

## Canonical Protected Contract

The admitted operation is
`FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION` at
`POST /internal/v2/finance/cost-allocation-batches/{batch_id}:refresh-project-pnl`.
It requires a signed service token with `service:call`, trusted tenant,
company, and correlation headers, and exactly one business selector:
`batch_id`. The operation admits no request body or query-provided projection
input.

The canonical response schema and example define the immutable projection
references and exact-replay disposition required from `.6A.2`. The OpenAPI
contract records the write classification, business scope, selector boundary,
and bounded `200`, `201`, `400`, `401`, `404`, `409`, `422`, and `503`
outcomes.

Contract assets:

- `project_pnl_refresh_from_allocation.v1.schema.json`
- `eos_project_pnl_refresh_from_allocation.created.json`
- the canonical EOS OpenAPI operation and schema reference

## EOS Source Authority

`EosAllocationPnlRefreshSourceResolver` first delegates admission to the
existing Allocation reconciliation service. It requires:

- `COMMITTED` commit state;
- `COMMITTED_CONFIRMED` reconciliation;
- `VERIFIED` verification;
- `DO_NOT_RERUN` retry disposition;
- no reversed SourcePool; and
- an exact tenant, company, and Batch identity match.

After admission, the resolver reloads the authoritative Batch, Lines,
SourcePools, and Projects in EOS. It derives period, currency, Plan identity,
reconciliation evidence, commit boundary, and the stable union of allocation
target and source/residual Projects. Project roles and codes are checked
against the exact persisted lineage, and the complete source semantics receive
a domain-separated deterministic hash.

The resolver rejects missing or foreign Batch identity with zero-disclosure
`404`; unverified, reversed, incomplete, or drifted lineage with `409`;
malformed identities with `422`; and persistence failures with retryable
`503`. It performs no insert, update, projection rebuild, outbox transition, or
other financial mutation.

## Composition Boundary

The resolver is composed in the standard EOS dependency graph and exposed on
application state for the next Slice. No route is registered in `.6A.1`.
This makes accidental early activation observable while preserving one
product composition path for `.6A.2`.

The following remain intentionally deferred:

- deterministic projection creation and exact/restart/concurrent replay;
- protected route registration and response materialization;
- strict AE consumer integration; and
- actual PostgreSQL protected smoke and the Checkpoint Gate.

The first two belong to `.6A.2`; the latter two belong to `.6A.3`.

## Verification

- Focused source resolver and contract tests: `25 passed`
- Canonical contract validation:
  `272 schemas`, `320 examples`, `260 negative examples`, `10 OpenAPI`
- EOS Slice Gate: `PASS`, `5/5` commands, `204.5s`
- EOS statement coverage: `96.99%`
- EOS branch coverage: `95.21%`
- New resolver statement coverage: `100.00%`
- New resolver branch coverage: `100.00%`
- Ruff and diff checks: pass
- Evidence:
  `reports/quality/mybee-w70-cp-m1-e2e-fx-01b6a1-eos-slice-gate.json`

The opt-in PostgreSQL suites are not claimed by this Slice. The parent
amendment assigns actual `nex_eos_test` migration, restart, concurrency, and
zero-residue proof to `.6A.3` after `.6A.2` has activated the product route.

## Closure Decision

`CP-M1-E2E-FX-01B.6A.1` is closed. EOS now owns a strict, deterministic,
mutation-free source resolver and a canonical protected contract for
AllocationBatch-bound Project P&L refresh. `.6A.2` may compose the existing
projector and immutable repository from this resolved authority. It may not
accept caller-supplied period, Project, currency, time, version, watermark, or
fallback values.
