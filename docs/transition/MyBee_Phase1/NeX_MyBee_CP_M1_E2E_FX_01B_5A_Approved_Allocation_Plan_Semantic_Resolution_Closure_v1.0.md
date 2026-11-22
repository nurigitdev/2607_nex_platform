# NeX MyBee CP-M1-E2E-FX-01B.5A: Approved Allocation Plan Semantic Resolution Closure v1.0

## 1. Document Status

- Date: `2026-11-16`
- Status: `IMPLEMENTATION REQUIRED / ENTRY DECISION FROZEN`
- Parent:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Trigger: source-backed stop condition discovered before
  `CP-M1-E2E-FX-01B.6`
- Scope: approved Cost Allocation Plan semantic resolution only
- Database migration: prohibited by default
- Remote provider: not required
- Successor: `CP-M1-E2E-FX-01B.6`

This controlled amendment closes one authority gap between deterministic D04
Journal completion and the existing EOS allocation product. It does not
create, approve, release, mutate, or retire an Allocation Plan. It provides a
fail-closed way for the installed PA runtime to identify the one already
approved plan whose semantics exactly match the admitted M1 request and the
verified Posted Journal source.

## 2. Source-Backed Gap

The current product sources establish all of the following:

1. `ae.business_request_context.v1` preserves requested Project Codes and
   ratios, but does not contain an Allocation Plan ID or revision.
2. `READY_FOR_D04` preparation authority resolves Project identities and OA
   authorization, but correctly does not invent an Allocation Plan identity.
3. EOS `FINANCE.COST_ALLOCATION_PLAN.RELEASE` requires a distinct final
   `BUSINESS_FORMAL` proof bound to the exact plan hash, operation, and
   protected resource.
4. EOS `FINANCE.COST_ALLOCATION_PLAN.GET` requires a caller-supplied
   `plan_id + plan_revision`.
5. EOS has no current API that resolves an approved plan by source kind,
   effective date, Project set, and exact allocation ratios.
6. Allocation execution requires an already released plan and rejects source
   or plan semantic drift.

Therefore the installed runtime cannot satisfy the parent work order by using
only existing public product APIs. A fixed Plan ID, direct SQL query, test
fixture lookup, latest-row shortcut, or runner-owned mapping would violate the
parent document's authority and hard-coding rules.

This activates parent stop condition 3: an existing service API cannot express
the required authority transition. Implementation of `.6` remains paused
until this amendment passes.

## 3. Decision

EOS SHALL expose a side-effect-free semantic resolver for already approved
Cost Allocation Plans.

```text
operation_id = FINANCE.COST_ALLOCATION_PLAN.RESOLVE
method       = POST
path         = /internal/v2/finance/cost-allocation-plans:resolve
owner        = nex-eos
semantics    = READ
side effect  = none
```

`POST` is used because the selector is a bounded structured object. It does
not imply creation or mutation. The response SHALL use `Cache-Control:
no-store`, require signed service trust, and remain tenant/company scoped.

The resolver SHALL NOT call the release operation, manufacture approval
evidence, change plan state, or select an arbitrary candidate. Plan creation
and approval remain separate governed business operations.

This operation is an installed post-write orchestration dependency, not an
agent-selectable NSL Tool or a new D04 Skill. It SHALL NOT be added to a model
capability snapshot or compiled as another plan step in this amendment. A
future Tool activation would require its own signed Skill and capability
admission decision.

## 4. Canonical Selector

The request body SHALL have this logical shape:

```json
{
  "schema_version": "eos_cost_allocation_plan_resolve.v1",
  "source_kind": "SHARED_EXPENSE",
  "scope_type": "PROJECT_SET",
  "effective_on": "2026-11-16",
  "projects": [
    {
      "project_id": "<EOS Project UUID>",
      "project_code": "VO00D260101",
      "allocation_ratio": "0.400000000000"
    },
    {
      "project_id": "<EOS Project UUID>",
      "project_code": "VO00D260102",
      "allocation_ratio": "0.600000000000"
    }
  ]
}
```

Tenant and company identity SHALL come from authenticated headers. The source
kind SHALL come from the admitted EOS CostSourcePool projection after verified
Journal commit. Effective date and Project allocation SHALL come from the
hash-bound WorkIntent and authoritative Project resolution. A model, browser,
runner, or fixture cannot supply a Plan identity.

Selector admission SHALL enforce:

- canonical fields only;
- exact EOS Project UUID and Project Code pairing;
- unique Project identities and codes;
- stable Project Code ordering in the canonical projection;
- positive decimal ratios at EOS precision;
- exact ratio total of one;
- admitted source kind and `PROJECT_SET` scope;
- an ISO calendar date; and
- a deterministic selector hash using the shared semantic hash primitive.

The user-facing UI and final result continue to communicate by Project Code.
Internal EOS joins use UUID authority.

## 5. Exact Match Semantics

A candidate Plan matches only when all of the following are true:

1. tenant and company match the authenticated request;
2. plan state is `APPROVED`;
3. source kind and scope type match exactly;
4. `effective_start <= effective_on` and `effective_end` is absent or not
   earlier than `effective_on`;
5. Project ID, Project Code, and normalized ratio sets are exactly equal;
6. every line retains its immutable line and eligibility hashes;
7. the plan has a final approval-proof reference and immutable plan hash; and
8. the complete projection passes canonical integrity validation.

The resolver SHALL NOT silently choose the highest revision, newest creation
time, first database row, closest ratio, overlapping date, or default basis
kind. If more than one approved row satisfies the exact selector, authority is
ambiguous and execution stops. Operational data must be corrected or the
future business context must be extended through a separate controlled
amendment.

The resolution outcomes are fixed:

| Condition | HTTP | Error code / disposition |
| --- | ---: | --- |
| exactly one approved match | `200` | `EXACT_MATCH` |
| no approved match | `404` | `EOS_COST_ALLOCATION_PLAN_NOT_RESOLVED` |
| two or more exact matches | `409` | `EOS_COST_ALLOCATION_PLAN_AMBIGUOUS` |
| malformed or ratio-invalid selector | `400` | `EOS_COST_ALLOCATION_PLAN_SELECTOR_INVALID` |
| tenant/company or Project mismatch | `403/404` | fail-closed without cross-scope disclosure |
| persistence unavailable | `503` | retryable, no fallback |

## 6. Authority Projection

The successful response SHALL include only the authority needed by `.6`:

- tenant and company IDs;
- Plan ID and revision;
- Plan hash and state;
- source kind, scope type, and basis kind;
- effective interval;
- rule release hash and basis source reference/hash;
- final approval-proof reference;
- exact ordered Project lines, ratios, work-code references, eligibility
  hashes, and confidentiality classes;
- selector hash;
- operation and `EXACT_MATCH` disposition; and
- a semantic resolution hash over the complete response excluding that hash.

The response SHALL NOT expose approval bodies, decision comments, OA token
content, payroll details, or private database diagnostics.

AE SHALL bind the resolution hash, Plan ID/revision/hash, selector hash,
source-pool hash, WorkIntent context hash, and `READY_FOR_D04` preparation hash
into the restart-safe post-write checkpoint before allocation execution.

## 7. Product Integration Boundary

The implementation SHALL reuse existing authorities:

- `eos_cost_allocation_plan` and `eos_cost_allocation_plan_line` remain the
  Plan SoR;
- the existing release path remains the sole Plan mutation path;
- `EosCostAllocationService` remains the allocation executor;
- existing Project and company scopes remain authoritative;
- OA/WC evidence used during Plan release remains immutable history; and
- the installed AE runtime consumes the resolver through a strict HTTP client.

No new runtime branch may mention M1, tenant `VO00`, sample Project Codes,
USD 10,000, KRW 1,350.20, or 40/60. The resolver must work for arbitrary
admitted tenant/company/Project sets and exact decimal ratios.

## 8. Implementation Slices

### CP-M1-E2E-FX-01B.5A.1: EOS Resolver Contract And Repository Query

- add canonical selector/result validators;
- add an exact, bounded repository query over existing Plan/Line tables;
- implement zero/one/many outcome handling;
- add the protected internal API and OpenAPI contract; and
- prove no writes, no release call, and no new migration.

### CP-M1-E2E-FX-01B.5A.2: Strict Installed Consumer And Authority Binding

- add the MyBee/AE strict resolver client;
- validate tenant, company, Project set, ratios, plan hash, and approval ref;
- bind resolver evidence to the post-write checkpoint;
- expose installed readiness without secrets or business defaults; and
- reject replay with changed selector or source-pool lineage.

### CP-M1-E2E-FX-01B.5A.3: Protected Resolution Gate

- run actual EOS PostgreSQL migration/state smoke;
- prove exact match, no match, ambiguity, overlap, stale dates, ratio drift,
  cross-company, and cross-tenant denial;
- prove restart and exact replay determinism;
- run EOS/AE focused regression and coverage;
- run the required Checkpoint Gate; and
- record the `.6` resume decision.

## 9. Verification Matrix

The Gate SHALL include at least:

```text
exact one approved semantic match       = PASS
same selector exact replay              = PASS
same plan resolution hash after restart = PASS
no approved match                       = 404
two exact approved matches              = 409
nearest-ratio candidate                  = NOT SELECTED
latest-row shortcut                      = PROHIBITED
expired/future plan                      = NOT SELECTED
Project UUID/Code mismatch               = DENIED
cross-company and cross-tenant probes    = ZERO DISCLOSURE
Plan/Line mutation count                 = 0
new migration                            = 0
fixture or direct SQL runtime lookup     = 0
```

Focused coverage SHALL prioritize no-match, ambiguity, malformed ratios,
overlapping effective intervals, hash drift, and persistence-failure branches.
Existing service coverage floors may not be reduced.

## 10. Prohibited Shortcuts

The following cannot close `.5A`:

- adding Plan ID/revision as a model-selected or user-entered authority;
- choosing the latest or first approved Plan;
- approximate ratio matching;
- querying EOS private tables from AE, a smoke runner, or Playwright;
- releasing a Plan as a side effect of resolution;
- reusing a business-proposal or accounting proof whose payload hash is not
  the exact Allocation Plan hash;
- test-only resolver factories or tenant-specific dictionaries;
- changing NSL compiler/runtime behavior;
- weakening existing BUSINESS_FORMAL or OA authorization requirements; or
- treating a fixture-seeded Plan as runtime configuration.

Fixtures may seed an already approved Plan before a protected test begins.
After request admission, only product APIs and installed workers may advance
the journey.

## 11. Stop Conditions

Implementation stops for another explicit decision if:

1. the existing Plan/Line schema cannot express an exact semantic query;
2. production-scale `EXPLAIN` evidence requires a new index or migration;
3. multiple valid plans are an intended business condition rather than a data
   conflict;
4. the source kind cannot be derived from the admitted Posted Journal line;
5. Project entitlement must be extended with a new OA action; or
6. a resolved Plan cannot be bound to `.6` without a new durable entity.

## 12. Closure And Resume Rule

`.5A` closes only when one approved Plan is resolved through the canonical EOS
API, its immutable authority is bound to the installed AE post-write
checkpoint, zero/one/many outcomes are proven against actual PostgreSQL, and
the repository Gate passes without migration or fixed business values.

After closure, `CP-M1-E2E-FX-01B.6` resumes from the exact resolution evidence.
It may admit the CostSourcePool, execute and verify the AllocationBatch, read
privacy-protected Project P&L, and publish PA/WC/WA/IA results. It may not
re-resolve or replace the Plan using a weaker rule.
