# CP-M1-E2E-FX-01B.5A.2 Strict Installed Consumer and Authority Binding

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_5A_Approved_Allocation_Plan_Semantic_Resolution_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.5A.3`

This Slice installs the EOS allocation-plan resolver as a strict AE consumer
without embedding an M1 scenario in the product boundary. The implementation
does not select a latest Plan, invent ratios, assume a Project count, or fall
back to tenant-specific configuration.

## Generic Product Boundary

`NexAllocationPlanResolverClient` accepts only caller-provided tenant,
company, source kind, effective date, and the complete Project identity and
ratio set. It sends the admitted
`FINANCE.COST_ALLOCATION_PLAN.RESOLVE` request and validates the exact
response contract, selector hash, resolution hash, approved proof, Project
set, ratios, and immutable Plan lineage.

`ApprovedAllocationPlanAuthorityBinder` is independent of M1 and any test
scenario. It binds one admitted resolver result to the exact SourcePool,
business-context hash, and preparation hash. Exact replay returns the existing
checkpoint; changed selector, Plan, source-pool, or journal lineage fails
closed.

`InstalledApprovedAllocationPlanResolution` owns service-token resolution,
EOS transport, timeout validation, readiness, and the generic client/binder
composition. Readiness exposes no token, URL, content, or business default.

## Thin M1 Composition

`m1_allocation_plan_composition.py` is the only M1-specific layer. It reads
the already admitted WorkIntent business context, preparation authority, and
SourcePool, then maps those authoritative values into the generic runtime. It
does not own Plan selection or business values.

The installed product runtime constructs this dependency through the
canonical product profile. Resolver unavailability and malformed or stale
authority fail closed.

## Hardcoding Guard

The focused matrix covers materially different inputs:

- tenant `T101`, two Projects, `SERVICE`, ratios `25/75`; and
- tenant `Z9K2`, three Projects, `PAYROLL`, ratios `20/30/50`.

The SourcePool source Project is intentionally outside the allocation target
set, proving that a source Project is not treated as a fixed allocation
target. Focused residue checks reject scenario tenant values, fixed `40/60`
ratios, and fixture, demo, Golden A, or M1 markers in the three generic product
modules.

## Contract Lineage Reconciliation

The EOS resolver OpenAPI contract added by `.5A.1` changed the admitted EOS
contract digest. This Slice mechanically regenerated the dependent D04/D12
manifest, capability-registry, bundle-lock, platform-lock, and W70 Foundation
Gate receipt chain with the canonical repository builders. No Skill business
contract or runtime behavior was changed by that regeneration.

## Verification

- Focused generic client, binder, installed runtime, and M1 mapping:
  `93 passed`
- Related allocation and installed-runtime regression: `303 passed`
- Focused new-module statement coverage: `96%`
  - generic client: `99%`
  - authority binder: `94%`
  - installed runtime: `100%`
  - thin M1 composition: `91%`
- Frozen-baseline reconciliation regression: `43 passed`
- AE Slice Gate: `6/6` commands passed
- AE regression: `6473 passed`, `47 skipped`
- AE statement coverage: `96.47%` against `95.00%`
- AE branch coverage: `94.72%` against `94.00%`
- Contract validation:
  `271 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- Golden journey, demo/product dependency, ownership, and tiered-quality
  audits: pass
- Evidence:
  `reports/quality/mybee-w70-cp-m1-e2e-fx-01b5a2-ae-slice-gate.json`

The existing opt-in database and provider suites remain skipped by the AE
Slice Gate. This Slice introduces no persistence schema and requires no model
provider. Actual EOS PostgreSQL resolution, ambiguity, restart, and exact
replay evidence remains assigned to `CP-M1-E2E-FX-01B.5A.3`.

## Closure Decision

`CP-M1-E2E-FX-01B.5A.2` is closed. The installed AE runtime now consumes the
authoritative EOS resolver through scenario-neutral components, while M1 is
limited to a thin mapping over existing authoritative inputs. There is no
fixed Plan ID, ratio, Project count, tenant dictionary, direct EOS database
lookup, or fallback selection path.
