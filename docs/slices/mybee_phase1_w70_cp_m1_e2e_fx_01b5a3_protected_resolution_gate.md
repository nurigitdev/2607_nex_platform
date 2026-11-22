# CP-M1-E2E-FX-01B.5A.3 Protected Resolution Gate

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_5A_Approved_Allocation_Plan_Semantic_Resolution_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice:
  `CP-M1-E2E-FX-01B.6: Allocation, P&L, WA, And IA Result Integration`

This Slice closes the protected database and repository Gate for the generic
Allocation Plan resolver introduced by `.5A.1` and the installed authority
binding introduced by `.5A.2`. It adds no product selection rule, migration,
fixed Plan ID, ratio, Project count, tenant dictionary, or fallback.

## Protected PostgreSQL Boundary

The opt-in protected test connects to the actual `nex_eos_test` database as
`nex_eos_user`, creates a uniquely named isolated schema, and applies the
complete EOS migration inventory. The expected head is derived from the
repository inventory instead of being hardcoded; the observed head was
`2548_eos_pnl_privacy_guard` across 49 migrations.

The test then constructs the actual EOS application, admits a signed
`TEST_MOCK` service token for `nex-ae-api`, calls the protected
`FINANCE.COST_ALLOCATION_PLAN.RESOLVE` API through
`NexAllocationPlanResolverClient`, disposes the runtime, creates a second
runtime over the same schema, and finally drops the schema. No AE component
reads EOS tables directly.

Approved Project and Allocation Plan records are seeded before invocation as
authoritative test state. Once the protected request begins, the journey uses
only the product API and consumer. Plan and Line row counts are checked before
and after every resolution branch to prove zero mutation.

## Verification Matrix

- one exact approved semantic match: pass
- same selector exact replay: identical response
- process restart: identical Plan and `resolution_hash`
- stale and future effective dates: `404`, zero disclosure
- cross-tenant and cross-company probes: `404`, zero disclosure
- ratio drift: `404`; nearest-ratio Plan is not selected
- Project UUID/Code mismatch: `404`
- later-created near match: not selected
- overlapping second exact Plan: `409 EOS_COST_ALLOCATION_PLAN_AMBIGUOUS`
- Plan/Line mutation: zero
- isolated schema residue after cleanup: zero
- new migration or product schema: zero

The first protected run also detected an obsolete smoke fixture shape:
`LEGACY_DIRECT` with absent approval lineage violated the current Project
lineage constraint. The fixture was corrected to the governed
`APPROVED_APPLICATION` shape with request, approval, owner, and manager
lineage. No production constraint was weakened.

## Verification Results

- Actual PostgreSQL protected smoke: `1 passed`
- Focused resolver, consumer, authority, and PostgreSQL regression:
  `164 passed`
- Ruff for the protected test: pass
- EOS Slice Gate: `5/5` commands passed
  - EOS regression: `2255 passed`, `65 skipped`
  - statement coverage: `96.97%`
  - branch coverage: `95.17%`
- AE Slice Gate: `6/6` commands passed
  - AE regression: `6473 passed`, `47 skipped`
  - statement coverage: `96.47%`
  - branch coverage: `94.72%`
- Contract validation:
  `271 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- Repository Checkpoint Gate: `PASS`, `5/5` commands, `1689.105s`
  - statement coverage: `98.39%`
  - branch coverage: `96.94%`
  - contract, Golden journey, and demo/product dependency audits: pass

Evidence:

- `reports/quality/mybee-w70-cp-m1-e2e-fx-01b5a3-eos-slice-gate.json`
- `reports/quality/mybee-w70-cp-m1-e2e-fx-01b5a3-ae-slice-gate.json`
- `reports/quality/mybee-w70-cp-m1-e2e-fx-01b5a3-checkpoint-gate.json`
- `reports/quality/checkpoint-latest.json`

## Closure And Resume Decision

`CP-M1-E2E-FX-01B.5A` is closed. Actual PostgreSQL proves deterministic
zero/one/many resolution, isolation, restart replay, and zero mutation without
fixture-driven runtime selection.

`CP-M1-E2E-FX-01B.6` is `READY`. It must consume the exact admitted Plan and
resolution evidence from this boundary to admit the CostSourcePool, execute
and verify AllocationBatch, read privacy-protected Project P&L, and publish
PA/WC/WA/IA results. It may not re-resolve, replace, approximate, or weaken
the approved Plan authority.
