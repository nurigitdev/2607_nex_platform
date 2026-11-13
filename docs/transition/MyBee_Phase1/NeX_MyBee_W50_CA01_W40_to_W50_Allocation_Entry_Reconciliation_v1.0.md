# NeX MyBee W50-CA01: W40-to-W50 Allocation Entry Reconciliation v1.0

## 1. Status And Authority

- Decision date: `2026-11-13`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `c3fd7943`
- Runtime code changes by this document: none

This controlled amendment reconciles the completed W40 immutable Posting
foundation with the planned W50 cost-allocation and budget foundation. It is a
narrow source-backed entry decision and does not rewrite the frozen PAD, SRS,
or v1.2 Slice Plan except where current source, migration inventory, mandatory
Project attribution, or allocation accounting requires a more precise rule.

Where an earlier document can be read as allowing a nullable, synthetic, or
unapproved Project merely because a cost will later be allocated, this
amendment takes precedence. Where an earlier migration reservation conflicts
with the current repository inventory, this amendment also takes precedence.

## 2. W50 Entry Decision

W50 may begin after this amendment because its runtime prerequisites are now
closed:

1. W40 PostedJournal creation, atomic Posting, exact replay, outbox recovery,
   and UNKNOWN commit reconciliation are complete.
2. Every new MyBee accounting Journal line retains a non-null approved Project
   UUID and human-facing Project Code.
3. PostedJournal header and lines are immutable and insert-only.
4. S1-06 Project WorkAssignment and Grade/Man-Day planning readiness exists.
5. EOS, OA, WC, and AE actual PostgreSQL protected smoke passed with
   `34 passed, 0 skipped`.
6. The Repository Full Gate passed with statement coverage `96.73%` and branch
   coverage `95.89%`.

W50 is therefore authorized to add allocation and budget authorities around
the immutable GL. It is not authorized to mutate or replace the GL.

## 3. Source-Backed Current State

| Boundary | Confirmed source state | W50 consequence |
| --- | --- | --- |
| Migration inventory | EOS currently ends at `2540_eos_atomic_journal_posting.sql` | Historical W50 reservations `2525/2526` cannot be reused |
| PostedJournal | `eos_journal_header` and `eos_journal_line` are immutable POSTED truth | Allocation references exact Journal lineage and never updates it |
| Project attribution | Each Journal line has non-null `project_id` and 11-character `project_code` | Presence of a Project alone must not imply final direct-cost recognition |
| Posting recovery | Business operation, idempotency, outbox, and reconciliation are authoritative | Allocation consumes only a confirmed committed Journal |
| Work evidence | Project WorkAssignment and approved planning inputs exist | Allocation plans may bind admitted evidence snapshots |
| Cost allocation | No active EOS cost source pool, allocation plan, batch, or line module exists | `S6-01` through `S6-03` remain new implementation |
| Budget | No active EOS budget authority or Project budget binding exists | `S7-01` remains new implementation |
| Product topology | EOS is the financial SoR; MyBee is a governed consumer | MyBee must not own an allocation ledger or write EOS tables directly |

## 4. Normative Decisions

### W50-CA01-ADR-01: Preserve Mandatory Project Attribution

`eos_journal_line.project_id` and `project_code` remain mandatory. Allocation
does not make them nullable and does not replace them with company-only scope.

The Project on a Journal line is the accountable source Project for Posting
and traceability. For a direct cost it is also the final management-cost
Project. For a shared cost it may be the real approved Project responsible for
the source transaction while a later allocation distributes management cost
to one or more target Projects.

The source Project must be a real approved Project visible through its Project
Code. A hidden synthetic Project, arbitrary UUID, inactive Project, or null
Project is prohibited. An `OPERATING` Project is usable only when it is a real
governed Project created and approved through the canonical Project lifecycle.

### W50-CA01-ADR-02: Separate Posting Attribution From P&L Recognition Role

Project presence on the Journal line is not enough to decide how the amount is
recognized in management P&L. W50 persists an explicit source classification
and allocation mode derived from approved accounting policy:

| Classification | Management treatment |
| --- | --- |
| `DIRECT` | Recognize the eligible amount once against the Journal line Project |
| `MANAGEMENT_ALLOCATION` | Do not also recognize the source Project as direct cost; recognize finalized allocation lines and retain any unallocated balance separately |
| `INELIGIBLE` | Exclude the line from Project cost allocation |
| `GL_COST_TRANSFER` | Reserved for a later governed GL-transfer option; not active in W50 |

The classification must be stored with the source-pool snapshot. It must not
be inferred later only from account number, Project presence, or an LLM
response.

### W50-CA01-ADR-03: Enforce One Recognition Path Per Source Component

For each tenant, company, source Journal line, eligible cost component,
currency, and accounting period, exactly one management-recognition path is
allowed. The conservation equation is:

```text
eligible recognized source amount (E)
  = direct recognized amount (D)
  + finalized allocated amount (A)
  + explicit unallocated amount (U)
```

`E = D + A + U` must hold at the approved currency scale with zero unexplained
residue. A source component cannot be both direct and allocated. A
`GL_COST_TRANSFER` source cannot also contribute a management-allocation
amount to Project P&L.

### W50-CA01-ADR-04: Admit Only Eligible POSTED GL Components

An allocation source is admitted only when:

- the business operation and Journal reconciliation outcome are
  `COMMITTED_CONFIRMED` and `VERIFIED`;
- the Journal, line, account-policy release, company, period, currency,
  Project, and source-document lineage agree;
- the account and PostingRule identify an eligible recognized expense or
  signed correction component; and
- the source is not already bound to a conflicting source pool or recognition
  mode.

Cash, accounts payable, withholding, tax, asset, inventory, pure balance-sheet,
and balancing lines are not cost merely because they belong to the same
Journal. Inventory or assets become eligible only when a later admitted
consumption, impairment, disposal, or other recognition event establishes the
expense component. FX and signed negative components preserve their explicit
accounting direction and are never converted into an arbitrary positive pool.

### W50-CA01-ADR-05: Keep The GL Immutable

Source pools, plans, batches, and allocation lines reference the immutable
Journal and its hashes. They must not update or delete:

- `eos_journal_header`;
- `eos_journal_line`;
- AccountingApprovalAcceptance;
- the source BusinessOperation or idempotency record; or
- the committed Journal outbox event.

A policy change or corrected basis creates a new plan revision and a new
adjustment or reversal allocation lineage. It never edits an earlier finalized
allocation result. Journal reversal semantics remain governed by W80 and must
not be improvised inside W50.

### W50-CA01-ADR-06: Require Approved, Hash-Bound Allocation Plans

An allocation plan contains a versioned and hash-bound basis snapshot. The
allowed evidence priority is:

1. admitted actual work or usage evidence;
2. approved Project plan, WorkAssignment, or business BOM;
3. admitted person, seat, facility, equipment, or license driver;
4. an explicitly approved fixed ratio with recorded reason and authority.

An LLM may assist an operator in finding or explaining evidence, but it cannot
invent an allocation ratio or approve a plan. Plan release requires the
existing BUSINESS_FORMAL approval boundary and fresh OA authorization for the
exact tenant, company, policy, source scope, and action.

### W50-CA01-ADR-07: Make Allocation Deterministic And Replay-Safe

Allocation uses `Decimal` at the admitted currency/accounting scale. Rounding
residue uses a documented deterministic largest-remainder rule followed by a
stable Project Code and Project UUID tie-break. Identical source, plan,
evidence snapshot, policy revision, and idempotency identity must produce the
same batch, lines, hashes, and totals.

The implementation must prove:

- one batch under at least 20 concurrent identical requests;
- exact replay returns the same logical result;
- changed source, ratio, policy, evidence, Project set, or payload hash returns
  conflict with zero additional allocation mutation; and
- a partial transaction, ACK loss, worker restart, or outbox retry cannot
  create a second finalized batch.

### W50-CA01-ADR-08: Keep Budget Authority Separate From Actuals

`S7-01` establishes the approved Budget SoR and Project budget binding. Budget
amounts, forecasts, planned Man-Day rates, and unposted commitments are not
POSTED actuals. Actual-versus-budget reads must identify both authorities and
their `as_of` or revision metadata rather than merging them into one monetary
truth.

W50 does not build the final Project P&L projection. W60 consumes the W50
allocation and budget authorities and must preserve direct/allocation
exclusivity, watermark, OA scope, and privacy.

### W50-CA01-ADR-09: Preserve Authorization And Payroll Privacy

- EOS remains the financial and allocation SoR.
- OA remains the Project authorization-decision SoR.
- WC remains the Human approval workflow owner.
- MyBee remains a consumer and must not directly write EOS allocation tables.
- Project Code is the user-facing and authorization-facing identifier; UUID is
  internal relational lineage.
- Project membership alone does not grant allocation-policy approval.
- Individual payroll, actual salary, and small-cell inference remain hidden
  from ordinary PM/PA views. Approved Grade/Man-Day planning rates and actual
  private labor cost use separate projections and permissions.

### W50-CA01-ADR-10: Use Current Migration Inventory

The v1.2 plan's `2525_eos_cost_source_allocation.sql` and
`2526_eos_project_budget_master.sql` are historical reservations now occupied
by W10/W20 work. The source-backed W50 reservations are:

| Migration | Owner | Purpose |
| --- | --- | --- |
| `2541_eos_cost_source_allocation.sql` | `S6-01` through `S6-03` | source pools, allocation plan revisions, batches, lines, and immutable adjustment lineage |
| `2542_eos_project_budget_master.sql` | `S7-01` | approved budget authority and Project budget binding |

These are reservations, not proof that migrations exist or have been applied.
Every implementation Slice must recheck repository HEAD before creating or
modifying a migration. Table, constraint, and index names must remain within
PostgreSQL identifier limits.

## 5. Persistence Boundary

The implementation should use the minimum EOS-owned structures needed to
express the approved contracts:

| Authority | Minimum responsibility |
| --- | --- |
| Cost source pool | exact Journal-line/component lineage, eligibility, source Project, recognition mode, eligible amount, currency/period, source hash |
| Allocation plan | immutable revision, basis kind, evidence snapshot hash, target Projects, ratios/quantities, approval proof, effective scope |
| Allocation batch | idempotent execution identity, source-set hash, plan revision, lifecycle state, totals, reconciliation proof, operation identity |
| Allocation line | target Project Code/UUID, work code where known, basis, allocated amount, rounding component, source record reference |
| Allocation adjustment | append-only correction/reversal linkage without rewriting finalized history |
| Budget authority | approved budget revision and Project binding, separate from POSTED actuals |

The exact normalized table split is decided after the `S6-01` source audit.
The implementation must not collapse source, plan, execution, and result into
one mutable table merely to reduce table count.

## 6. Corrected W50 Slice Order

| Order | Slice | Required closure |
| --- | --- | --- |
| 1 | `S6-01` POSTED GL SourcePool Eligibility | `2541` foundation, exact source lineage, recognition classification, uniqueness, actual EOS PostgreSQL smoke |
| 2 | `S6-02` Allocation Plan Release And Policy | approved evidence hierarchy, immutable plan revision, OA/WC authorization, policy hash, fail-closed API |
| 3 | `S6-03` Deterministic Allocation Batch And Reconciliation | concurrency, replay/conflict, conservation, rounding, adjustment lineage, outbox/restart recovery |
| 4 | `S7-01` Budget SoR And Project Budget Binding | `2542` foundation, approved revision, Project binding, budget/actual separation, W50 closure |

Remote generation, embedding, and reranking providers are not required for
W50. Deterministic accounting logic and authoritative PostgreSQL state are the
acceptance boundary.

## 7. Gate Sequence

1. `S6-01`: focused tests, contract validation, actual EOS PostgreSQL migration
   and source-admission smoke.
2. `S6-02`: actual EOS/WC/OA PostgreSQL approval and denial smoke, then W50
   Checkpoint Gate.
3. `S6-03`: actual EOS PostgreSQL concurrency, replay, restart, outbox, and
   zero-residue smoke; escalate immediately on a conservation defect.
4. `S7-01`: actual EOS PostgreSQL budget revision/concurrency smoke followed
   by the Repository Full Gate.

Every Slice is implemented, tested, committed, and synchronized independently.
An important semantic conflict or migration collision stops the sequence.

## 8. Minimum Acceptance Matrix

W50 cannot close unless all of the following are proven:

1. only confirmed POSTED eligible components enter the source authority;
2. non-cost balancing, tax, liability, asset, and inventory lines are denied;
3. source Project Code is real, approved, tenant-correct, and preserved;
4. direct and management-allocation recognition are mutually exclusive;
5. `E = D + A + U` holds exactly by source component, company, period, and
   currency;
6. three or more target Projects preserve the total through deterministic
   rounding;
7. duplicate source-pool admission and conflicting plan/batch replay fail
   closed;
8. 20 concurrent identical executions produce one finalized batch;
9. exact replay returns the original result without duplicate outbox effects;
10. policy or evidence changes create a new immutable revision rather than
    editing prior history;
11. allocation cannot mutate PostedJournal or accounting acceptance rows;
12. stale, rejected, revoked, cross-tenant, inactive-Project, and unauthorized
    approval paths produce zero allocation mutation;
13. budget revision is distinct from POSTED actual and allocation facts;
14. service restart resumes pending work without loss or duplicate allocation;
15. user-facing and authorization surfaces use Project Code without exposing
    internal UUID as the primary business identifier;
16. payroll/privacy negative tests prevent personal-cost and small-cell
    inference; and
17. actual PostgreSQL protected smoke and the final Repository Full Gate pass
    with zero test residue.

## 9. Explicit Non-Goals

W50 does not implement:

- final Project or NVT P&L projection and executive UI;
- P&L privacy/watermark policy, which belongs to W60;
- payroll and purchasing source adapters, which belong to `S6-04`/W81;
- GL reversal, FX remeasurement, settlement, or period close, which belong to
  W80;
- GL cost-transfer activation;
- manufacturing, inventory valuation, MRP, or tax automation;
- AI-generated allocation ratios or model-provider calibration; or
- direct MyBee writes to EOS financial tables.

## 10. Rollback And Compatibility

- W40 PostedJournal, accounting approval, reconciliation, and outbox contracts
  remain unchanged.
- Existing direct Project attribution remains readable and valid.
- W50 structures are additive and can be disabled without deleting GL truth.
- A failed allocation is retried or reconciled by its operation identity; it
  never triggers a replacement Journal Posting.
- Migration rollback in protected test schemas may remove only W50-owned
  structures. Production correction favors forward migration and append-only
  adjustment evidence.

## 11. Closure Statement

```text
W50-CA01 design reconciliation = CLOSED
W50 runtime implementation     = NOT STARTED BY THIS DOCUMENT
first implementation Slice     = S6-01
```

W50 implementation may begin with `S6-01` after this document is reviewed and
committed. No Slice may treat mandatory Journal Project attribution as proof
of direct-cost recognition, bypass allocation-plan approval, or duplicate the
immutable GL in an allocation ledger.

