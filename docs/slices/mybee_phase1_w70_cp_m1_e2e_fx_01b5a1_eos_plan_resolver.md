# CP-M1-E2E-FX-01B.5A.1 EOS Resolver Contract and Repository Query

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_5A_Approved_Allocation_Plan_Semantic_Resolution_Closure_v1.0.md`
- Entry commit: `0c3ca956`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.5A.2`

This Slice adds the authoritative, side-effect-free EOS resolver needed to
translate approved allocation-plan semantics into one immutable plan identity.
It reuses `eos_cost_allocation_plan` and `eos_cost_allocation_plan_line`; it
does not add a lookup table, release a plan, select a latest revision, or
expose a new NSL Tool.

## Canonical Contract

The admitted internal operation is
`FINANCE.COST_ALLOCATION_PLAN.RESOLVE` at
`POST /internal/v2/finance/cost-allocation-plans:resolve`. The selector binds:

- service-token tenant and company scope;
- exact source kind and `PROJECT_SET` scope;
- ISO effective date within the plan interval; and
- the complete Project UUID, Project code, and twelve-decimal ratio set.

Project order is normalized for semantic hashing, but project membership and
ratios are never approximated. The response contains the one immutable
approved plan projection, `selector_hash`, and `resolution_hash`. Both success
and error responses use `Cache-Control: no-store` and `Pragma: no-cache`.

Resolution outcomes are fail-closed:

- exactly one match returns `200` and `EXACT_MATCH`;
- no match returns `404 EOS_COST_ALLOCATION_PLAN_NOT_RESOLVED`;
- more than one match returns `409 EOS_COST_ALLOCATION_PLAN_AMBIGUOUS`;
- malformed or noncanonical selectors return
  `400 EOS_COST_ALLOCATION_PLAN_SELECTOR_INVALID`; and
- persistence failure or an excessive bounded candidate set returns retryable
  `503`.

Only `APPROVED` plans participate. Resolution does not invoke fresh human OA
approval because it is a read-only identity lookup; the service-to-service
token and tenant/company boundary remain mandatory.

## Repository Query

`SqlAlchemyEosAllocationPlanRepository.resolve_matches()` performs a bounded
query over approved plans matching tenant, company, source kind, scope, and
effective interval. It then compares the exact persisted Project identity and
ratio set. The query order is deterministic and the coarse candidate set is
capped at `256`; exceeding that bound fails unavailable instead of returning
an arbitrary plan.

No row is inserted or updated by the resolver. Unit coverage verifies stable
replay and unchanged plan/line row counts before and after repeated reads.

## Contract Assets

- `cost_allocation_plan_resolve.v1.schema.json`
- `cost_allocation_plan_resolution.v1.schema.json`
- the canonical resolver path and schema references in
  `contracts/openapi/nex-eos.openapi.yaml`

## Verification

- Focused resolver and existing allocation-plan regression: `70 passed`
- Canonical contract validation:
  `271 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- EOS Slice Gate: `6/6` commands passed
- EOS regression: `2254 passed`, `65 skipped`
- Statement coverage: `96.97%` against `95.00%`
- Branch coverage: `95.17%` against `94.00%`
- Golden journey, product dependency, and tiered-quality audits: pass
- Evidence:
  `reports/quality/mybee-w70-cp-m1-e2e-fx-01b5a1-eos-slice-gate.json`

The skipped PostgreSQL tests are existing opt-in suites. This Slice introduces
no schema or migration and therefore does not claim PostgreSQL concurrency or
index evidence. Actual EOS PostgreSQL resolver evidence and query-plan review
remain explicitly assigned to `CP-M1-E2E-FX-01B.5A.3`.

## Closure Decision

`CP-M1-E2E-FX-01B.5A.1` is closed. EOS now owns one strict semantic resolver
for approved allocation plans. `CP-M1-E2E-FX-01B.5A.2` may consume this API
through a strict AE client and replace the prior caller-supplied plan identity
without adding direct EOS database access or fallback selection behavior.
