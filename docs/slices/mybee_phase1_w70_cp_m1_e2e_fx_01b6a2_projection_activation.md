# CP-M1-E2E-FX-01B.6A.2 Deterministic Projection Activation Service

## Status

- Date: `2026-11-17`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6A_EOS_Allocation_to_PnL_Projection_Activation_Boundary_v1.0.md`
- Predecessor: `CP-M1-E2E-FX-01B.6A.1`
- Database migration: none
- Remote provider: not required
- Next Slice:
  `CP-M1-E2E-FX-01B.6A.3: Strict Consumer And Protected Gate`

This Slice activates the EOS-owned product path from a verified
AllocationBatch to immutable Project P&L projections. It composes the source
resolver, the existing projector, and the existing immutable repository. It
does not add a receipt table, duplicate P&L formulas, expose projection
components, or grant Project P&L read authority.

## Deterministic Activation

`EosProjectPnlRefreshService` resolves the verified allocation source and
builds a stable refresh plan for every target and source/residual Project. For
each Project it derives the request from EOS authority only:

- tenant, company, Batch, period, and functional currency;
- Project UUID and approved Project Code;
- Batch `committed_at` as both projection `as_of` and deterministic evaluation
  boundary; and
- the next immutable projection version, or the exact existing boundary
  version on replay.

The existing `EosProjectPnlProjector.preview()` performs the same source load
and calculation as `rebuild()` without persistence. The service previews all
affected Projects before the first append. A PARTIAL, BLOCKED, PENDING, STALE,
drifted, ambiguous, or out-of-order result therefore fails before predictable
partial mutation.

The existing repository now supports a bounded exact-`as_of` lookup. This is
not a latest-row fallback: zero rows means a new next revision may be created,
one exact row is verified by deterministic projection ID and hash, and two
rows at the same boundary are an ordering conflict.

## Replay And Concurrency

The first successful activation appends one immutable next revision per
affected Project and returns `201 CREATED`. Exact replay, including a new
service instance over the same persistence, validates the stored projection
against a newly previewed hash and returns `200 EXACT_REPLAY` with the same
projection IDs, versions, hashes, and `refresh_hash`.

If concurrent callers select the same next version, the existing unique
constraints choose one persisted result. The losing caller reloads the exact
boundary and succeeds only when exactly one projection with the expected ID
and hash is visible. Otherwise it fails closed. A later projection without an
exact historical result blocks an older refresh rather than returning the
latest row.

The response `refresh_hash` excludes only the transport disposition, so
creation and exact replay preserve one semantic receipt.

## Protected Route

The canonical route is now active:

```text
POST /internal/v2/finance/cost-allocation-batches/{batch_id}:refresh-project-pnl
Operation: FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION
```

It requires a service token for the `nex-eos` audience with `service:call`, a
trusted tenant/company/correlation header set, and a WRITE route admission.
Any request body or query parameter is rejected. Success and all problem
responses carry `Cache-Control: no-store` and `Pragma: no-cache`.

Dependency composition is fail closed: the route is always registered, while
the service is available only when resolver, projector, and repository are all
configured.

## Verification

- Focused activation, resolver, repository, projector, and route regression:
  `122 passed`
- Broader Project P&L and Cost Allocation regression: `200 passed`
- New refresh service/API statement coverage: `100.00%`
- New refresh service/API branch coverage: `100.00%`
- EOS Slice Gate: `PASS`, `5/5` commands, `202.798s`
  - EOS regression: `2297 passed`, `66 skipped`
  - statement coverage: `97.00%`
  - branch coverage: `95.25%`
- Contract validation:
  `272 schemas`, `320 examples`, `260 negative examples`, `10 OpenAPI`
- Golden journey transition audit: pass
- Demo/product dependency audit: pass
- Ruff, compile, and diff checks: pass
- Evidence:
  `reports/quality/mybee-w70-cp-m1-e2e-fx-01b6a2-eos-slice-gate.json`

The skipped PostgreSQL suites are existing opt-in tests. This Slice proves the
activation algorithm and product composition with the repository contract,
but does not claim actual PostgreSQL restart or concurrent transaction
evidence. Those tests, the strict AE consumer, isolated schema cleanup, and
Checkpoint Gate remain assigned to `.6A.3`.

## Closure Decision

`CP-M1-E2E-FX-01B.6A.2` is closed. EOS now exposes one protected product route
that deterministically activates verified AllocationBatch state into immutable
Project P&L revisions and converges exact replay without new persistence.

`CP-M1-E2E-FX-01B.6A.3` may now add the strict provider-neutral consumer and
prove the complete creation, replay, restart, concurrency, cross-scope, and
zero-mutation matrix against actual `nex_eos_test`. `CP-M1-E2E-FX-01B.6`
remains paused until that protected Gate closes.
