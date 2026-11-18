# CP-M1-E2E-FX-01B.6B.5B.1 Claimable Source And Dispatch Contract

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5B_Installed_WC_Assignment_Dispatch_Closure_v1.0.md`
- Database migration: `1007_wc_assignment_dispatch_scan`
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5B.2`

## Source-Backed Decision

The existing `ix_wc_work_item_state_created` index is ordered by
`(tenant_id, state, created_at)`. Actual `nex_wc_test` EXPLAIN evidence showed
that the generic cross-tenant `CREATED/ROUTED` query otherwise requires a
sequential scan and sort. The approved corrective migration adds one partial
index:

```text
ix_wc_work_item_dispatch_scan
  (state, created_at, tenant_id, work_item_id)
  WHERE state IN ('CREATED', 'ROUTED')
```

No table, mutable business field, or cross-service persistence was added.
State-specific keyset scans now match the partial index and remain bounded by
an explicit `1..500` limit.

## Contract

`SqlAlchemyCoordinationRepository` and its in-memory counterpart now expose a
bounded claimable WorkItem source. The source:

- accepts only `CREATED` or `ROUTED`;
- pages by `(created_at, tenant_id, work_item_id)` within one state;
- returns only identity, state, version, trace, and timestamps;
- maps `CREATED` to `ROUTE` and `ROUTED` to `CLAIM`; and
- excludes prompt, goal, business payload, Project-specific logic, and other
  private WorkItem content.

The new `assignment_dispatch.py` contract freezes:

- job type `WC_ASSIGNMENT_DISPATCH`;
- subject type `WC_WORK_ITEM`;
- schema `wc_assignment_dispatch.v1`;
- deterministic semantic identity over tenant, WorkItem, expected version,
  and action;
- deterministic UUID job identity;
- reference-only payload and links;
- five bounded attempts; and
- explicit `RETRY`, `RELOAD`, and `TERMINAL` failure dispositions.

`NO_ELIGIBLE_AGENT` remains retryable. Version conflicts and an already active
Claim require authority reload. Authorization denial and malformed authority
remain terminal for the current job identity. This Slice defines those
semantics but does not enqueue or execute a dispatch job.

## Verification

- focused contract and existing coordination regression: `54 passed`
- actual PostgreSQL protected regression: `31 passed`
- actual database identity: `nex_wc_test / nex_wc_user`
- applied migration: `1007_wc_assignment_dispatch_scan`
- PostgreSQL query plan: `Index Scan using ix_wc_work_item_dispatch_scan`
- protected test residue: `0`
- Ruff and compile checks: PASS
- WC Slice Gate: `695 passed`, `23 protected skips`
  - statement coverage: `97.86%`
  - branch coverage: `95.80%`
  - commands: `5/5`
- contract validation: `274 schemas`, `320 examples`, `260 negative examples`,
  `10 OpenAPI`
- Golden Journey transition and demo/product dependency audits: PASS
- evidence:
  `reports/quality/mybee-w70-cp-m1-01b6b5b1-wc-slice-gate.json`

The non-blocking warnings are the previously recorded Starlette/httpx and
SQLite datetime deprecations. No new warning was introduced by this Slice.

## Closure

`CP-M1-E2E-FX-01B.6B.5B.1` is closed. WC now owns a bounded, index-backed,
content-minimal claimable source and a deterministic dispatch job contract.
No routing or claim transition has been moved into a runner. `.5B.2` may add
the generic scheduler and handler by reusing `SqlAlchemyJobQueue`,
`run_worker_once()`, and the existing `WorkCoordinationService.route()` and
`claim()` authority.
