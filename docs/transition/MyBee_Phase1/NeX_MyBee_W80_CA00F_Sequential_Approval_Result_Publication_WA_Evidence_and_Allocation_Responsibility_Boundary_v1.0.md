# NeX MyBee W80-CA00F Sequential Approval, Result Publication, WA Evidence, and Allocation Responsibility Boundary v1.0

**Status:** CLOSED / PROTECTED ACCEPTANCE PASS

**Predecessor:** W80-CA00E

**Boundary:** Business approval -> accounting approval -> governed Journal write
-> IA result publication -> WA evidence settlement; separate accounting allocation

**Database migration:** None planned. Reuse the existing EOS approval, Journal,
allocation, AE result/publication, and WA evidence/asset stores. If a source-fit
audit proves that evidence-only WA admission cannot be represented safely by
the current stores, implementation must stop for an explicit persistence
decision rather than add an implicit migration.

## 1. Purpose

The installed M1 journey proved the complete accounting spine, but it combined
several distinct business responsibilities into one acceptance request. The
journey prompt requested both an external-labor Journal and a fixed Project
allocation, the installed D04 completion path automatically ran allocation and
Project P&L refresh, and the resulting business card summarized the combined
outcome. This was useful vertical-spine evidence, but it is not the desired
operating boundary for ordinary employees and accounting staff.

W80-CA00F freezes the following product rules before W80 Journal-lifecycle work
begins:

1. business approval must complete before accounting approval is actionable;
2. the requester must receive the authoritative IA Workspace result without
   waiting for WA settlement;
3. an EOS VoucherCandidate, PostedJournal, or accounting ledger record is not a
   WA-owned business asset;
4. Project allocation is a separate accounting responsibility and operation;
5. Journal and allocation acceptance must be demonstrated by separate live
   journeys rather than one scenario-specific combined prompt.

The amendment preserves the current generalized Agent, WC, approval, NSL,
result, and evidence mechanics. It removes a product-composition coupling; it
does not create a second runtime pipeline.

## 2. Source-Backed Current State

### 2.1 Approval stages are persisted together but activated sequentially

EOS currently materializes every stage of an admitted approval policy when the
case is created. Stage one is persisted as `ACTIVE`; later stages are persisted
as `WAITING`. The scoped approval publisher creates a WC approval WorkItem only
for the case's current `active_stage_order`. After an approved decision, EOS
advances the case and publishes the next stage. A rejection terminates the case.

The installed Playwright journey also treats more than one simultaneously
pending approval gate as an error. Therefore the source does not currently
authorize parallel business and accounting decisions. The remaining risk is
projection and presentation ambiguity: a pre-created `WAITING` stage must never
look actionable in an API, approval inbox, diagnostic screen, or operator
report.

### 2.2 Result completion and WA settlement are related but distinct

IA Workspace publication persists the owner-scoped activity, acknowledges the
required delivery, and completes the IA execution in one AE transaction. WA is
notified only after that commit and is reconciled separately. For a background
PA execution, however, WA reconciliation may begin after WC WorkResult ACK and
before the resulting WC event has been restored into the originating IA
Workspace.

This ordering is acceptable for mandatory execution evidence but is not a
valid reason to present a voucher as a user-selected company asset. User result
delivery and evidence retention require separate policy decisions.

### 2.3 WA stores execution evidence, not accounting truth

The WA AgentResult adapter currently admits `AE_AGENT_RESULT` and supporting
`WC_WORK_RESULT` identities as hash-bound evidence and builds an
`AGENT_EXECUTION_RESULT` WorkAsset. The admitted record carries source IDs,
revisions, hashes, Agent identity, Project attribution, timestamps, and
classification. It does not own the VoucherCandidate or PostedJournal payload.

EOS remains the sole business system of record for accounting Candidates,
approval evidence, PostedJournals, allocation Batches, and Project P&L
projections. A rendered PDF, spreadsheet, report, or other explicit artifact
may become a WA asset, but the underlying accounting transaction does not move
to WA.

### 2.4 Journal completion is currently coupled to allocation

The M1 acceptance prompt explicitly asks for an external-service-cost Journal
and a fixed `40/60` Project allocation. The installed D04 controlled-write
outcome then invokes the financial result integrator, which runs allocation,
Project P&L refresh, and result lookup immediately after Journal success.

That coupling crosses responsibility boundaries:

- an employee may request a valid expense without authority to allocate it;
- allocation requires an approved plan and current accounting authority;
- allocation can occur at a later accounting period or after additional source
  evidence is available;
- retry and correction rules for Journal posting differ from allocation and
  Project P&L projection rules;
- one combined result obscures which operation succeeded or awaits accounting
  action.

## 3. Non-Goals

W80-CA00F does not:

- replace the current multi-stage approval engine;
- lazily invent an approval route after submission or discard the immutable
  pre-created approval-stage definition;
- make WA an accounting, approval, or workflow authority;
- require a user confirmation before mandatory compliance or execution evidence
  is retained;
- duplicate VoucherCandidate or PostedJournal payloads in WA;
- remove approved allocation, Project P&L refresh, or accounting tools;
- make an LLM decide an allocation ratio, approval authority, or accounting
  policy;
- add tenant-, Project-, ratio-, prompt-, or M1-specific runtime branches;
- change the NSL compiler/runtime or weaken EOS immutable Journal lineage;
- rewrite historical M1 evidence or existing WA records.

## 4. Sequential Approval Contract

### 4.1 Required state progression

The ordinary accounting flow is:

```text
BUSINESS_FORMAL stage 1 ACTIVE
  -> APPROVED
BUSINESS_FORMAL accounting stage ACTIVE
  -> APPROVED
NSL_WRITE gate ACTIVE
  -> APPROVED
governed EOS Journal mutation
```

`NSL_WRITE` is a governed-write checkpoint after human business and accounting
authority. It must not be presented as another business approval.

### 4.2 Activation and visibility rules

1. All route stages may be persisted at case creation for immutable policy
   evidence.
2. Only the exact current `ACTIVE` stage is actionable and publishable to WC.
3. `WAITING` stages are visible only as non-actionable route context to
   authorized users and operators.
4. Before business approval, the accounting approver inbox must contain no
   actionable request for the case.
5. Business rejection terminates the case and must not activate accounting or
   NSL WRITE.
6. Accounting rejection terminates the case and must not create a Journal
   write request.
7. Requester, business approver, and accounting approver SoD remains enforced.
8. Replay, restart, and ACK loss must not activate two stages or publish a
   duplicate approval WorkItem.

No new approval state machine is authorized unless focused source tests prove
that the current `ACTIVE/WAITING` mechanics cannot satisfy these rules.

## 5. IA Result Publication and WA Boundary

### 5.1 Authoritative requester result

The requester-facing completion barrier is the owner-scoped IA WorkspaceResult
publication. The Workspace result must contain safe business references and a
user-facing summary of what was committed, rejected, or deferred. It must not
wait for WA availability or a user asset-retention choice.

For a delegated PA result, the required sequence is:

```text
PA AgentResult
  -> WC WorkResult ACK
  -> generalized result event and IA resume
  -> IA AgentResult finalization
  -> IA WorkspaceResult ACK
  -> requester-visible result
```

WA evidence reconciliation may proceed independently once its authoritative
source completion barrier is satisfied. A WA retry or outage cannot roll back
or hide an already published IA result.

### 5.2 Mandatory evidence versus optional asset

Two retention classes are fixed:

| Class | Behavior | User confirmation |
| --- | --- | --- |
| Execution/compliance evidence | Hash-bound AE/WC/EOS lineage retained automatically in WA | Not required |
| User-curated artifact | Rendered PDF, spreadsheet, report, or other explicit artifact | Required unless a registered retention policy mandates it |

An optional `Save as company asset` action is permitted only after the result is
visible and only for a versioned artifact. It cannot transfer accounting truth
out of EOS or make WA settlement a prerequisite for IA completion.

## 6. Voucher, Journal, Evidence, and Asset Classification

The following ownership matrix is canonical:

| Object | Authoritative owner | WA treatment |
| --- | --- | --- |
| VoucherCandidate revision | EOS | Reference/hash evidence only |
| Business/accounting approval proof | EOS/WC according to existing boundary | Reference/hash evidence only |
| PostedJournal header/line | EOS | Reference/hash evidence only; never copied as WA business truth |
| Allocation Batch and line | EOS | Reference/hash evidence only |
| Project P&L projection | EOS | Reference/hash evidence only |
| AgentResult / WorkResult | AE/WC | Mandatory WA execution evidence after source completion |
| Rendered voucher receipt or report | AE artifact authority | Optional WA `HUMAN_OWNED_ARTIFACT` after explicit retention action or policy |

The implementation must audit whether the existing WA admission API can retain
mandatory evidence without presenting every evidence envelope as a user-facing
company asset. Existing `wa_work_evidence` and `wa_work_asset` stores must be
reused where possible. Historical `AGENT_EXECUTION_RESULT` assets remain valid;
no bulk rewrite is authorized.

## 7. Journal and Allocation Responsibility Split

### 7.1 Journal operation

An ordinary external-labor or service-cost request may include:

- company and primary Project attribution;
- transaction date, counterparty, amount, currency, and description;
- source document and attachment evidence;
- business and accounting approval context.

Its product completion boundary is:

```text
VoucherCandidate admitted and reviewed
  -> business approval
  -> accounting approval
  -> governed Journal write and verification
  -> PostedJournal receipt
  -> IA Workspace result
```

Journal completion may make an EOS source pool eligible according to existing
accounting rules. It must not automatically select an AllocationPlan, create an
AllocationBatch, refresh Project P&L, or claim that allocation completed.

### 7.2 Allocation operation

Allocation is a separate accounting WorkIntent and durable execution. It must:

1. be requested or accepted by a currently authorized accounting principal;
2. resolve an eligible, verified source pool from EOS;
3. resolve an approved allocation plan through the existing generic authority
   resolver;
4. execute allocation with conservation, replay, and reconciliation controls;
5. refresh only affected Project P&L projections;
6. publish its own IA or accounting-workspace result and evidence lineage.

If a non-accounting user includes allocation language in a Journal prompt, IA
may split the request, explain that allocation requires accounting action, or
delegate a separate accounting WorkItem. It must not silently execute the
allocation. An accounting-authorized user may request both outcomes, but the
runtime must still create two separately identifiable intents/operations with
separate authority and replay boundaries.

## 8. Compatibility and Retirement

1. Existing approval policies, instances, and stage records remain readable.
2. Existing VoucherCandidates, PostedJournals, AllocationBatches, P&L
   projections, AgentResults, WorkResults, and WA evidence remain valid.
3. The combined M1 live journey and its fixed allocation seed remain historical
   acceptance evidence only; they are not the canonical product UX after this
   amendment.
4. Generic allocation clients, resolvers, adapters, and EOS APIs remain active.
   Only automatic invocation from Journal completion is retired.
5. Existing result contracts may be read for compatibility. New Journal results
   must not assert allocation or P&L completion unless a separately identified
   allocation operation actually completed.
6. No test or product path may substitute fixture ratios, fixed Project counts,
   tenant dictionaries, or default Plan IDs for authoritative EOS data.

## 9. Recommended Implementation Slices

### W80-CA00F.1 - Sequential Approval Activation and Visibility Hardening

Audit EOS/WC/AE approval projections and UI inboxes. Preserve immutable route
materialization while proving that only the active stage is actionable. Add
business rejection, accounting rejection, replay, restart, ACK-loss, and SoD
coverage. No replacement approval engine is planned.

### W80-CA00F.2 - IA Result Publication and WA Evidence Boundary

Freeze IA WorkspaceResult as the requester-visible completion boundary. Verify
PA WorkResult-to-IA publication ordering, WA reconciliation independence, and
restart behavior. WA failure must not suppress an acknowledged IA result.

### W80-CA00F.3 - Voucher and WA Asset Classification Closure

Audit WA evidence and WorkAsset admission. Retain mandatory hash-bound execution
evidence, prevent VoucherCandidate/PostedJournal duplication, and expose an
optional post-result asset-retention action only for rendered artifacts. Prefer
existing WA tables and APIs; stop for a persistence decision if that boundary
cannot be represented without a migration.

### W80-CA00F.4 - Journal and Allocation Runtime Decoupling

Remove automatic allocation and P&L refresh from Journal controlled-write
completion. Preserve source-pool eligibility and the generic approved-plan
resolver. Add a separate accounting-authorized allocation orchestration and
ensure combined user prompts split into separately governed operations.

### W80-CA00F.4A - Independent Accounting Allocation Authority Lineage Closure

Replace the temporary D04-preparation dependency with a typed, hash-bound
accounting allocation WorkIntent and a fresh OA
`finance:allocation:execute` authority checkpoint. Bind each execution to its
own RuntimeJob, replay identity, and IA or accounting Workspace publication
target. The caller supplies approved Project codes and ratios; EOS resolves the
current ACTIVE Project UUIDs and APPROVED company bindings before selecting the
exact approved AllocationPlan. The pre-W80 UUID resolver and
`READY_FOR_D04` lineage remain readable only through an explicit historical
replay adapter. Reuse current allocation and P&L persistence; do not add a
scenario-specific table, default ratio, Project count, Plan ID, or database
migration.

### W80-CA00F.5 - Split Live Journeys and Protected Closure

Entry to this Slice is gated by
`W80-CA00F.5A: Accounting Allocation Product Entry and Domain Intent Activation
Closure`, which replaces direct harness construction with the admitted semantic
candidate, DomainIntentActivator, Product Coordinator, and common RuntimeJob
product path. Installed Journal acceptance also requires
`W80-CA00F.5B: Primary Project Code Typed Business Context Propagation Closure`,
which preserves the canonical Project identity through claimed-work
reconstruction without imposing Project scope on general queries.
Installed result rendering further requires
`W80-CA00F.5C: Installed Journal Business Result Summary and IA Projection
Closure`, which restores the typed user summary from product authorities and
the verified EOS result without creating a second publication pipeline.

Replace the canonical combined acceptance with two journeys:

1. an external-labor Journal journey ending at PostedJournal and IA result;
2. an accounting allocation journey starting from a verified source pool and
   approved AllocationPlan, ending at P&L refresh and its own IA/accounting
   result.

Run actual OA, AE, WC, EOS, and WA PostgreSQL; installed Compose services;
OpenBao trust; live generation; authenticated Playwright; restart/replay;
screen and diagnostic evidence; zero-residue cleanup; coverage gates; and the
Repository Full Gate.

## 10. Acceptance Matrix

The amendment closes only when all of the following are demonstrated:

1. only the business approver has an actionable gate immediately after submit;
2. accounting becomes actionable only after business approval;
3. business rejection produces no accounting or NSL WRITE gate;
4. accounting rejection produces no Journal mutation;
5. approval replay, restart, and ACK loss do not produce parallel active stages;
6. Journal success publishes a requester-visible IA result without waiting for
   WA settlement;
7. WA outage/retry does not remove or duplicate the IA result;
8. WA holds execution evidence and references, not a duplicate EOS Journal;
9. optional artifact retention occurs only after result visibility and explicit
   action or a registered retention policy;
10. the external-labor Journal journey creates no AllocationBatch and performs
    no Project P&L refresh;
11. a non-accounting allocation request is denied, split, or delegated without
    unauthorized execution;
12. a separately authorized allocation journey resolves authoritative EOS data,
    conserves source amounts, and refreshes only affected Projects;
13. exact replay creates no second Journal, AllocationBatch, AgentResult, or WA
    evidence record;
14. source scans find no fixed ratio, Project count, tenant mapping, or scenario
    value in product runtime code;
15. the two live journeys pass independently on exact head.

## 11. Stop Conditions

Implementation must stop and request a decision if it discovers that:

- accounting approval is actually published before business approval in a
  product path not covered by the current journey;
- the current WA schema cannot represent mandatory evidence independently from
  optional user-facing asset semantics;
- Journal and allocation cannot be separated without changing a public EOS or
  NSL contract;
- an existing consumer treats a combined allocation result as the only Journal
  success contract;
- separation would weaken immutable Journal lineage, approval SoD, Project
  authorization, replay safety, or accounting conservation;
- live acceptance would require scenario-specific runtime logic or fixture
  mutation after request submission.

## 12. Closure Criteria

```text
BUSINESS BEFORE ACCOUNTING APPROVAL       = REQUIRED
WAITING STAGE ACTIONABILITY               = FORBIDDEN
IA WORKSPACE RESULT DELIVERY              = AUTHORITATIVE REQUESTER BARRIER
WA EVIDENCE SETTLEMENT                     = DURABLE AND INDEPENDENT
VOUCHER/JOURNAL WA BUSINESS OWNERSHIP      = FORBIDDEN
OPTIONAL RENDERED ARTIFACT RETENTION       = EXPLICIT OR POLICY-DRIVEN
JOURNAL-TO-ALLOCATION AUTOMATIC COUPLING   = RETIRED
ALLOCATION ACCOUNTING AUTHORITY            = REQUIRED
JOURNAL AND ALLOCATION LIVE JOURNEYS       = SEPARATE
FIXTURE-SPECIFIC PRODUCT LOGIC             = FORBIDDEN
DATABASE MIGRATION                         = NOT PLANNED
```

W80-CA00F closes only after the source-backed sequential approval behavior is
visible in the product UI, Journal completion no longer performs allocation,
IA result publication and WA evidence retention satisfy their separate
contracts, and both exact-head live journeys pass independently.

## 13. As-Built Closure

`W80-CA00F.1` through `.5`, including corrective boundaries `.4A`, `.5A`,
`.5B`, and `.5C`, are complete. The final protected acceptance ran the Journal
and accounting-allocation journeys independently on product source head
`46aadc52116b3df960110d5e7f1f445ff3bed40d`.

The 15 acceptance requirements are `15/15 PASS`. Actual PostgreSQL, installed
Compose, OpenBao, RustFS, remote generation, authenticated Playwright,
restart/replay, screen evidence, diagnostic evidence, and zero-residue cleanup
all passed. The exact-head Repository Full Gate also passed with `24,111`
Python tests, statement coverage `96.23%`, branch coverage `95.12%`, `401`
Node tests, and `134` React/Vitest tests.

The canonical evidence and per-requirement disposition are recorded in
[`mybee_phase1_w80_ca00f5_split_live_journeys_protected_closure.md`](../../slices/mybee_phase1_w80_ca00f5_split_live_journeys_protected_closure.md).
No product source or persistence migration was added by the final closure.
