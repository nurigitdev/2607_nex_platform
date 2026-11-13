# NeX MyBee W40-S4-00A: Pre-Posting VoucherCandidate Revision and Journal Boundary Hardening v1.0

## 1. Status And Authority

- Decision date: `2026-11-13`
- Status: `IMPLEMENTED_CLOSED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `e191a1ac`
- Runtime code changes by this document: implemented in W40-S4-00A
- Remote model provider required: no

This document is a narrow pre-entry hardening amendment before W40 `S4-01`.
It does not introduce GL Posting. It closes the naming, persistence, revision,
and immutability boundary between the already implemented pre-Posting
`VoucherCandidate` and the future immutable `PostedJournal`.

It supplements, without rewriting:

- `NeX_MyBee_D04_D12_Accounting_Transaction_Contract_Closure_v1.0_RC1.md`;
- `NeX_MyBee_Implementation_Slice_Plan_v1.2.md` and its Execution Matrix;
- W30 `S3-01` through `S3-03` and `MB3-01` implementation evidence;
- W40-CA01 Project-Code entitlement and fail-closed authorization; and
- W40-CA02 installed accounting product-runtime entry acceptance.

For the physical pre-Posting aggregate name and the current migration-number
inventory, this document takes precedence over older design references to
`eos_journal_candidate` and migration `2523_eos_posted_journal_posting.sql`.
The repository already uses migration 2523 for FX market-rate adoption and it
must not be reused.

## 2. Problem Statement

Accounting requires a strict separation between an editable or reviewable
voucher before accounting approval and an immutable journal after Posting.
Traditional systems often express this as an inbox header/line pair and a GL
header/line pair.

The current NeX-EOS source already implements the first responsibility under
the `VoucherCandidate` name:

```text
eos_voucher_candidate
  -> eos_voucher_candidate_revision
     -> eos_voucher_candidate_line
```

Creating a second physical aggregate such as
`eos_journal_inbox_header/eos_journal_inbox_line` would duplicate candidate
identity, line amounts, Project attribution, evidence hashes, workflow state,
and idempotency semantics. It would also introduce a second synchronization
problem before Posting.

The correct closure is therefore to complete the existing Candidate revision
path and reserve `eos_journal_header/eos_journal_line` exclusively for the
immutable PostedJournal.

## 3. Source-Backed Current State

### 3.1 Legacy VoucherDraft v1

`eos_voucher_draft` and `eos_voucher_draft_line` remain the historical Golden
A compatibility aggregate.

- The header state is constrained to `DRAFT`.
- Lines use a signed amount rather than the Finance v2 debit/credit model.
- The line foreign key currently permits cascade deletion with the draft.
- It is not the MyBee W40 pre-Posting or GL authority.
- It must not be promoted to `POSTED` or reused as a PostedJournal.

### 3.2 VoucherCandidate v2

Migration `2534_eos_voucher_candidate_v2.sql` implements:

- `eos_voucher_candidate`: tenant/company/Project/document/source identity and
  workflow state;
- `eos_voucher_candidate_revision`: immutable revision identity and exact
  document, evidence, policy, FX, and journal-payload hashes; and
- `eos_voucher_candidate_line`: revision-scoped debit/credit lines with exact
  Account, Project UUID, user-facing Project Code, source line, and evidence
  hash.

PostgreSQL triggers already reject `UPDATE` and `DELETE` on candidate revisions
and lines. The candidate header rejects deletion and permits mutation only of
the explicit workflow projection fields:

```text
state
current_revision_no
version
updated_at
```

Migration `2535_eos_candidate_review_state.sql` adds an append-only review
event and the current state set:

```text
DRAFT
READY_FOR_REVIEW
RETURNED_FOR_CORRECTION
```

### 3.3 Confirmed implementation gap

The schema can store multiple candidate revisions, but the installed product
path currently creates revision 1 only. No canonical command appends a corrected
revision after `RETURNED_FOR_CORRECTION`.

The current submit path can re-submit a returned Candidate without proving that
a new immutable revision was created. This leaves the correction lifecycle
weaker than the frozen design intent.

### 3.4 PostedJournal state

No `eos_journal_header`, `eos_journal_line`, or authoritative ledger-entry
table currently exists in the NeX-EOS source or migration inventory. Those are
W40 implementation targets, not existing evidence.

## 4. Canonical Boundary Decision

### W40-S4-00A-ADR-01: VoucherCandidate is the pre-Posting voucher authority

`VoucherCandidate` is the only canonical EOS aggregate for a MyBee accounting
voucher before successful Posting.

The user-facing product may label its projection as `전표 입력함`,
`회계 검토함`, or `승인 대기 전표`. Those labels do not create a second
physical persistence aggregate.

The following new physical tables are prohibited by this amendment:

```text
eos_journal_inbox_header
eos_journal_inbox_line
eos_preposting_journal_header
eos_preposting_journal_line
```

A read-only projection or database view may be proposed later for reporting,
but it must be derived from `VoucherCandidate` and must not become a second SoR.

### W40-S4-00A-ADR-02: Candidate identity and revision body are distinct

The existing Candidate header remains the immutable business identity and
workflow projection. A correction appends a new revision and new lines; it
does not update or delete the prior revision.

The following Candidate identity changes require a new Candidate rather than a
new revision:

- tenant or company;
- Project UUID or Project registration code;
- ApprovedDocumentEnvelope identity;
- source kind or source record identity;
- business work code;
- transaction currency; or
- recognition date.

S4-00A revisions correct the accounting proposal body within that identity,
including Account selection, debit/credit amounts, descriptions, source line
references, and evidence hashes.

### W40-S4-00A-ADR-03: Returned Candidates require a new revision

A Candidate returned for correction cannot be submitted again by only changing
the workflow state. The canonical flow is:

```text
READY_FOR_REVIEW
  -> RETURNED_FOR_CORRECTION
  -> append revision N+1 and immutable lines
  -> DRAFT
  -> validate exact revision N+1
  -> READY_FOR_REVIEW
```

The old revision, old validation, and old review event remain queryable but
cannot authorize Posting. All later approval and Posting evidence binds the
exact current revision number and candidate hash.

### W40-S4-00A-ADR-04: PostedJournal is insert-only accounting truth

W40 `S4-02` and `S4-03` will introduce a separate PostedJournal aggregate:

```text
eos_accounting_approval_acceptance
eos_journal_header
  -> eos_journal_line
```

`eos_journal_header` and `eos_journal_line` are created only as part of a
successful Posting transaction. They are never used as a draft or approval
inbox.

The PostedJournal contract requires:

- repository/API operations limited to insert and read/verify;
- PostgreSQL triggers rejecting direct `UPDATE` and `DELETE`;
- foreign keys using `ON DELETE RESTRICT`, never cascade;
- one Journal per `(tenant_id, candidate_id, candidate_revision)`;
- exact linkage to Candidate revision/hash, accounting approval acceptance,
  accounting period, BusinessOperation, and Project Code;
- immutable Account and policy snapshots required for historical explanation;
  and
- correction only through a new `REVERSAL` or `ADJUSTMENT` Journal linked to
  the original Journal.

Service repository discipline is not sufficient by itself. Raw SQL mutation
must also be rejected in actual PostgreSQL protected tests.

## 5. Candidate Revision Command Contract

The implementation Slice adds one canonical product command:

```text
FINANCE.VOUCHER_CANDIDATE.REVISE
```

Minimum input semantics:

- `tenant_id`;
- `candidate_id`;
- `expected_candidate_version`;
- `expected_current_revision_no`;
- stable idempotency key and canonical payload hash;
- correction actor and reason/reference;
- complete replacement line set; and
- exact evidence hashes for every line.

The command is a full revision replacement, not a partial line patch. It must:

1. lock the Candidate header;
2. require `RETURNED_FOR_CORRECTION`;
3. compare expected version and current revision;
4. reject a semantic no-op correction;
5. append revision `N+1` and all its lines;
6. update only header workflow fields by compare-and-swap;
7. transition the header to `DRAFT`;
8. preserve all prior revisions and review events; and
9. commit through one EOS PostgreSQL transaction.

Exact replay with the same idempotency key and payload hash returns the existing
new revision. The same key with changed semantics returns a typed conflict.
Concurrent corrections from the same base version produce one winner and one
stale-version conflict.

Revision is prohibited when the Candidate is:

- `READY_FOR_REVIEW`;
- `POSTED`;
- `CANCELLED`; or
- bound to a different tenant, Project, document, or source identity.

## 6. Posting Linkage Contract

The future Journal header must carry or reference at least:

- `tenant_id`, `journal_id`, `company_id`;
- posting date and AccountingPeriod identity/version;
- functional and transaction currency semantics;
- `source_candidate_id`, `source_candidate_revision`;
- exact Candidate hash and journal payload hash;
- accounting approval acceptance identity;
- Project UUID and Project Code;
- BusinessOperation and idempotency identity;
- journal kind (`STANDARD`, `REVERSAL`, or `ADJUSTMENT`); and
- `reversal_of_journal_id` where applicable.

Each Journal line must carry or reference at least:

- tenant, journal, and line number;
- Account identity and historical Account code snapshot;
- Project UUID and Project Code;
- debit/credit amounts in the required currency basis;
- Candidate source line number;
- posting dimensions; and
- immutable evidence hash/reference.

The source linkage is one-way authoritative:

```text
VoucherCandidate revision -> zero or one PostedJournal
PostedJournal             -> exactly one VoucherCandidate revision
```

The Candidate does not become the GL and the Journal does not become editable
because its source Candidate was returned or corrected.

## 7. Transaction And State Rules

S4-00A does not perform Posting. It reserves the following rules for S4-03:

```text
lock current Candidate revision and AccountingPeriod
verify exact fresh OA and accounting Human proof evidence
insert AccountingApprovalAcceptance
insert Journal header and lines
consume approved document allowance
transition Candidate READY_FOR_REVIEW -> POSTED by CAS
insert BusinessOperation, idempotency result, and outbox
commit once
```

Any failure before commit leaves no approval acceptance, Journal, consumption,
POSTED state, idempotency result, or publication event. An ambiguous response
after commit is reconciled by authoritative operation and Journal lookup; it
must never create a second Journal.

`POSTED` and `CANCELLED` may be added to the Candidate state constraint only
with their corresponding guarded transitions. Merely widening the database
CHECK constraint is not accepted as implementation.

## 8. Persistence And Migration Rules

1. S4-00A should reuse the existing Candidate, revision, line, review event,
   BusinessOperation, idempotency, and outbox tables.
2. A new S4-00A table is not expected. A migration is permitted only for a
   source-proven constraint or column requirement.
3. Migration number `2523` is already occupied and is prohibited for W40.
4. The next migration identifier must be calculated from the repository
   inventory at implementation time. At reviewed commit `e191a1ac`, the latest
   EOS migration is `2538_eos_project_authorization_sync.sql`.
5. The PostedJournal migration has one explicit owner, selected during S4-02
   source audit. S4-01 and S4-03 must not create competing copies of the same
   tables.
6. Table and constraint names remain within PostgreSQL identifier limits.
7. SQLite may cover deterministic domain regression, but immutability,
   concurrency, trigger, lock, and rollback claims require actual
   `nex_eos_test` PostgreSQL evidence.

## 9. Security And Privacy

- Project UUID remains internal; user-facing projections use Project Code.
- Candidate and Journal access requires tenant, Project entitlement, finance
  scope, and accounting SoD decisions as applicable.
- A Project grant never replaces finance or accounting-approval scope.
- Candidate revisions, Journal lines, evidence, and approval proof are not
  included in ordinary logs.
- No OA, WC, or external HTTP call occurs while the EOS Posting transaction is
  open. Fresh evidence is obtained and validated before entering the local
  transaction and rechecked against bounded evidence/version rules inside it.
- Model generation output is never authoritative for Posting amounts, Account
  validity, approval, or state transitions.

## 10. Required Acceptance Matrix

S4-00A implementation is closed only when all of the following pass:

1. revision 1 remains byte/semantically unchanged after revision 2 creation;
2. direct SQL `UPDATE/DELETE` of any revision or line is rejected;
3. returned Candidate cannot be resubmitted without an admitted new revision;
4. exact revision replay returns the same revision identity;
5. changed replay returns a conflict with zero additional rows;
6. two concurrent revisions from the same base version yield one success;
7. stale validation and review evidence cannot bind the new revision;
8. READY, POSTED, CANCELLED, cross-tenant, or changed-identity revision is
   rejected;
9. no Journal row exists before successful W40 Posting;
10. existing VoucherDraft v1, Golden A, W30 Candidate, and MyBee consumer
    regression remains green; and
11. actual PostgreSQL protected smoke leaves zero fixture residue.

S4-02/S4-03 later add these mandatory Journal tests:

- raw SQL Journal header/line `UPDATE/DELETE` rejection;
- line-insert or outbox fault rolls back the complete Posting;
- same Candidate revision produces at most one Journal; and
- reversal creates a new linked Journal without changing the original.

## 11. Explicit Non-Goals

S4-00A does not:

- create `journal_inbox` tables;
- create or activate PostedJournal tables;
- accept an accounting Human decision;
- perform GL Posting, reversal, allocation, or Project P&L;
- change VoucherDraft v1 behavior;
- add UI workflow beyond preserving current projections;
- call generation, embedding, or reranker providers; or
- claim W40 completion.

## 12. Implementation And Gate Plan

Implementation remains one focused Slice named:

```text
W40-S4-00A: Pre-Posting VoucherCandidate Revision and Journal Boundary Hardening
```

Required execution order:

1. re-audit current Candidate repository, command, review, validation, API,
   contracts, and migration inventory;
2. perform the minimum refactoring needed to isolate revision append from
   review-state mutation;
3. implement the canonical revision command and repository transaction;
4. add schema, positive/negative examples, OpenAPI, and typed errors;
5. run focused unit and regression tests;
6. run actual `nex_eos_test` PostgreSQL immutability, replay, race, and
   zero-residue smoke;
7. run the NeX-EOS Slice Gate while maintaining the current coverage margin;
   and
8. record As-Built evidence before entering `S4-01`.

No remote provider is required.

## 13. S4-01 Entry Decision

W40 `S4-01` remains blocked until S4-00A proves that:

- `VoucherCandidate` is the only canonical pre-Posting voucher SoR;
- returned corrections create a new immutable revision;
- stale review evidence cannot authorize the new revision;
- no duplicate `journal_inbox` aggregate exists; and
- the future PostedJournal boundary is reserved for insert-only GL truth.

After this evidence is recorded, W40 proceeds in the existing canonical order:

```text
S4-01 Accounting Proof acceptance and fresh OA revalidation
  -> S4-02 immutable PostedJournal and DB protection
  -> S4-03 atomic single-EOS Posting transaction
  -> S4-04 replay, outbox, and UNKNOWN recovery
```

## 14. As-Built Closure

W40-S4-00A implemented the source-backed boundary without adding a migration or
a second pre-Posting aggregate.

- `FINANCE.VOUCHER_CANDIDATE.REVISE` appends revision `N+1` and its complete
  replacement line set through the EOS transaction coordinator.
- The command requires an exact immutable RETURN or INVALIDATE review event,
  expected Candidate version, current revision number, and Candidate hash.
- Exact replay returns the committed revision; changed replay, stale CAS, a
  semantic no-op, missing return evidence, or denied OA/Project authority fails
  closed.
- A successful correction updates only Candidate workflow projection fields and
  returns the Candidate to `DRAFT` for fresh validation and review.
- Direct resubmission and validation from `RETURNED_FOR_CORRECTION` are no
  longer admitted.
- The product API, JSON Schemas, examples, OpenAPI contract, dependency
  composition, and outbox event `VOUCHER_CANDIDATE_REVISED` are installed.
- Actual `nex_eos_test` PostgreSQL evidence proved one-winner concurrency,
  revision/line mutation rejection, absence of premature Journal tables, and
  isolated-schema zero residue.

The detailed implementation and gate receipt is recorded in
`docs/slices/mybee_phase1_w40_s4_00a_pre_posting_candidate_revision.md`.
