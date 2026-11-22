# W60-S7-02C Payroll Project Allocation, Residual Labor, and Adjustment Integration

## Decision

`W60-S7-02C` connects the approved payroll and labor evidence introduced by
S7-02B to the existing EOS management-allocation authority and Project P&L
projector. It does not create a second management ledger or a second cost
allocation engine.

The implementation reuses:

- `eos_cost_source_pool` as the exact eligible POSTED payroll-expense source;
- `eos_cost_allocation_plan` and its lines as approved allocation authority;
- `eos_cost_allocation_batch` and its immutable lines for the initial
  deterministic allocation;
- `eos_cost_allocation_adjustment` for append-only late corrections; and
- the rebuildable `eos_project_pnl_projection` read model.

The new `eos_payroll_project_alloc` table is a narrow immutable lineage link.
It binds PayrollPostingEvidence, LaborEffortSnapshot, AllocationPlan, committed
batch, residual policy, revision, and supersession identity without storing
employee salary or employee-level payroll facts.

## Allocation and Residual Policy

Allocation admission is fail-closed. Payroll evidence must be reconciled, the
labor snapshot and plan must be approved, the plan must be a PAYROLL plan, and
every Project, WorkCode, basis unit, deterministic ratio, eligibility hash,
period, and released policy hash must match.

Actual approved effort creates a `CONFIRMED` allocation. Approved-plan
fallback creates a `PROVISIONAL` allocation and cannot be represented as
confirmed Project actual.

Residual labor has one explicit governed treatment:

- `RETAIN_UNALLOCATED`: preserve the monetary residue as
  `POSTED_PAYROLL_UNALLOCATED`;
- `ALLOCATE_INDIRECT_OVERHEAD`: include residual effort in the approved
  allocation basis; or
- `OPERATING_PROJECT`: allocate residual effort to an active governed Project
  whose UUID and Project Code both match EOS authority.

No residual may disappear into an implicit common-cost balance.

## Correction and P&L Semantics

Late actual effort or payroll correction appends a new allocation revision.
It never mutates the committed batch, its lines, prior evidence, or prior
allocation link.

- plan fallback to actual is `PROVISIONAL_TO_ACTUAL`;
- later actual correction is `ACTUAL_CORRECTION`;
- a confirmed allocation cannot regress to provisional;
- replacement snapshots must have a later revision; and
- stale predecessor, semantic replay conflict, or broken conservation fails
  closed.

Adjustment deltas are stored in the existing allocation-adjustment table and
are included in confirmed `posted_allocated_cost` through the
`LABOR_ADJUSTMENT` classification. The projector suppresses replaced
provisional values, follows a contiguous revision chain, and requires exact
conservation between current Project amounts and explicit residual.

Payroll evidence, labor effort, and allocation watermarks now participate in
the projection hash and freshness boundary.

## Persistence and Runtime

Migration `2545_eos_payroll_project_allocation.sql`:

- adds `eos_payroll_project_alloc`;
- extends `eos_cost_allocation_adjustment` with optional payroll lineage;
- preserves append-only database triggers;
- updates the P&L component semantics so governed labor adjustments contribute
  to confirmed allocated cost; and
- keeps every table, index, trigger, and constraint name within PostgreSQL's
  identifier limit.

The canonical EOS dependency factory composes
`EosPayrollProjectAllocationService` from the existing cost-allocation service,
business transaction coordinator, and the new narrow repository. No public
HTTP contract or remote model provider is introduced by this Slice.

## Verification

Focused allocation, projector, and persistence regression:

```text
tests = 127 passed
payroll allocation module coverage = 96%
projector module coverage           = 99%
```

Adjacent SourcePool, AllocationPlan, allocation, payroll bridge, Project P&L,
projector, and EOS service-skeleton regression:

```text
tests = 326 passed, 1 protected-smoke skip
```

Protected PostgreSQL smoke used the actual `nex_eos_test` database and an
isolated schema. It:

1. applied all EOS migrations through `2545`;
2. created a governed VoucherCandidate and atomic POSTED Journal;
3. admitted a PAYROLL SourcePool and PayrollPostingEvidence;
4. admitted two approved actual LaborEffortSnapshot revisions;
5. committed and exactly replayed an initial allocation with explicit residue;
6. appended and exactly replayed an actual correction that removed the
   residue;
7. rebuilt Project P&L with the corrected confirmed amount and payroll/labor
   watermarks;
8. proved the allocation append-only trigger rejects mutation; and
9. dropped the isolated schema and confirmed zero residue.

```text
protected PostgreSQL smoke = 1 passed
```

Final EOS Slice Gate:

```text
tests                 = 2136 passed, 61 protected-smoke skips
statement coverage    = 96.94%
branch coverage       = 95.18%
gate commands         = 5/5 passed
contract validation   = pass
transition audit      = pass
dependency audit      = pass
```

The final branch result preserves the preceding S7-02B baseline. Coverage
includes the case where a later labor adjustment introduces a Project that was
not present in the original confirmed allocation. The known non-blocking
Starlette/httpx deprecation warning remains in the UI/UX compatibility backlog.

Remote generation, embedding, and reranking providers were not used.

## Closure

```text
W60-S7-02C Payroll Project Allocation, Residual Labor,
and Adjustment Integration = PASS / CLOSED
```

Material commitment, inventory consumption, and material variance integration
remain subsequent W60 work.
