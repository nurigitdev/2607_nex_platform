# NeX MyBee W80-CA00G Business Proposal Draft Review, Amount-Tiered Approval, and Voucher Pre-Submission Review Boundary v1.0

**Status:** DESIGN FROZEN / IMPLEMENTATION IN PROGRESS

**Predecessor:** W80-CA00F

**Boundary:** AI-assisted business-proposal draft -> requester review and
revision -> amount-tiered BUSINESS_FORMAL approval -> immutable
ApprovedDocumentEnvelope -> VoucherCandidate draft -> requester accounting-line
review -> accounting submission

**Database migration:** An additive EOS migration is expected for durable
business-proposal draft and immutable revision persistence. Existing approval,
ApprovedDocumentEnvelope, VoucherCandidate, Journal, and WA tables must be
reused. Exact physical DDL is admitted only after the first implementation
Slice proves storage fit; implementation must not place business-document SoR
data in AE Workspace or mutate the approved-envelope store into a draft store.

## 1. Purpose

W80-CA00F proved the installed accounting spine by generating and submitting a
business proposal inside one runtime operation, completing sequential business
and accounting approval, posting one immutable Journal, and publishing the IA
result. That acceptance remains valid as platform evidence, but it intentionally
compressed two user-controlled groupware boundaries:

1. a requester must review and, when necessary, edit a generated business
   proposal and its approval line before submission;
2. a requester must review and, when necessary, edit the generated account,
   debit, and credit lines before submitting a VoucherCandidate for accounting
   approval.

An ordinary enterprise expense therefore follows this product lifecycle:

```text
IA-assisted proposal draft
  -> requester review/edit/approval-line preview
  -> explicit proposal submission
  -> amount-tiered BUSINESS_FORMAL approval
  -> immutable ApprovedDocumentEnvelope
  -> later expense evidence and VoucherCandidate DRAFT
  -> requester account/debit/credit review and revision
  -> explicit accounting submission
  -> accounting approval
  -> governed WRITE and immutable Journal
```

The amendment adds durable review and submission boundaries. It does not add a
second approval engine, let an LLM select business authority, or weaken the
W80-CA00F separation between Journal posting and accounting allocation.

## 2. Source-Backed Current State

### 2.1 Reusable foundations

The current repository already provides:

- typed `BusinessProposalForm` and versioned D04 proposal templates;
- exact proposal content, attachment-manifest, and approval-subject hashes;
- EOS amount-aware `ApprovalPolicy` selection with `minimum_amount`,
  `maximum_amount`, transaction, Project, account, risk, and effective-time
  selectors;
- one-to-five persisted approval stages with only one ACTIVE stage;
- OA-backed leadership and approver resolution;
- WC `BUSINESS_FORMAL` work items and sequential decision delivery;
- immutable final `ApprovedDocumentEnvelope` with amount, currency, Project,
  attachment, revision, Proof, and consumption lineage;
- `VoucherCandidate` header, immutable revisions and lines;
- `DRAFT`, `READY_FOR_REVIEW`, `RETURNED_FOR_CORRECTION`, and `POSTED`
  Candidate states;
- Candidate revise, validate, submit, return, invalidate, posting admission,
  and immutable Journal boundaries;
- maker/checker SoD and fresh OA authorization at approval and posting.

These foundations remain canonical.

### 2.2 Confirmed gaps

The installed preparation adapter currently builds a proposal object and calls
the EOS approval consumer immediately. The proposal is not a durable,
reopenable business draft and no user-facing proposal editor exists.

The current approval consumer receives an `approval_policy_id`; it does not yet
provide a product flow that:

- resolves the policy from the final submitted amount and business scope;
- previews the required approval ladder;
- admits requester-selected approvers from the OA-eligible candidate set;
- binds that exact line to the submitted proposal revision.

VoucherCandidate revision and review persistence already exists, but the
installed journey creates and advances the Candidate without a requester-facing
accounting-line review surface. This is primarily a product composition, API,
and UI gap rather than a new ledger model.

## 3. Canonical Ownership

| Concern | Owner | Rule |
| --- | --- | --- |
| Proposal template and user-facing field semantics | MyBee domain | Versioned contract; no tenant business values in code |
| Durable proposal aggregate and revisions | EOS | Business SoR; restart-safe and tenant-scoped |
| Proposal editing projection | AE API/Web | Owner-authorized facade; never the SoR |
| Required approval policy and stages | EOS | Deterministic policy resolution |
| Organization, active membership, roles, authority | OA | Fresh authority source |
| Human approval work and decision delivery | WC | Sequential work routing and durable decision events |
| Final ApprovedDocumentEnvelope | EOS | Immutable final business approval Proof |
| VoucherCandidate and revision/line truth | EOS | Existing persistence reused |
| Accounting review and Posting | EOS/WC/OA | Separate Human Gate and governed WRITE |
| Optional rendered artifacts and execution evidence | WA | References/evidence only; no duplicate business truth |

AE may generate, display, and edit projections through protected APIs. It must
not own proposal, approval, Candidate, or Journal truth.

## 4. Durable Business Proposal Contract

### 4.1 Aggregate states

The proposal aggregate uses these product states:

```text
DRAFT -> SUBMITTED -> APPROVED
                   -> REJECTED
DRAFT -> WITHDRAWN
REJECTED -> DRAFT (new revision and new approval case only)
```

- `DRAFT` is owner-editable through revision creation.
- `SUBMITTED` binds one exact immutable revision, approval line, policy, and
  approval case. It is not editable.
- `APPROVED` is terminal for the submitted revision and materializes one exact
  ApprovedDocumentEnvelope.
- `REJECTED` is terminal for its approval case and materializes no envelope.
- A rejected proposal may be corrected only by creating a new revision and a
  new approval case. Earlier decisions remain immutable history.
- `WITHDRAWN` is allowed only before a terminal approval decision and creates no
  ApprovedDocumentEnvelope.
- Physical deletion is forbidden. Retention and privacy controls operate on
  access and lifecycle policy, not history mutation.

### 4.2 Revision rules

Each edit appends a revision. In-place mutation of a persisted revision is
forbidden. A revision binds at least:

- tenant, proposal, revision, requester, company, and template identities;
- title, purpose, business justification, transaction type, requested amount,
  original currency, valid period, and Project scope;
- attachment object references, sizes, media types, and hashes;
- content and attachment-manifest hashes;
- policy-selection input and normalized approval amount evidence;
- proposed and admitted approval-line hashes;
- created time, creator, and predecessor revision.

Updates require `expected_revision` and aggregate `expected_version`. Stale
browser tabs and concurrent edits fail with a typed conflict and never overwrite
the latest revision.

### 4.3 Amount normalization

Approval thresholds must not compare amounts from different currencies as if
they were equal. Policy resolution uses:

1. the proposal's original amount and currency;
2. the company's functional approval currency;
3. an admitted FX RateSnapshot when conversion is required;
4. the normalized approval amount and calculation hash.

The original amount remains the business request. The normalized amount is
policy-selection evidence only. Missing, stale, or incompatible FX evidence
fails closed before submission.

## 5. Approval-Line Selection and Authority

### 5.1 Required ladder

EOS resolves the required policy from the submitted proposal revision using
tenant, company, transaction type, amount tier, Project scope, risk, and
effective time. Product code contains no fixed currency thresholds or tenant
maps.

The initial acceptance configuration demonstrates one-, two-, and three-stage
routes. The common approval engine retains its existing maximum of five stages.
Example stage roles are team lead, group lead, and chief executive; actual
position names and thresholds are tenant policy data, not source constants.

### 5.2 User selection

The UI may recommend a default line and let the requester select a concrete
approver for each required stage, subject to all of the following:

- the stage itself comes from the EOS policy and cannot be removed or reordered;
- candidates come only from OA's active, eligible organization/role projection;
- the requester cannot select self when separation policy forbids it;
- an optional reviewer may be added, but cannot replace a mandatory stage;
- the selected line is hash-bound to the submitted revision;
- final authority is revalidated against OA when the stage activates and when
  the decision is recorded.

The selected person is a routing nomination, not a durable grant of authority.
If a nominated approver becomes inactive or loses authority after submission,
the system must not silently route to an arbitrary person. A controlled
reassignment preserving the policy stage and audit history, or a return to the
requester, is required.

### 5.3 Editing invalidates stale approval previews

Any change to amount, currency, company, transaction type, Project scope,
business content, attachments, or validity creates a new revision and
invalidates the prior policy preview and approval-line selection. Submission is
admitted only when revision, content hash, policy hash, line hash, OA candidate
evidence, and idempotency semantics agree.

## 6. Sequential Business Approval and Rejection

- Only stage one is ACTIVE immediately after submission.
- Later stages remain WAITING and are not actionable or visible as pending work
  to their actors.
- Approval activates exactly the next persisted stage.
- Rejection at any stage makes the approval case terminal.
- A middle-stage or final-stage rejection creates no later approval work item,
  ApprovedDocumentEnvelope, VoucherCandidate, accounting approval, NSL WRITE
  gate, or Journal.
- Replay, duplicate delivery, ACK loss, restart, and concurrent workers cannot
  create parallel ACTIVE stages or duplicate decisions.
- Final approval materializes an ApprovedDocumentEnvelope bound to the exact
  proposal revision, Proof, amount, currency, Project set, attachments, policy,
  and decision chain.

## 7. Voucher Pre-Submission Review

### 7.1 Candidate creation boundary

Final business approval authorizes a later expense within the envelope; it does
not itself prove that the expense occurred and does not automatically post a
Journal. A VoucherCandidate is created only when actual expense evidence is
available and a protected command references the usable ApprovedDocumentEnvelope.

The Agent may propose account and line values. The authoritative result remains
an EOS `DRAFT` Candidate.

### 7.2 Requester review

Before accounting submission, the requester can review and revise:

- debit and credit accounts;
- line descriptions and evidence references;
- original-currency debit and credit amounts;
- recognition date and permitted accounting metadata;
- the Project attribution allowed by the ApprovedDocumentEnvelope.

Every edit creates a new immutable Candidate revision. The UI shows the current
revision, the prior revision diff, balance state, validation results, approved
amount/remaining amount, Project code, period, FX evidence, and attachment
references. Internal UUIDs are not the primary user-facing identity.

Changes may not alter company, currency, Project scope, or business purpose
outside the approved envelope. Amount above the remaining approved limit or a
material scope change requires a new or revised business proposal rather than a
VoucherCandidate override.

### 7.3 Explicit accounting submission

`SUBMIT_FOR_ACCOUNTING` is a user command, not an automatic runtime transition.
It requires:

- the expected current Candidate revision and hash;
- debit equals credit;
- current COA, open accounting period, FX, Project, and ApprovedDocument checks;
- no duplicate source invoice/evidence consumption;
- a fresh accounting approval policy and requester identity;
- an explicit user confirmation recorded with the submission event.

The admitted transition is `DRAFT -> READY_FOR_REVIEW`. After submission, that
revision is locked. Accounting rejection uses the existing return event and
`RETURNED_FOR_CORRECTION`; correction creates a new revision before resubmission.
The preparer/requester cannot approve the accounting submission.

## 8. AE Web Experience

The authenticated product shell adds two user workflows.

### 8.1 Proposal workspace

- proposal list with `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, and
  `WITHDRAWN` filters;
- AI-generated draft editor using the admitted template;
- attachment review and replacement before submission;
- Project code, amount, currency, purpose, and validity review;
- required approval-line preview and OA-eligible approver selector;
- revision diff and stale-edit conflict handling;
- explicit `상신` command and confirmation;
- sequential approval timeline with current stage, completed decisions,
  rejection reason, and final envelope reference.

### 8.2 Voucher draft workspace

- approved proposal/envelope selector and remaining approved amount;
- account search and debit/credit line editor;
- real-time balance and validation summary;
- immutable revision history and diff;
- save-draft and explicit accounting-submission commands;
- returned-for-correction handling;
- accounting approval and Posting timeline after submission.

The UI must not expose service tokens, internal authority payloads, raw database
identities, or controls the current user is not authorized to invoke.

## 9. Live Acceptance Matrix

Protected acceptance uses actual OA, AE, WC, EOS, and WA PostgreSQL; installed
Compose; OpenBao; RustFS where attachments apply; remote generation for
AI-assisted draft creation; and authenticated Playwright.

The following journeys are independent:

1. **One-stage success:** low-tier proposal draft, user edit, line preview,
   submit, one business approval, and exact ApprovedDocumentEnvelope.
2. **Two-stage success:** middle-tier proposal with only one ACTIVE gate at a
   time and final envelope after stage two.
3. **Three-stage success and accounting completion:** high-tier proposal,
   three sequential approvals, expense evidence, VoucherCandidate draft,
   account/amount edit, explicit accounting submission, accounting approval,
   governed WRITE, immutable Journal, and IA result.
4. **Middle-stage rejection:** a three-stage proposal rejected at stage two;
   no stage three, envelope, Candidate, accounting gate, or Journal.
5. **Final-stage rejection:** a three-stage proposal rejected at stage three;
   no envelope, Candidate, accounting gate, or Journal.
6. **Correction journey:** accounting rejection returns the Candidate, a new
   Candidate revision is submitted, and only the admitted latest revision may
   be posted.

Each journey verifies restart/replay, ACK loss, stale revision rejection,
maker/checker SoD, owner/tenant isolation, screen evidence, diagnostic evidence,
zero residue, and no duplicate proposal, approval decision, envelope,
Candidate revision, accounting Proof, Journal, AgentResult, or WA evidence.

Pre-request policy, organization, and account seed is permitted. Direct
database mutation or fixture injection after a user request begins is forbidden.
Threshold examples used by tests must not appear as product runtime constants.

## 10. Non-Goals

W80-CA00G does not:

- replace EOS/WC/OA approval foundations;
- make AE Workspace the business-document SoR;
- store editable drafts in the immutable ApprovedDocumentEnvelope table;
- let an LLM choose or authorize approvers, accounting policy, or account truth;
- permit a requester to remove required stages or self-approve;
- make final business approval equivalent to accounting approval or Posting;
- automatically submit a generated proposal or VoucherCandidate;
- automatically run cost allocation after Journal completion;
- duplicate proposal, Candidate, or Journal truth in WA;
- add tenant-, amount-, Project-count-, approver-, or scenario-specific branches;
- modify the NSL compiler/runtime.

## 11. Implementation Slices

0. `W80-CA00G.0: Owner-Scoped Agent Execution Progress Projection Foundation`
0A. `W80-CA00G.0A: Protected Live Progress and Playwright Evidence Acceptance`
1. `W80-CA00G.1: Proposal Persistence and Revision Contract Closure`
2. `W80-CA00G.2: Amount-Tiered Policy Resolution and Approval-Line Selection`
3. `W80-CA00G.3: Proposal Draft/Edit/Submit Product APIs and AE Web`
4. `W80-CA00G.4: Sequential Approval, Rejection, and Envelope Finalization`
5. `W80-CA00G.5: Voucher Draft Review, Revision, Validation, and Explicit Submit`
6. `W80-CA00G.6: Groupware Journey Integration and Result Projection`
7. `W80-CA00G.7: Protected Live Matrix, Repository Full Gate, and As-Built Closure`

`.0` is a cross-cutting observability foundation. The browser creates the
`interaction_id` before submission, starts progress polling concurrently with
the Chat POST, and appends owner-scoped, ordered progress messages until a
terminal result is observed. Deterministic activity identifiers make boundary
replay idempotent. Existing Workspace activity persistence is reused; raw
prompt, plan payload, and private business content are not part of this
projection. The initial diagnostic UI may prefix each line with the event time,
but time formatting is presentation-only and must not change durable identity.
`.0A` reuses the installed Journal and independent Allocation product journeys
to prove concurrent polling, append-only rendering, terminal stop, owner scope,
restart recovery, screenshot integrity, and zero residue before `.1` begins.

Checkpoint gates run after `.3` and `.5`. `.7` runs the six protected journeys,
actual PostgreSQL smoke, Playwright evidence, restart/replay acceptance, coverage
gates, and the Repository Full Gate.

## 12. Stop Conditions

Implementation must stop for a design decision if:

- existing proposal or approval persistence already provides a canonical draft
  SoR whose semantics conflict with the proposed additive model;
- concrete approver selection cannot be represented without weakening OA's
  fresh authority or WC routing contract;
- currency-normalized approval thresholds cannot bind an immutable FX source;
- proposal editing would require mutation of submitted or approved revisions;
- a Candidate edit can bypass approved amount, company, currency, Project, or
  attachment lineage;
- the UI would need direct EOS database access or service credentials;
- a live journey requires post-request fixture mutation or scenario-specific
  product logic;
- the change would weaken Journal immutability, approval SoD, replay safety,
  zero-residue, or W80-CA00F allocation independence.

## 13. Closure Criteria

```text
DURABLE PROPOSAL DRAFT SOR                = EOS
PROPOSAL AND CANDIDATE REVISION MUTATION  = FORBIDDEN
USER REVIEW BEFORE PROPOSAL SUBMIT        = REQUIRED
AMOUNT-TIERED POLICY RESOLUTION           = REQUIRED
MANDATORY APPROVAL-STAGE REMOVAL          = FORBIDDEN
FRESH OA AUTHORITY                        = REQUIRED
BUSINESS APPROVAL BEFORE CANDIDATE        = REQUIRED
USER REVIEW BEFORE ACCOUNTING SUBMIT      = REQUIRED
BUSINESS APPROVAL = ACCOUNTING APPROVAL   = FALSE
ACCOUNTING APPROVAL = POSTING             = FALSE
JOURNAL-TO-ALLOCATION COUPLING            = FORBIDDEN
SCENARIO-SPECIFIC PRODUCT LOGIC           = FORBIDDEN
```

W80-CA00G closes only after users can generate, persist, reopen, edit, preview,
and explicitly submit a proposal; amount-tiered sequential approval succeeds or
rejects without leaking later stages; a final envelope is the sole authority for
creating an expense Candidate; users can review and revise accounting lines
before explicit submission; and all success, middle-rejection, final-rejection,
correction, restart, replay, and zero-residue gates pass on exact head.
