# NeX MyBee W60-CA01: Project P&L Projection and Management Allocation Entry Reconciliation v1.0

## 1. Status And Authority

- Decision date: `2026-11-14`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `e8580f6054498529253cfca713fd972a38992d69`
- Runtime code changes by this document: none

This controlled amendment reconciles the completed W40 immutable PostedJournal
and W50 allocation/budget authorities with the planned W60 Project P&L
projection. It freezes how payroll and material cost become Project management
cost, how the result remains traceable to the immutable GL, and how a fast P&L
read model is built without creating a second financial ledger.

Where an earlier document can be read as requiring a new management-journal
header and line in addition to the W50 allocation ledger, this amendment takes
precedence. Where a material purchase can be read as immediate Project expense
before inventory consumption, this amendment also takes precedence.

## 2. W60 Entry Decision

W60 may begin after this amendment because its source authorities now exist:

1. `eos_journal_header` and `eos_journal_line` are the immutable POSTED GL
   truth.
2. `eos_cost_source_pool` admits exact eligible Journal-line components and
   preserves source Project, account, period, currency, policy, and hash
   lineage.
3. `eos_cost_allocation_plan` and its lines preserve an approved, immutable,
   hash-bound allocation basis.
4. `eos_cost_allocation_batch` and `eos_cost_allocation_line` persist the
   deterministic management-allocation result.
5. `eos_cost_allocation_adjustment` preserves append-only correction lineage.
6. W50 proved actual PostgreSQL concurrency, exact replay, transaction
   rollback, outbox atomicity, and `E = D + A + U` conservation.
7. `eos_budget` and Project budget binding remain separate from POSTED actuals.
8. The immutable GL and allocation contracts can carry consumption cost, but
   purchase-time Project material commitment and unassigned-inventory
   visibility require an explicit W60 projection boundary.
9. The immutable GL can carry company- or organization-level payroll expense,
   but the PayrollRun, approved work evidence, privacy, and Project allocation
   bridge require an explicit W60 contract boundary.

W60 is authorized to build Project P&L projection, freshness, access, and
privacy around these authorities. It is not authorized to mutate GL truth,
duplicate the allocation ledger, infer unapproved allocation ratios, or treat
budget and planned work as confirmed actual cost.

## 3. Source-Backed Current State

| Boundary | Confirmed source state | W60 consequence |
| --- | --- | --- |
| Migration inventory | EOS currently ends at `2542_eos_budget_project_binding.sql` | Historical `2527` P&L reservation is occupied; the implementation Slice must reserve the next free migration only after rechecking HEAD |
| PostedJournal | Header and lines are immutable, POSTED, Project-attributed truth | P&L lineage starts from exact Journal and line identity; no management write updates the GL |
| Source eligibility | `2541` admits only REVENUE/EXPENSE components with explicit recognition mode | Balance-sheet inventory, asset, liability, tax, and cash lines are not Project expense merely because they were posted |
| Allocation authority | Source pool, plan revision, batch, line, and adjustment structures are active | They are the canonical management-allocation ledger; no parallel management-journal tables are required |
| Work basis | `eos_project_work_assignment.planned_man_days` supports approved plan evidence | Approved actual Man-Day SoR is not yet present; planned Man-Day cannot silently become confirmed actual effort |
| Payroll evidence | EOS has no authoritative PayrollRun, attendance, leave, tax, or payroll-calculation authority | W60 must define a privacy-preserving Payroll-to-Project bridge without absorbing HR/payroll product ownership |
| Material basis | `USAGE` and approved-plan basis kinds are admitted | Purchase receipt alone is not consumption; W60 must still expose Project-attributed and unassigned purchased inventory without classifying it as actual expense |
| Budget | Approved Budget SoR and Project binding are active | Budget/forecast and actual P&L remain separately identified authorities |
| P&L projection | No active `eos_project_pnl_projection` exists | W60 must add a rebuildable, watermark-aware read model rather than query all source tables for every request |
| Authorization | OA is the Project authorization-decision SoR | P&L reads require fresh Project/company scope and privacy policy; membership alone is insufficient for payroll-sensitive detail |

## 4. Normative Decisions

### W60-CA01-ADR-01: Use The W50 Allocation Ledger As The Management Entry

The business term **Project management allocation entry** maps to the existing
W50 persistence authorities:

| Business concept | Canonical persistence authority |
| --- | --- |
| Source accounting component | `eos_cost_source_pool` |
| Approved rule and evidence snapshot | `eos_cost_allocation_plan` and `eos_cost_allocation_plan_line` |
| Management entry header | `eos_cost_allocation_batch` |
| Management entry line | `eos_cost_allocation_line` |
| Correction or reversal lineage | `eos_cost_allocation_adjustment` |

User-facing products may label a batch and its lines as `Project management
allocation entry`, `management allocation voucher`, or `Project cost
allocation ledger`. Those labels do not make the records a second GL and do
not authorize new `eos_management_journal_header/line` tables.

Creating another mutable management-journal pair would duplicate W50 facts,
complicate reconciliation, and create a double-counting path. A later use case
that cannot be expressed by the allocation authorities requires a separate
controlled amendment before adding persistence.

### W60-CA01-ADR-02: Preserve One Recognition Path And Exact GL Lineage

Every Project P&L component must preserve the W50 recognition invariant:

```text
eligible recognized source amount (E)
  = direct recognized amount (D)
  + finalized allocated amount (A)
  + explicit unallocated amount (U)
```

- `DIRECT` contributes the eligible source component once to its source
  Project.
- `MANAGEMENT_ALLOCATION` contributes committed allocation lines to target
  Projects and does not also contribute the original source Project amount.
- `GL_COST_TRANSFER` remains inactive until a separate governed decision.
- `INELIGIBLE`, non-POSTED, unreconciled, and unrecognized balance-sheet
  components do not contribute confirmed P&L.

Every direct or allocated component must resolve to the exact immutable
Journal, Journal line, source pool, policy/evidence hashes, and, for allocated
cost, batch and allocation line. Projection rows are derived summaries and do
not replace that lineage.

### W60-CA01-ADR-03: Allocate Payroll By Approved Effort, Not Membership

Project membership proves participation and authorization scope. It does not
prove how much labor a member supplied to a Project. Payroll allocation uses
the following evidence order:

1. approved actual Man-Day or equivalent actual-work evidence;
2. approved Project WorkAssignment/plan Man-Day when actual evidence is not
   yet available;
3. another approved driver only when the payroll allocation policy explicitly
   admits it.

An `APPROVED_PLAN` result is `PROVISIONAL` or `FORECAST`; it is not reported as
confirmed actual effort. When actual work is approved later, EOS creates a new
plan revision and append-only adjustment lineage. It does not edit the prior
batch or allocation lines.

The monthly payroll source is admitted from eligible POSTED payroll-expense
components. Payroll liabilities, withholding, cash, advances, and balancing
lines do not become separate Project labor cost.

HR, attendance, leave, tax, and payroll calculation remain the responsibility
of an HR/payroll SoR. EOS does not recompute gross pay, deductions, net pay,
withholding, leave entitlement, or attendance. EOS consumes two logical,
hash-bound contracts from that boundary.

#### PayrollPostingEvidence

| Field group | Minimum meaning |
| --- | --- |
| Identity | tenant, legal entity/company, opaque `payroll_run_id`, payroll period, revision |
| Posting lineage | Journal ID, eligible expense line/component references, accounting period, POSTED/reconciliation state |
| Cost classification | organization/cost center where admitted, payroll component class, account, functional currency |
| Amount | eligible aggregate payroll expense, never an invented total derived from liability or net-pay lines |
| Evidence | payroll source reference/hash, approval reference/hash, posting mapping hash, privacy classification |

#### LaborEffortSnapshot

| Field group | Minimum meaning |
| --- | --- |
| Identity | tenant, company, effort period, snapshot revision, source reference/hash |
| Basis | approved actual hours/Man-Day by Project and WorkCode where admitted |
| Aggregate dimensions | organization, Grade/band, cost cohort, or another approved non-identifying dimension |
| Closure | attendance/work evidence cut-off, approval state, approved-at, superseded/revoked state |
| Privacy | confidentiality class, aggregate population/suppression metadata, no ordinary-view employee pay |

Raw employee attendance and payroll records remain private in their owning
SoR. EOS may persist opaque lineage and admitted Project-level aggregate basis,
but it must not turn that evidence into a general employee payroll database.

### W60-CA01-ADR-03A: Support Company And Organization Payroll Journals

The payroll bridge must support both common Posting shapes:

- one company-wide monthly Payroll Journal; and
- multiple organization, cost-center, or payroll-component Journals/lines.

Where the Journal provides separate expense components, EOS creates distinct
eligible SourcePools by exact Journal line/component and approved policy. A
single consolidated expense line may still be allocated, but its weaker
organization/component traceability must remain visible in evidence and
reconciliation status.

The following may enter a payroll cost pool only when the released accounting
policy admits the exact expense component:

- base salary and overtime expense;
- bonus or incentive expense;
- employer-paid insurance, tax, welfare, or benefit expense;
- leave, training, bench, or other paid non-productive labor cost; and
- signed correction/reversal expense components.

Employee withholding, income tax payable, social-insurance payable, net-pay
liability, cash, advances, receivables, and balancing lines are not additional
Project labor cost. Capitalized labor or another asset component is not actual
P&L expense until the governed accounting recognition event occurs.

Each admitted payroll component uses exactly one direct or management-
allocation path and remains subject to `E = D + A + U`.

### W60-CA01-ADR-03B: Preserve Non-Project Time And Residual Labor

Paid leave, training, bench time, corporate administration, and other
non-Project activity cannot be disguised as productive Project Man-Day. The
released labor policy must select one explicit treatment for each class:

1. charge an approved real organization/operating Project;
2. allocate as indirect labor overhead using an approved actual-effort driver;
   or
3. retain it as `POSTED_PAYROLL_UNALLOCATED` or
   `UNALLOCATED_LABOR_OVERHEAD`.

The system must not create a hidden synthetic Project or spread unexplained
labor across all members merely to force a zero residual. Any operating
Project used for this purpose must be a real governed Project with valid
Project Code and authorization.

Actual effort and payroll may close on different dates. A late attendance,
leave, transfer, bonus, or payroll correction creates a new evidence/plan
revision and append-only allocation adjustment. It cannot silently rewrite a
closed-period P&L result.

### W60-CA01-ADR-04: Keep Individual Payroll Private

General allocation and Project P&L structures must not persist or expose
individual salary amounts. The preferred source pool is an admitted aggregate
such as company, payroll period, expense account, Grade, cost center, or other
approved confidentiality cell. The allocation basis may use protected
employee work evidence, but the emitted allocation line contains Project,
work-code where admitted, basis, amount, and evidence hash rather than a
public employee-payroll record.

The Phase-1 default is an aggregate payroll pool distributed by approved
actual Man-Day, optionally weighted by an approved Grade/band policy. If a
future private payroll adapter computes exact employee-level cost internally,
it emits only Project-level aggregate allocation facts and evidence hashes to
EOS. It does not publish employee salary or employee-level cost lines through
the general P&L API.

W60 privacy must prevent ordinary PM, PA, or executive views from deriving a
person's pay through small samples, repeated filters, differences between
queries, or Project membership changes. Small-cell suppression, minimum
aggregation, authorization scope, and query-shape controls belong to `S7-03`.

### W60-CA01-ADR-05: Attribute Material At Purchase And Recognize Cost At Consumption

A raw-material purchase commonly posts inventory and payable entries. The
purchase amount is not Project P&L cost while it remains an asset. Material
cost becomes eligible when an admitted event establishes economic
consumption, issue, impairment, disposal, or another expense recognition.

The absence of expense recognition must not make purchased material invisible
to Project management. A purchase, receipt, or admitted acquisition event must
therefore create a separate **material commitment/inventory attribution**
view when one or more target Projects are known:

- a Project-specific purchase is attributed entirely to that Project;
- a shared purchase may be attributed by an approved quantity, ratio, BOM, or
  another governed planning basis;
- the portion without an approved target remains explicit
  `UNASSIGNED_INVENTORY`; and
- the accountable Project on the purchase Journal remains source lineage and
  must not be mistaken for all target Project commitments.

Purchase-time attribution is not an allocation of recognized expense and must
not enter `eos_cost_source_pool` merely to reuse the W50 cost-allocation path.
It is a Project cost commitment and inventory-visibility authority. The
physical persistence is decided by the implementation source audit, but the
logical authority must preserve at least:

- tenant, company, acquisition/purchase/receipt source reference and hash;
- item or material reference and, when available, lot/cost-layer reference;
- target Project UUID and human-facing Project Code;
- attributed quantity, attributed acquisition amount, currency, and basis;
- assigned, unassigned, consumed/released, returned, and adjusted amounts;
- evidence and policy revision hashes; and
- idempotency, event, and reconciliation lineage.

The narrow W60 inventory boundary is Project commitment visibility and
consumption reconciliation. It is not a full warehouse or inventory-valuation
SoR.

The target lineage is:

```text
Purchase Journal
  -> receipt / inventory lot or cost layer
  -> approved Project issue or consumption event
  -> recognized expense Journal component
  -> CostSourcePool
  -> allocation batch and lines where shared
  -> Project P&L projection
```

Non-stock consumables or services that are validly expensed at Posting may be
recognized directly or allocated immediately under the approved policy.
Inventory purchases must not be allocated directly from the payable or asset
line merely to accelerate P&L.

When consumption occurs, its Project attribution and actual valued cost are
reconciled against the remaining purchase-time commitment. The transition
must decrease remaining commitment and increase confirmed actual cost without
double counting. Partial consumption preserves the remaining attributed or
unassigned inventory. Return, cancellation, price variance, quantity variance,
and valuation differences remain explicit rather than rewriting the original
purchase attribution.

For each admitted acquisition or material cost layer, the management
conservation boundary is:

```text
acquired material value
  = consumed actual value
  + remaining Project-attributed inventory value
  + unassigned inventory value
  + returned / valuation-adjustment value
```

The exact valuation method is outside W60, but unexplained residue is not
allowed. A source adapter that cannot provide authoritative valuation marks
the material state pending or stale rather than inventing a cost.

### W60-CA01-ADR-06: Reserve BOM As Approved Planning Evidence

A governed and revisioned BOM may later provide:

- planned material quantities by product, Project, or work code;
- a deterministic allocation driver for shared material consumption;
- expected-versus-actual material variance; and
- evidence for `APPROVED_PLAN` before actual issue data is available.

BOM does not by itself prove that inventory was consumed. Confirmed material
actual requires an admitted issue/consumption or equivalent accounting
recognition event. BOM-based amounts remain plan, forecast, or provisional
until reconciled with actual consumption.

The material lifecycle therefore has three deliberately separate stages:

1. `BOM_FORECAST`: expected quantity/value without acquisition or consumption;
2. `MATERIAL_COMMITTED` or `INVENTORY_ATTRIBUTED`: purchased/received material
   assigned to a Project but not yet consumed; and
3. `POSTED_DIRECT` or `POSTED_ALLOCATED`: consumed and recognized actual cost.

Moving from one stage to the next releases the earlier remaining amount. The
three stages are never summed as three independent actual costs.

Manufacturing BOM authority, inventory valuation, lot/cost-layer handling,
yield, scrap, substitutions, work-in-process, and production-order integration
are deferred to a later controlled Wave. W60 only preserves compatible
`basis_source_ref`, `basis_source_hash`, `USAGE`, `APPROVED_PLAN`, Project, and
work-code boundaries.

### W60-CA01-ADR-07: Separate Confirmed, Provisional, Stale, And Unallocated

P&L output must never present missing or provisional economic facts as zero or
confirmed actual. At minimum it distinguishes:

| Classification | Meaning |
| --- | --- |
| `POSTED_DIRECT` | Eligible and reconciled POSTED component recognized directly once |
| `POSTED_ALLOCATED` | Committed and reconciled management-allocation line |
| `UNALLOCATED` | Eligible amount not yet assigned to a target Project |
| `POSTED_LABOR_ALLOCATED` | Payroll-expense subtype allocated from approved actual effort and included in confirmed actual |
| `POSTED_PAYROLL_UNALLOCATED` | POSTED eligible payroll expense without completed Project allocation |
| `LABOR_ALLOCATION_PROVISIONAL` | Payroll expense allocated from approved plan rather than closed actual work evidence |
| `PLANNED_LABOR` | Planned rate/Man-Day forecast; not POSTED payroll actual |
| `UNALLOCATED_LABOR_OVERHEAD` | Paid non-Project or unexplained labor retained explicitly under policy |
| `LABOR_ADJUSTMENT` | Append-only correction caused by later payroll or work-evidence revision |
| `MATERIAL_COMMITTED` | Purchased/received inventory attributed to a Project but not consumed; Project Cost Outlook only |
| `UNASSIGNED_INVENTORY` | Purchased/received inventory without an approved target Project; visible exception, not hidden common cost |
| `BOM_FORECAST` | Governed expected material requirement; neither acquired inventory nor actual cost |
| `PROVISIONAL` | Approved plan-based allocation awaiting actual evidence |
| `APPROVED_NOT_POSTED` | Approved business amount without confirmed GL Posting |
| `PLANNED_BUDGET` | Approved budget authority, never actual |
| `FORECAST` | Governed forward-looking value, never actual |
| `RECONCILIATION_PENDING` | Source or allocation exists but is not verified |
| `PROJECTION_STALE` | Projection watermarks lag an admitted source event |

Confirmed Project actual uses only `POSTED_DIRECT` and reconciled
`POSTED_ALLOCATED` values, including governed append-only adjustments. The API
may identify an admitted labor subtype as `POSTED_LABOR_ALLOCATED`, but that
subtype is not an additional amount beside `POSTED_ALLOCATED`. The API returns
payroll unallocated, labor provisional/plan/overhead, material commitment,
unassigned inventory, BOM forecast, unallocated, stale, and pending values
separately.

The user-facing read model may expose a **Project Cost Outlook** containing
confirmed actual plus remaining admitted commitments. It must label its
components and must not present that outlook as financial P&L actual.

### W60-CA01-ADR-08: Build A Rebuildable Watermark-Aware Projection

Project P&L must not perform a full join over Journals, pools, batches, lines,
budgets, and Projects for every request. W60 adds an EOS-owned,
rebuildable projection optimized for Project and period reads.

The minimum projection identity is:

```text
tenant_id
company_id
project_id
accounting_period_id
projection_version
classification and reporting dimension
```

The projection preserves at least:

- human-facing `project_code`;
- reporting account/category and `source_kind`;
- functional currency;
- direct, allocated, unallocated, provisional, budget, revenue, and expense
  amounts as distinct fields or typed rows;
- committed material, unassigned inventory, BOM forecast, consumed material,
  and material variance as distinct fields or typed rows;
- allocated labor, unallocated payroll, provisional/plan labor, labor
  overhead, and labor adjustment as distinct fields or typed rows;
- `as_of`;
- `posting_watermark`;
- `allocation_watermark`;
- `payroll_evidence_watermark` and `labor_effort_watermark` when those facts
  are admitted;
- `material_commitment_watermark` when purchase/receipt attribution facts are
  admitted;
- budget/projection revision where applicable;
- reconciliation and staleness status; and
- source-count or lineage-query reference sufficient to drill down without
  copying private source detail into the projection.

The projector consumes admitted Posting, PayrollPostingEvidence,
LaborEffortSnapshot, allocation commit/adjustment, material
acquisition/attribution/consumption, and budget revision facts idempotently.
Restart, duplicate event delivery, ACK loss, and rebuild must converge to the
same projection. Projection corruption is repaired by replay/rebuild from
authoritative records, not by editing GL, payroll/effort evidence, inventory
evidence, or allocation truth.

### W60-CA01-ADR-09: Optimize For Project And Period Reads

The physical design must prioritize the primary business question: current
and period Project P&L. Index design must support at least:

- one Project over one or more accounting periods;
- all authorized Projects in a company and period;
- Project Code resolution without exposing UUID as the primary business key;
- stale/unallocated/reconciliation work queues; and
- controlled source-line drill-down.

Table and index names must remain within PostgreSQL identifier limits. Exact
normalization and the migration number are decided by the `S7-02` source audit,
not by this document. The implementation must recheck the current migration
head and must not reuse historical reservation `2527`.

### W60-CA01-ADR-10: Preserve Service Ownership And Authorization

- EOS owns GL, source eligibility, allocation, budget, and Project P&L facts.
- OA owns authorization decisions for Project and company scope.
- WC owns Human approval workflow where a policy, basis, or adjustment
  requires approval.
- MyBee is a governed consumer and never writes EOS projection tables.
- Project Code is the user-facing identifier; UUID remains internal relational
  lineage.
- Project membership does not grant payroll detail or allocation-policy
  authority.
- Remote generation, embedding, and reranking providers are not required for
  deterministic W60 accounting acceptance.

## 5. Canonical Payroll Flow

```text
1. HR/payroll SoR closes attendance, leave, tax, and payroll calculation and
   produces an approved PayrollRun.
2. A company- or organization-level Payroll Journal becomes POSTED and
   reconciled.
3. PayrollPostingEvidence maps the PayrollRun to exact eligible expense
   Journal components; liability, withholding, cash, and balancing components
   remain excluded.
4. Eligible payroll-expense components enter CostSourcePool.
5. Protected actual-work evidence closes into an approved
   LaborEffortSnapshot, or an approved plan is selected explicitly as a
   provisional fallback.
6. Non-Project paid time and residual labor receive an explicit operating,
   indirect-overhead, or unallocated policy treatment.
7. A hash-bound AllocationPlan revision is released.
8. Deterministic allocation produces one committed batch and immutable lines.
9. Project P&L projector consumes confirmed, provisional, and unallocated
   labor classifications without exposing employee pay.
10. Later work/payroll correction creates a new evidence and plan revision
    plus append-only adjustment; prior GL and allocation history remain
    unchanged.
```

The source period, payroll period, work-evidence period, and accounting period
must be explicit. A late timesheet or payroll correction cannot silently move
cost between closed periods.

Before Payroll Posting, planned labor may appear only as forecast or budget.
When POSTED payroll actual arrives, the projection replaces or compares the
corresponding forecast; it never adds both values as two actual costs.

## 6. Canonical Material Flow

```text
1. BOM or another governed plan may establish a material forecast.
2. Purchase and receipt establish payable, inventory, quantity, and source
   lineage.
3. Known Project targets receive material commitments; the remainder becomes
   explicit unassigned inventory.
4. Inventory remains a balance-sheet asset and does not enter actual Project
   P&L while it is unconsumed.
5. Approved issue/consumption identifies quantity, Project/work target, and
   inventory/cost-layer lineage.
6. Expense recognition creates or identifies the eligible POSTED component.
7. Consumption releases the corresponding commitment; direct consumption is
   recognized once against its Project and shared consumption enters a USAGE-
   or approved-plan-based allocation.
8. The projection exposes actual P&L, Project Cost Outlook, remaining
   commitment, unassigned inventory, forecast, and variance separately.
```

If a later manufacturing design introduces production order, WIP, yield, or
scrap, those authorities extend the forecast, acquisition, and consumption
stages without changing the immutable GL and allocation invariants.

Purchase-time attribution and consumption-time recognition may differ because
of partial issues, returns, substitutions, weighted-average/FIFO valuation,
price variance, or quantity variance. The system reconciles the difference; it
does not copy the original purchase amount into actual P&L without evidence.

## 7. Corrected W60 Slice Boundary

| Order | Slice | Required closure |
| --- | --- | --- |
| 1 | `W60-CA01` Project P&L Projection and Management Allocation Entry Reconciliation | This design closure, source-backed migration refresh, Payroll-to-Project/material commitment/BOM boundary, projection and privacy entry decision |
| 2 | `S7-02` Project P&L Query/Projection and Watermark | EOS projection persistence, payroll evidence/effort and material commitment/outlook contracts, idempotent projector/rebuild, direct/allocation exclusivity, typed status, API/MyBee consumer, actual PostgreSQL smoke |
| 3 | `S7-03` Executive P&L Security and Small-Cell Inference Prevention | fresh OA scope, Project/company access, payroll suppression, filter/difference-attack denial, actual PostgreSQL protected smoke |

`S7-04` NVT rollup and Project-close unsettled checks remain in W84. W60 may
provide an authorized company/group summary only when it cannot duplicate
Project facts or weaken the later NVT hierarchy contract.

HR/payroll, purchasing, inventory movement, and manufacturing source adapters
remain outside W60. W60 nevertheless fixes the PayrollPostingEvidence,
LaborEffortSnapshot, Project labor allocation, Project material commitment,
unassigned-inventory, consumption-release, and P&L projection contracts. Their
later implementation must feed those contracts rather than create a separate
P&L truth.

## 8. Minimum Acceptance Matrix

W60 cannot close unless all of the following are proven:

1. no second GL or duplicate management-journal authority is created;
2. every confirmed P&L component resolves to exact immutable source lineage;
3. direct and management-allocation paths are mutually exclusive;
4. `E = D + A + U` remains exact after projection and rebuild;
5. payroll allocation uses approved actual work first and labels plan fallback
   as provisional;
6. Project membership alone never becomes a Man-Day or cost ratio;
7. company-wide and organization-level payroll Journals both map exact
   eligible expense components to one PayrollRun lineage;
8. payroll liabilities, withholding, net pay, cash, advances, and balancing
   lines do not create duplicate Project labor cost;
9. paid leave, training, bench, administration, and residual labor receive an
   explicit operating, overhead, or unallocated treatment;
10. planned labor and POSTED payroll are never summed as two actual costs;
11. individual salary and small-cell payroll inference are denied;
12. payroll/effort correction uses a new immutable evidence revision and
    append-only allocation adjustment;
13. payroll period, effort period, and accounting period remain explicit and
    cannot drift silently;
14. inventory purchase does not become Project expense before admitted
   consumption/recognition;
15. purchase-time Project material commitment is visible without entering
   confirmed actual P&L;
16. unknown target material remains explicit `UNASSIGNED_INVENTORY` rather
    than disappearing into an opaque common-cost balance;
17. consumption releases commitment and creates actual cost exactly once;
18. acquisition value reconciles to consumed, remaining attributed,
    unassigned, returned, and valuation-adjustment values without unexplained
    residue;
19. BOM evidence cannot masquerade as acquisition or actual consumption;
20. confirmed, committed, unassigned, provisional, unallocated, pending,
    stale, budget, and forecast values remain distinguishable;
21. duplicate/reordered events, ACK loss, restart, and full rebuild converge to
    identical projection values and watermarks;
22. late evidence or correction uses append-only adjustment lineage;
23. closed-period and cross-period corrections fail closed or follow an
    explicitly governed adjustment period;
24. user-facing reads use Project Code while preserving internal UUID lineage;
25. unauthorized, cross-tenant, cross-company, inactive-scope, and stale-token
    reads fail closed;
26. actual EOS/OA PostgreSQL protected smoke proves the persisted boundary;
27. projection query/index plans are recorded for the primary Project-period
    reads; and
28. Repository gates pass with zero test residue.

## 9. Explicit Non-Goals

W60 does not implement:

- HR master, attendance, leave, tax, payroll calculation, payslip,
  withholding, or employee-payroll SoR beyond the narrow
  PayrollPostingEvidence/LaborEffortSnapshot bridge fixed here;
- actual timesheet/work-log product ownership or employee-facing attendance
  workflow;
- full purchasing, warehouse movement, available-to-promise, inventory
  valuation, or lot-accounting product ownership beyond the narrow Project
  material commitment/consumption projection fixed here;
- BOM, MRP, production order, WIP, yield, scrap, or manufacturing costing;
- NVT hierarchy rollup or Project-close blocking, which remains `S7-04`/W84;
- GL cost-transfer activation;
- a second management GL;
- model-generated allocation ratios; or
- direct MyBee writes to EOS financial/projection tables.

## 10. Rollback And Compatibility

- W40 PostedJournal and W50 allocation/budget authorities remain unchanged.
- The P&L projection is additive and rebuildable. Disabling or rebuilding it
  does not delete GL, source pool, allocation, adjustment, or budget truth.
- Existing direct and management-allocation records retain their hashes and
  identifiers.
- A projector defect stops or marks the projection stale; it never fabricates
  zero, modifies a Journal, or retries a financial write.
- A future BOM/inventory adapter must enter through approved source and
  evidence contracts, preserving compatibility with existing Project P&L
  rows and lineage queries.
- A future HR/payroll adapter must enter through PayrollPostingEvidence and
  LaborEffortSnapshot. It cannot write employee pay into general Project P&L
  tables or bypass exact Journal-line reconciliation.
- Purchase-time material commitment persistence is additive and cannot mutate
  PostedJournal or convert an asset line into expense. A projector rollback
  may rebuild commitments and outlook, but it cannot erase acquisition or
  consumption evidence.

## 11. Closure Statement

```text
W60-CA01 design reconciliation = CLOSED
W60 runtime implementation     = NOT STARTED BY THIS DOCUMENT
first implementation Slice     = S7-02
```

W60 implementation may begin with `S7-02` after this document is reviewed and
committed. No Slice may duplicate the W50 allocation ledger, recognize
inventory purchases as consumed material cost, hide purchased material that
is attributed or unassigned, equate membership with effort, duplicate payroll
expense through liability/net-pay components, or publish provisional payroll
allocation as confirmed Project actual.
