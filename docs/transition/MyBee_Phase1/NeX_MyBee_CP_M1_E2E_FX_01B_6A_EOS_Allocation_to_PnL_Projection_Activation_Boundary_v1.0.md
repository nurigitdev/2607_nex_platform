# NeX MyBee CP-M1-E2E-FX-01B.6A: EOS Allocation-to-P&L Projection Activation Boundary v1.0

## 1. Status And Authority

- Decision date: `2026-11-17`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `fc3b6ccf`
- Parent packet:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Predecessor: `CP-M1-E2E-FX-01B.5A.3`
- Successor after closure: `CP-M1-E2E-FX-01B.6`
- Runtime code changes by this document: none
- Database migration authorized by this document: none
- Remote model-provider dependency: none

This controlled amendment closes the source-backed product gap found when
entering `CP-M1-E2E-FX-01B.6`. It supplements the parent packet without
weakening its allocation conservation, Project P&L authorization, privacy,
replay, publication, or zero-duplicate acceptance criteria.

The existing Cost Allocation command and verification APIs are productized,
and the Project P&L query API is productized. The EOS-owned
`EosProjectPnlProjector` is also implemented and persisted through immutable
Project P&L projection revisions. However, no product route, daemon, or
outbox consumer currently activates that projector after a committed and
verified AllocationBatch. Existing projector smoke tests call the projector
directly from test code; that is valid component evidence but cannot close an
installed product E2E.

## 2. Entry Finding And Decision

The current product path stops here:

```text
FINANCE.COST_ALLOCATION.RUN
  -> committed AllocationBatch and Lines
  -> FINANCE.COST_ALLOCATION.VERIFY
  -> COMMITTED_CONFIRMED / VERIFIED
  -> [missing product activation boundary]
  -> EosProjectPnlProjector.rebuild(...)
  -> FINANCE.PROJECT_PNL.GET
```

`CP-M1-E2E-FX-01B.6` must not fill this gap by:

- calling `EosProjectPnlProjector` from AE, a runner, or Playwright;
- reading EOS private tables from another service;
- letting AE supply Project IDs, Project Codes, period, currency, projection
  version, watermark, or projection time;
- treating a stale pre-allocation projection as current; or
- fabricating P&L output in a WorkResult.

The sequence is therefore amended:

1. implement and close `CP-M1-E2E-FX-01B.6A`;
2. prove the protected EOS refresh contract against actual PostgreSQL;
3. resume `CP-M1-E2E-FX-01B.6`; and
4. make `.6` use only
   `allocation RUN -> VERIFY -> P&L REFRESH -> GET`.

## 3. Confirmed Foundations

The correction must reuse these authorities rather than introduce parallel
storage or business rules:

| Foundation | Current source authority | Required reuse |
| --- | --- | --- |
| Allocation commit | `cost_allocations.py` and `eos_cost_allocation_batch/line` | Batch and Line identities, Plan lineage, period, currency, conservation, and idempotency remain authoritative |
| Allocation verification | `allocation_reconciliation.py` | Refresh requires the existing reconstructed command, source, Plan, outbox, and reconciliation proof |
| Allocation event | `FINANCE.COST_ALLOCATION_COMMITTED.v1` | Remains publication evidence; it is not redefined as a projector receipt |
| P&L source loading | `SqlAlchemyEosProjectPnlProjectionSource` | EOS derives source pools, allocations, payroll, material, budget, and posting facts |
| P&L projection | `EosProjectPnlProjector` | Existing deterministic component classification, watermarks, conservation, and freshness rules remain unchanged |
| P&L persistence | `SqlAlchemyEosProjectPnlRepository` | Existing immutable version, projection hash, authority, and component tables are reused |
| P&L read | `FINANCE.PROJECT_PNL.GET` | Fresh OA Project authorization and privacy/difference-attack guards remain the only user-facing read boundary |

## 4. Normative Decisions

### 4.1 Protected EOS Operation

EOS SHALL add this protected internal operation:

```text
Operation ID : FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION
Method       : POST
Path         : /internal/v2/finance/cost-allocation-batches/{batch_id}:refresh-project-pnl
Route class  : WRITE
Audience     : nex-eos
Scope        : service:call
```

The business selector supplied by the caller is exactly `batch_id`. Tenant
and company remain mandatory trusted request headers, and authentication and
correlation headers retain their existing platform meanings. The operation
accepts no JSON body and no query parameters.

The canonical caller for `.6` is `nex-ae-api`. A future EOS-owned worker may
use the same protected service contract, but this amendment does not add a
daemon or broaden user access.

### 4.2 Verified Batch Admission

Before projection, EOS SHALL invoke the existing allocation reconciliation
boundary and require all of the following:

```text
commit_state           = COMMITTED
reconciliation_status  = COMMITTED_CONFIRMED
verification_status    = VERIFIED
retry_disposition      = DO_NOT_RERUN
batch                   = present and exact
reversed_pool_ids       = []
```

The verified Batch must belong to the exact request tenant and company.
Missing, cross-tenant, and cross-company Batch probes return the same bounded
not-found response and disclose no foreign identity or state. Failed,
pending, reversed, or adjustment-required verification cannot refresh P&L.

### 4.3 EOS-Derived Refresh Authority

The caller SHALL NOT provide any P&L projection input other than `batch_id`.
EOS derives:

- `period_id`, `functional_currency`, Batch state, Plan identity, and
  reconciliation hash from the verified AllocationBatch;
- target Project IDs and Codes from committed AllocationLines;
- source/residual Project IDs and Codes from the exact SourcePools consumed by
  that Batch;
- the affected Project set as the stable union of allocation targets and
  source/residual Projects;
- Project status and Project Code from EOS Project authority;
- `as_of` and `evaluated_at` from the immutable Batch `committed_at` for the
  exact refresh attempt; and
- the projection version from existing immutable Project P&L revisions.

The affected Project set is sorted by stable Project identity before rebuild.
Including source/residual Projects is mandatory even when the current Batch
has zero residual, because a new verified allocation may remove a previously
visible unallocated component.

### 4.4 Deterministic Immutable Projection And Replay

For every affected Project, EOS builds the existing
`ProjectPnlRebuildRequest` and delegates calculation to the existing
projector. No allocation or P&L formula is duplicated in the activation
service.

First execution appends exactly one next immutable projection revision for
each affected Project. Exact replay, including replay after process restart,
returns the already persisted projection identities and hashes and appends no
new revision.

Replay equivalence is bound to at least:

- tenant and company;
- Batch ID and verified reconciliation hash;
- period and functional currency;
- stable affected Project set;
- Batch `committed_at` projection boundary;
- posting and allocation watermarks; and
- resulting projection IDs, versions, and hashes.

The activation service may extend the existing repository with a bounded
query over immutable projections to find the exact refresh result. It may not
add a mutable receipt column or silently choose the latest row. Concurrent
identical refreshes must converge: one append may win, while the other reloads
and returns the exact persisted result as replay.

If a newer projection exists and the exact historical refresh cannot be
proven, EOS fails closed with an ordering/reconciliation conflict. It must not
append an older `as_of` revision after a newer semantic boundary or return a
latest-row approximation.

### 4.5 Response Contract

The success response SHALL use a new canonical schema such as
`eos_project_pnl_refresh_from_allocation.v1` with this bounded shape:

```json
{
  "schema_version": "eos_project_pnl_refresh_from_allocation.v1",
  "operation": "FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION",
  "tenant_id": "...",
  "company_id": "...",
  "batch_id": "...",
  "period_id": "...",
  "allocation_reconciliation_hash": "sha256:...",
  "disposition": "CREATED | EXACT_REPLAY",
  "projections": [
    {
      "project_id": "...",
      "project_code": "...",
      "projection_id": "...",
      "projection_version": 1,
      "projection_hash": "sha256:...",
      "reconciliation_status": "VERIFIED",
      "freshness_status": "CURRENT"
    }
  ],
  "refresh_hash": "sha256:..."
}
```

Projection references are sorted by Project identity. `refresh_hash` covers
the complete response semantics excluding only itself. Exact replay preserves
the Project projection identities, versions, hashes, and refresh hash; only
the transport status and explicit disposition may distinguish creation from
replay.

### 4.6 Authorization And Privacy Separation

Refresh is an EOS-internal derived-state operation protected by service trust.
It does not grant a user permission to read Project P&L and does not accept a
user subject as projection authority.

After refresh, `.6` reads each result only through
`FINANCE.PROJECT_PNL.GET`, passing the actual requester subject. That read
must continue to perform fresh OA Project authorization, classification,
payroll suppression, minimum-population, and difference-attack checks. A
successful refresh therefore cannot be used as a read-authorization proof.

### 4.7 No New Persistence Or Outbox Reinterpretation

This amendment authorizes no database migration. The existing immutable P&L
header/component tables and allocation authorities are sufficient.

The existing `eos_outbox.delivery_state` has one external publication
meaning. It SHALL NOT be reused as an internal projector-completion ACK or be
marked `PUBLISHED` merely because P&L refresh succeeded. Allocation event
publication and P&L projection activation remain distinct responsibilities.

## 5. Error Contract

At minimum, the protected operation distinguishes these bounded outcomes:

| Condition | HTTP | Required behavior |
| --- | ---: | --- |
| Batch absent or outside tenant/company | 404 | zero disclosure |
| Batch verification not committed and verified | 409 | no projection mutation |
| Reversed or adjustment-required Batch | 409 | no projection mutation |
| Batch/Line/SourcePool/Project lineage drift | 409 | fail closed |
| Exact historical result cannot be proven after a newer boundary | 409 | no latest-row fallback |
| Concurrent exact replay | 200 | return exact persisted projection set |
| EOS projector or persistence unavailable | 503 | retryable; no fabricated success |

Malformed `batch_id`, unknown body/query fields, or missing trusted headers
are rejected before any projection mutation.

## 6. Product Composition After Closure

After `6A` closes, `CP-M1-E2E-FX-01B.6` owns this sequence only:

```text
verified PostedJournal
  -> FINANCE.COST_ALLOCATION.RUN
  -> FINANCE.COST_ALLOCATION.VERIFY
  -> FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION(batch_id)
  -> FINANCE.PROJECT_PNL.GET for each authorized Project
  -> redacted PA AgentResult / WC WorkResult
  -> WC delivery ACK
  -> WA source consumption
  -> IA owner-visible publication
```

`.6` must preserve the exact Batch, reconciliation, projection, OA decision,
and privacy evidence references. It may not call the projector directly,
recalculate amounts, choose a projection version, or replace a denied P&L
read with refresh output.

## 7. Implementation Slices

### CP-M1-E2E-FX-01B.6A.1: Refresh Contract And Source Resolver

- add canonical schema, examples, OpenAPI operation, and error contract;
- add an EOS-owned resolver for verified Batch, Lines, SourcePools, Projects,
  and exact affected Project set;
- reject cross-scope, unverified, reversed, malformed, and incomplete lineage;
- derive all refresh inputs from EOS authority; and
- add no migration.

### CP-M1-E2E-FX-01B.6A.2: Deterministic Projection Activation Service

- compose the existing allocation reconciliation service, P&L source,
  projector, and repository;
- derive deterministic time, ordering, version, and refresh hash;
- implement exact replay, restart replay, and concurrent convergence;
- prohibit latest-row approximation and out-of-order regression; and
- register the protected EOS route and dependency readiness.

### CP-M1-E2E-FX-01B.6A.3: Strict Consumer And Protected Gate

- add a provider-neutral typed client used by `.6`;
- validate the exact response and Batch/reconciliation/projection lineage;
- run actual EOS PostgreSQL migration/state smoke;
- prove creation, replay, restart, concurrency, cross-scope, verification,
  and zero-mutation negatives;
- run EOS and AE focused regression and coverage; and
- run the required Checkpoint Gate and record the `.6` resume decision.

## 8. Verification Matrix

The protected Gate SHALL prove at least:

```text
verified Batch refresh                    = PASS
caller business selector fields           = batch_id only
target + source/residual Project union     = EXACT
stable Project ordering                    = PASS
first immutable projection revisions       = exactly one per Project
same request exact replay                   = same projection refs/hashes
restart exact replay                        = same projection refs/hashes
concurrent exact replay                     = one semantic result
allocation conservation                     = unchanged
Batch/Line/SourcePool mutation              = 0
outbox publication-state mutation           = 0
cross-tenant and cross-company probes        = zero disclosure
unverified/reversed/adjustment Batch         = denied
Project/period/currency/lineage drift        = denied
newer-boundary latest-row shortcut           = prohibited
P&L GET with current OA entitlement          = pass
unauthorized Project P&L GET                 = denied
payroll/private component leakage            = 0
difference-attack suppression regression      = pass
new database migration                       = 0
```

Actual PostgreSQL evidence must use `nex_eos_test` with dynamically derived
migration inventory, isolated schema cleanup, and zero residue. Remote model
providers are not required.

## 9. Prohibited Shortcuts

The following cannot close `6A`:

- direct projector invocation outside EOS product code;
- a test-only refresh factory, endpoint, or route;
- caller-provided Project, period, currency, version, ratio, watermark, or
  timestamp;
- selecting the latest projection without exact Batch-bound semantics;
- changing AllocationBatch or SourcePool state during refresh;
- marking the allocation outbox event published as a projector ACK;
- exposing unredacted P&L components in the refresh response;
- treating refresh success as OA read authorization;
- a scenario tenant, fixed Project set, fixed ratio, or M1 amount branch;
- adding an NSL/compiler/runtime special case; or
- creating a new projection or receipt table without another explicit
  controlled amendment.

## 10. Stop Conditions

Implementation stops for another explicit decision if:

1. exact replay cannot be proven from existing immutable projection state;
2. concurrent refresh requires a new durable receipt or lock entity;
3. the current projector cannot derive a complete projection at the verified
   Batch boundary without caller-supplied business values;
4. affected Project authority cannot be derived from Batch, Line, SourcePool,
   and Project records;
5. a newer semantic boundary makes historical replay ambiguous;
6. P&L refresh would need to mutate the AllocationBatch, SourcePool, Journal,
   or outbox publication state; or
7. existing OA/privacy guards cannot protect the post-refresh GET path.

## 11. Closure And Resume Rule

`CP-M1-E2E-FX-01B.6A` closes only when a verified AllocationBatch can refresh
the exact affected Project P&L set through the protected EOS product API,
exact replay and restart return the same immutable projections, all denied
paths produce zero financial mutation and zero disclosure, actual PostgreSQL
passes, and no migration or private-state caller is introduced.

After closure, `CP-M1-E2E-FX-01B.6` resumes. It must consume the protected
refresh result and then read P&L through the existing authorized query API.
It may not reopen projector ownership or weaken any allocation, OA, payroll
privacy, WorkResult, WA, or IA publication boundary.
