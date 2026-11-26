# NeX MyBee W80-CA00H Proposal/Voucher Review Usability and Accounting Presentation Boundary v1.0

**Status:** DESIGN FROZEN / IMPLEMENTATION NOT STARTED

**Predecessor:** W80-CA00G

**Boundary:** proposal approval-line priority -> rejection-reason integrity ->
approved Project attribution -> effective K-IFRS account selection ->
VoucherCandidate review -> voucher-shaped BUSINESS_FORMAL/NSL_WRITE projection

**Database migration:** None planned. Existing EOS proposal, account catalog,
ApprovedDocumentEnvelope, VoucherCandidate, WC decision, and approval-event
stores remain authoritative. Implementation must stop for a storage decision if
the required requester-visible rejection or accounting projection cannot be
derived from those existing records without loss of lineage.

## 1. Purpose

W80-CA00G established durable proposal review, amount-tiered approval, and
VoucherCandidate review before accounting submission. Its protected acceptance
proved the workflow, but the resulting screens still expose several
implementation-oriented details that make ordinary groupware use unnecessarily
difficult:

1. the approval line appears after the long proposal form even though it is a
   primary submission decision;
2. VoucherCandidate creation binds a Project Code internally but does not make
   that binding sufficiently visible or controllable to the user;
3. account entry is code-first even though the authoritative EOS account catalog
   already contains K-IFRS-aligned account names and effective company policy;
4. approval details expose a generic request summary instead of a balanced,
   voucher-shaped accounting document;
5. the Web requires a rejection reason, but that rule and the requester-visible
   rejection projection are not yet frozen as an end-to-end product contract.

This amendment improves those review surfaces without creating a second
accounting source of truth, permitting browser-side authority inference, or
changing the W80-CA00G approval and revision lifecycle.

## 2. Source-Backed Current State

### 2.1 Reusable foundations

The current repository already provides:

- an EOS-owned durable `BusinessProposal` and immutable revisions;
- amount-tiered approval preview with mandatory stages and OA-eligible
  candidates;
- sequential WC `BUSINESS_FORMAL` work and durable `decision_comment`;
- an immutable ApprovedDocumentEnvelope containing Project scope;
- an EOS-owned VoucherCandidate with immutable lines and revisions;
- `project_code` on every VoucherCandidate and mandatory Project attribution in
  the accounting path;
- `account_code` and resolved `account_name` on projected VoucherCandidate
  lines;
- an EOS effective account-catalog API keyed by tenant, company, and effective
  date;
- approved company account policy fields including postable-leaf, currency,
  effective-period, catalog-release, and posting-rule evidence;
- AE protected facades for proposal, VoucherCandidate, and approval operations;
- an authenticated approval decision panel that already disables rejection
  while the reason is empty.

These foundations remain canonical and must be reused.

### 2.2 Confirmed usability and contract gaps

The source audit confirms the following gaps:

- proposal approval-line preview and selection are rendered below the form and
  action controls;
- VoucherCandidate creation uses the first approved Project Code without a
  dedicated visible Project field or a multi-Project selection boundary;
- voucher creation and revision use free-text account-code inputs rather than
  an admitted effective account catalog;
- `ae_user_approval_projection.v1` currently returns the amount, accounts, and
  line-item sections as `OPEN` and cannot render an authoritative debit/credit
  document;
- the existing approval line-item shape has one amount and no debit/credit
  direction, totals, or balance state;
- rejection reason is required by the current browser, but the server-side
  BUSINESS_FORMAL rejection admission and requester-visible result must be
  verified and hardened independently of browser validation.

## 3. Canonical Ownership

| Concern | Owner | Rule |
| --- | --- | --- |
| Proposal and submitted revision | EOS | Business SoR; AE renders an owner-safe projection |
| Required approval stages and eligible line | EOS/OA | Browser may select only from admitted candidates |
| Approval work and decision comment | WC | Immutable human-decision evidence |
| Approved Project scope | EOS ApprovedDocumentEnvelope | Sole source for VoucherCandidate Project choices |
| Effective account catalog and names | EOS | Company/date/currency-aware accounting authority |
| VoucherCandidate and immutable revisions | EOS | Sole pre-Posting voucher authority |
| User-facing approval projection | AE API | Server-side composition from authoritative services |
| Proposal, voucher, and approval presentation | AE Web | Presentation only; no business inference |

The browser must never query an EOS database directly, hold a service token, or
derive authority from cached display text.

## 4. Proposal Approval-Line Priority

The proposal editor places the approval-line section immediately after the
proposal identity and journey summary and before the editable business fields.

The section must show:

- the number and order of mandatory stages;
- each stage role and the selected eligible approver;
- whether the preview is current or invalidated by a revision edit;
- a clear command to calculate or refresh the line;
- an explicit incomplete state when a mandatory approver has not been selected.

Moving the section does not let the browser determine approval thresholds,
remove stages, reorder stages, or synthesize candidates. Any edit that changes
the W80-CA00G policy-selection input invalidates the displayed preview and
prevents submission until a new preview and selection are admitted.

## 5. Rejection-Reason Integrity

For a BUSINESS_FORMAL rejection:

1. a non-empty, trimmed reason is mandatory;
2. browser validation is convenience only and is not the authority boundary;
3. the protected WC decision API rejects a missing reason before mutation;
4. the admitted reason is stored with the immutable decision and propagated
   through the existing approval event;
5. EOS applies the reason to the exact proposal approval case and revision;
6. the requester can see the bounded, display-safe reason in the proposal
   timeline or result projection;
7. approval may keep a nullable comment unless a separate policy requires it.

The reason must not be used as an executable command, authority input, or raw
HTML. Length, control characters, display safety, and tenant/owner visibility
are validated at the protected boundary.

This amendment does not erase or rewrite earlier rejection decisions. A
corrected proposal follows the W80-CA00G revision and new-case rules.

## 6. Voucher Project Attribution UX

### 6.1 Single-Project envelope

When the selected ApprovedDocumentEnvelope contains exactly one Project Code:

- the VoucherCandidate draft binds that Project automatically;
- the Project Code is displayed as a prominent read-only accounting field;
- the create confirmation states that the Project came from the approved
  proposal;
- an internal Project UUID may remain in authority data but is not the primary
  user-facing identifier.

### 6.2 Multi-Project envelope

When an envelope contains multiple approved Projects, silently taking the first
array element is forbidden. The requester must explicitly choose one Project
from the approved set before creating the draft.

The UI must not permit arbitrary Project text. The API revalidates the selected
Project against the envelope, tenant, company, active Project authority, and
requester scope. Stale or out-of-scope selections fail closed.

One VoucherCandidate remains attributed to one Project Code under this
amendment. Splitting one expense across Projects belongs to the independent
accounting-allocation product boundary and must not be reintroduced into the
voucher review UI.

### 6.3 Missing Project

An envelope without an admitted Project Code is ineligible for MyBee accounting
VoucherCandidate creation. The browser shows a bounded explanation; it must not
invent a default Project or fall back to a tenant dictionary.

## 7. K-IFRS Account Catalog Presentation

### 7.1 Authority source

Account choices come from the EOS effective account catalog for:

- the authenticated tenant;
- the proposal/VoucherCandidate company;
- the recognition date;
- the current published catalog release and PostingRule;
- active, approved, postable-leaf company account policies;
- the transaction currency when the policy restricts allowed currencies.

An AE protected read facade forwards the authenticated user context through
signed service trust. The Web never calls the EOS internal route directly.

### 7.2 Display and wire identity

The user-facing selector displays account name first and code second, for
example:

```text
외주비 (510100)
```

Search may match normalized account name or code. The canonical wire and
persistence identity remains `account_code`; display names are projections and
must not be accepted as an accounting key.

Existing VoucherCandidate lines display their authoritative `account_name` and
`account_code`. When editing, the selected code is resolved again against the
effective catalog during EOS validation. A stale, non-postable, revoked,
currency-incompatible, or out-of-company account fails closed.

No K-IFRS account list, tenant override, default expense account, or default
offset account may be hardcoded in AE Web or AE API.

## 8. Voucher-Shaped Approval and NSL WRITE Projection

### 8.1 Projection source

The approval screen does not render raw NSL payloads, Agent plans, or arbitrary
gate summaries as an accounting document. AE API composes a typed, display-safe
projection from the exact authoritative references carried by the approval:

- VoucherCandidate identity and immutable revision/hash;
- Project Code;
- proposal or ApprovedDocumentEnvelope reference;
- company and recognition date;
- currency;
- account code and effective account name;
- description;
- debit and credit values;
- debit total, credit total, and balance state;
- approval domain, current stage, requester, and state.

If the approval cannot be joined to one exact authoritative Candidate revision,
the projection remains unavailable and the UI shows a bounded diagnostic. It
must not infer lines from title text or reconstruct them from an untrusted
summary.

### 8.2 Versioned contract

The current v1 line-item shape must not be silently reinterpreted. The
implementation introduces an explicitly versioned compatible projection or an
optional typed accounting-document block with strict schema admission. Existing
non-accounting approval domains remain supported.

The user-facing accounting view presents:

1. document header and workflow state;
2. Project and approved-business reference;
3. a tabular debit/credit line section;
4. totals and balance status;
5. approval progress and decision controls;
6. attachments and evidence;
7. collapsed technical references only where already authorized.

The same accounting projection is used for accounting BUSINESS_FORMAL and the
related NSL WRITE review when both refer to the same Candidate revision. Their
approval domains and authority semantics remain distinct.

## 9. Security and Privacy Boundary

- Internal UUIDs, hashes, object paths, service tokens, raw prompts, plans, and
  protected request payloads are not primary user-facing fields.
- Rejection reasons are visible only to authorized participants and operators
  with the required scope.
- Account catalogs are tenant/company/effective-date scoped and never cached
  across authority boundaries.
- Project options come only from the approved envelope and current authority.
- Server-side composition enforces tenant, owner, company, Candidate revision,
  and approval-target equality before returning accounting details.
- A failed join or unavailable authority source returns a typed unavailable or
  conflict state; it never falls back to fixture data.

## 10. Implementation Slices

1. `W80-CA00H.1: Approval-Line Priority and Rejection-Reason Contract Closure`
   - move proposal approval-line controls above the editable body;
   - preserve preview invalidation and mandatory-stage selection;
   - harden BUSINESS_FORMAL rejection-reason admission and requester projection.
2. `W80-CA00H.2: Voucher Project Scope Binding and Selection UX`
   - display single-Project automatic binding;
   - require explicit selection for an approved multi-Project envelope;
   - remove first-element and arbitrary-text ambiguity.
3. `W80-CA00H.3: Effective K-IFRS Account Catalog Facade and Selector`
   - add the protected AE catalog facade;
   - add name-first account search/selection;
   - retain code-only canonical write semantics and EOS revalidation.
4. `W80-CA00H.4: Voucher-Shaped Approval and NSL WRITE Projection`
   - introduce the versioned accounting projection;
   - render authoritative debit/credit lines, totals, balance, and lineage;
   - retain approval-domain separation and display safety.
5. `W80-CA00H.5: Protected PostgreSQL, Playwright, and Repository Closure`
   - run actual AE/WC/OA/EOS PostgreSQL protected acceptance;
   - verify authenticated proposal, voucher, rejection, and approval screens;
   - capture semantic Playwright evidence;
   - run coverage gates and the Repository Full Gate;
   - record As-Built and zero-residue evidence.

A focused Checkpoint Gate runs after `.3`. Slice `.5` is the final protected and
Repository Full Gate. Remote generation is not required for `.1` through `.4`;
`.5` may reuse an admitted persisted proposal/Candidate journey so provider
availability does not mask presentation or authority defects. A separate live
AI draft journey may be added as evidence when the canonical provider is
available, but it is not the source of account, Project, or approval truth.

## 11. Acceptance Matrix

| Case | Expected result |
| --- | --- |
| Proposal editor opens | Approval line appears before editable business fields |
| Proposal revision changes policy input | Prior preview is invalid and submission is blocked |
| BUSINESS_FORMAL rejection without reason | Protected API rejects with zero mutation |
| BUSINESS_FORMAL rejection with reason | WC/EOS persist it and requester sees the bounded reason |
| One approved Project | Project Code is automatically bound and visibly read-only |
| Multiple approved Projects | User must select one approved Project explicitly |
| Arbitrary/out-of-envelope Project | Request fails closed |
| Effective account catalog available | User sees account name plus code and submits canonical code |
| Revoked/non-postable/stale account | Selection or EOS validation fails closed |
| Accounting approval opens | Exact debit/credit lines, totals, and balance are visible |
| NSL WRITE approval opens | Same Candidate revision is readable without exposing raw payload |
| Projection join is ambiguous or unavailable | No inferred voucher is rendered |
| Cross-tenant/owner/company request | Access denied with no data disclosure |
| Replay/restart/ACK loss | No duplicate decision, Candidate revision, or mutable history |

## 12. Non-Goals

W80-CA00H does not:

- replace EOS account, proposal, Candidate, or Journal truth;
- add a browser-owned or AE-owned account catalog;
- change K-IFRS codebook approval or tenant-adoption policy;
- allow free-form Project or account identities;
- split one VoucherCandidate across multiple Projects;
- merge BUSINESS_FORMAL, accounting approval, and NSL WRITE authority;
- expose raw NSL, Agent, service, or database payloads;
- create a parallel approval engine, queue, or business table;
- change Journal Posting or allocation behavior;
- introduce scenario-, tenant-, Project-count-, or fixture-specific branches.

## 13. Stop Conditions

Implementation stops for a design decision if:

- a multi-Project envelope cannot preserve one exact selected Project without
  changing the accounting attribution contract;
- the effective account catalog cannot be resolved from company and recognition
  date with fresh authority;
- voucher-shaped approval would require trusting a raw NSL payload instead of an
  authoritative Candidate revision;
- rejection reason cannot be projected to the requester without duplicating or
  mutating WC/EOS decision history;
- a new database table appears necessary rather than reusing existing truth;
- UI work would require service credentials or direct database access;
- compatibility requires silently changing the semantics of the v1 approval
  projection;
- any change weakens SoD, revision immutability, Project attribution, tenant
  isolation, replay safety, or zero-residue behavior.

## 14. Closure Criteria

```text
APPROVAL LINE BEFORE PROPOSAL BODY          = REQUIRED
BROWSER-DERIVED APPROVAL AUTHORITY           = FORBIDDEN
BUSINESS REJECTION REASON                    = REQUIRED
PROJECT SOURCE                               = APPROVED ENVELOPE
MULTI-PROJECT FIRST-ELEMENT FALLBACK         = FORBIDDEN
ACCOUNT DISPLAY                              = NAME + CODE
ACCOUNT WRITE IDENTITY                       = CODE
ACCOUNT AUTHORITY                            = EFFECTIVE EOS CATALOG
VOUCHER APPROVAL PRESENTATION                = DEBIT/CREDIT DOCUMENT
RAW NSL PAYLOAD AS USER DOCUMENT             = FORBIDDEN
BUSINESS_FORMAL = NSL_WRITE                  = FALSE
NEW BUSINESS TABLE                           = NOT PLANNED
SCENARIO-SPECIFIC PRODUCT LOGIC              = FORBIDDEN
```

W80-CA00H closes only after proposal reviewers see and select the authoritative
approval line before submission, rejected business proposals preserve and show
their required reason, VoucherCandidates visibly bind an approved Project,
users select effective K-IFRS accounts by name while the platform writes codes,
and accounting approvals render the exact authoritative voucher revision in a
readable debit/credit form. All protected PostgreSQL, authenticated Playwright,
coverage, replay/restart, zero-residue, and Repository Full Gate requirements
must pass on exact head.
