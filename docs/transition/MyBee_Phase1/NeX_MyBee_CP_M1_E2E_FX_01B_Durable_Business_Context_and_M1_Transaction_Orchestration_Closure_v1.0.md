# NeX MyBee CP-M1-E2E-FX-01B: Durable Business Context and M1 Transaction Orchestration Closure v1.0

## 1. Status And Authority

- Decision date: `2026-11-16`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `d7b2625d9334a7dbd9d5607ff823efb2553e54d2`
- Runtime code changes by this document: none
- Database migration authorized by this document: none by default
- Remote model-provider dependency for this document: none
- Remote model-provider dependency for final implementation acceptance: required

This corrective work order closes the product gap found when the original
`CP-M1-E2E-FX-01` public Golden M1 journey resumed after the installed runtime,
Golden A retirement, and AE coverage-margin prerequisites had passed.

The installed product can resolve an ACTIVE Project, delegate to its PA, admit
a WC claim, schedule background work, select the signed D12/D04 Skills, and
execute either Skill when complete compiled inputs already exist. It does not
yet preserve the business values from the authenticated public request through
that path or deterministically create the approved VoucherCandidate and
authority references required by D04.

The original public M1 E2E must therefore pause. It resumes only after all
`01B` Slices and their protected Gate pass. This work order does not reduce the
frozen M1 acceptance scope or authorize smoke-owned business transitions.

This document supplements, without rewriting:

- `NeX_MyBee_Implementation_Slice_Plan_v1.2.md`;
- `NeX_MyBee_W70_CA01_NSL_Tool_Product_Capability_Registry_and_Skill_Pack_Entry_Reconciliation_v1.0.md`;
- `NeX_MyBee_W70_CA02_Installed_PA_Delegation_and_Multi_Skill_Runtime_Composition_Closure_v1.0.md`;
- `CP-M1-S8-02` and `CP-M1-MB8-01` evidence;
- `CP-M1-E2E-FX-01A.1` through `.5` evidence;
- `CP-M1-GA-RET-02` and `CP-M1-GA-RET-02A` evidence; and
- the immutable Golden A historical quarantine.

Where W70-CA02 can be read as declaring the business-input and transaction
orchestration path complete, this document takes precedence. W70-CA02 remains
authoritative for Project resolution, delegation, installed runtime, signed
Skill selection, deployment, and Golden A retirement.

## 2. Source-Backed Entry Finding

### 2.1 Public Business Values Are Not Durable WorkIntent State

The intent provider may return `entity_selectors` and `parameter_candidates`,
but `build_work_intent_from_decision()` currently initializes both collections
as empty. The Project delegation activator resolves only the Project Code and
replaces the goal with a generic delegation sentence.

Consequently, company, document, counterparty, amount, currency, recognition
date, requested allocation, and other user-supplied business values are not
durable inputs to the delegated PA execution.

### 2.2 Delegation And Claimed Planning Drop Business Context

The compiled `DelegationSpec` carries goal, capability, Project, result
contract, and completion policy. WC's claimed planning source carries the same
bounded set. Neither contract carries a typed, hash-bound business request.

A retry can therefore prove delegation identity but cannot prove that the
same business request is being replayed. A changed amount or allocation could
not be distinguished from a same-semantics retry at the PA planning boundary.

### 2.3 Generic Background Planning Cannot Materialize D04 Inputs

The generic plan binder derives local-capability inputs only from prior step
outputs and the optional attachment manifest. It cannot produce the exact D04
input set:

```text
company_id
candidate_id
expected_candidate_version
expected_candidate_revision
expected_candidate_hash
accounting_approval_evidence_id
```

`build_pa_nsl_invocation_plan()` defines the correct D12-before-D04 ordering
and input shape, but it is not composed into the installed claimed-work
planning path.

### 2.4 D04 Is A Posting Skill, Not Transaction Preparation

The signed `MYBEE.D04.JOURNAL_POSTING` Skill intentionally posts one already
validated and approved VoucherCandidate. It does not:

- submit a business proposal;
- obtain a final ApprovedDocumentEnvelope;
- create and validate a VoucherCandidate;
- request or complete human accounting approval;
- run or verify cost allocation;
- read Project P&L; or
- publish the final PA/WA/IA result.

Those authorities and APIs already exist. The missing part is product runtime
composition, not another ledger, approval engine, or accounting authority.

### 2.5 A Runner-Only Fix Is Prohibited

A runner that pre-creates the approved Candidate, directly invokes EOS
allocation/P&L, writes WC or AE private state, or fabricates a successful
WorkResult would recreate the smoke-owned behavior already retired after the
P8 Demo and GB2 work. Such a runner cannot close M1.

## 3. Closure Objective

`CP-M1-E2E-FX-01B` must establish this installed product path:

```text
authenticated IA request
  -> typed BusinessRequestContext admission
  -> hash-bound WorkIntent persistence
  -> authorized Project resolution and PA delegation
  -> WC WorkItem/Claim/Assignment and context-preserving handoff
  -> PA background transaction preparation
  -> business proposal and WC BUSINESS_FORMAL approval
  -> EOS ApprovedDocumentEnvelope
  -> VoucherCandidate create/validate/review
  -> human accounting approval and fresh OA authority
  -> deterministic signed D12/D04 executable plan
  -> controlled D04 Journal posting and verification/reconciliation
  -> deterministic cost allocation and verification
  -> authorized Project P&L reads
  -> PA WorkResult, WA consumption, and IA result publication
```

Every transition after the public request begins must be owned by installed
product code and an existing authoritative service. The acceptance runner may
seed prerequisite master data before the request and may act as authenticated
human users through public approval routes. It may not own product state
transitions.

## 4. Normative Decisions

### 4.1 ADR-01: Add A Typed, Hash-Bound BusinessRequestContext

The public M1 path introduces `ae.business_request_context.v1`. It is an
untrusted-but-durable statement of user intent, not business authority.

The minimum canonical projection is:

```json
{
  "schema_version": "ae.business_request_context.v1",
  "request_kind": "FINANCE_VOUCHER_POSTING",
  "source_prompt_ref": "AE:INTERACTION:<id>",
  "company_selector": {"kind": "CODE_OR_NAME", "value": "..."},
  "document": {
    "document_type": "BUSINESS_PROPOSAL",
    "subject_ref": "...",
    "subject_revision": 1,
    "content_hash": "sha256:...",
    "attachment_manifest_hash": null
  },
  "transaction": {
    "counterparty_selector": "...",
    "amount": "10000.00",
    "currency": "USD",
    "recognition_date": "YYYY-MM-DD",
    "description": "..."
  },
  "requested_allocation": [
    {"project_code": "...", "ratio": "0.400000"},
    {"project_code": "...", "ratio": "0.600000"}
  ],
  "candidate_provenance": {
    "intent_candidate_hash": "sha256:...",
    "input_context_hash": "sha256:...",
    "model_profile": "...",
    "model_ref": "..."
  },
  "context_hash": "sha256:..."
}
```

Rules:

1. The context contains normalized user inputs and source lineage only.
2. Tenant, requester, Project UUID, membership, OA decision, account ID, FX
   rate, period status, approval proof, Candidate identity, Posting result,
   allocation result, and P&L authority cannot be model-supplied fields.
3. Project Codes may be user-supplied selectors. EOS and OA resolve them to
   current authority before use.
4. Amount uses canonical decimal text, currency uses ISO 4217 uppercase text,
   dates use ISO 8601 calendar dates, and allocation ratios must be positive
   canonical decimals whose total is exactly `1.000000` after admission.
5. The raw prompt is not duplicated into the context. `source_prompt_ref`
   points to the owner-scoped interaction record.
6. Secret, credential, payroll-detail, hidden reasoning, and authority-bearing
   fields are rejected.
7. `context_hash` uses the shared domain-separated semantic hash helper and is
   included in replay and idempotency identity.

### 4.2 ADR-02: Version Existing JSON Contracts; Do Not Add A Table By Default

The context is persisted in the existing JSON authorities:

- `WorkIntent v1.2` adds `business_request_context`;
- `DelegationSpec v1.2` carries the exact context and hash;
- the WC WorkItem persists the admitted context without deriving business
  authority from it; and
- `p7.claimed_work_planning_source.v2` carries the exact context to AE.

Existing `WorkIntent v1.1`, `DelegationSpec v1.0/v1.1`, and claimed planning
source v1 records remain replayable. They cannot be silently upgraded or used
for the M1 transaction path when the business context is absent.

The existing `ae_work_intent.intent_json`, WC WorkItem/delegation JSON, AE
claimed-source JSON, executable plan JSON, and result/evidence references are
sufficient unless implementation proves otherwise. A new database table or
migration requires a separate stop-and-decide amendment.

### 4.3 ADR-03: Preserve Context Across IA, WC, And PA Without Trust Promotion

The exact `context_hash` must remain stable across:

```text
IA WorkIntent
  -> compiled DelegationSpec
  -> WC WorkItem
  -> ClaimExecutionHandoff planning source
  -> PA background WorkIntent
  -> deterministic transaction preparation
  -> executable-plan provenance
  -> WorkResult and final IA result
```

Each boundary validates schema, tenant/requester lineage, Project selectors,
hash, size, classification, and replay identity. WC does not inspect or
rewrite accounting values. AE does not treat the context as proof. EOS, OA,
and WC remain authoritative for all business and approval decisions.

Changed-context replay under the same delegation identity must fail with an
immutable semantic conflict. Exact replay returns the existing WorkItem,
execution, Candidate, Journal, allocation, and result identities.

### 4.4 ADR-04: Productize Transaction Preparation Above Existing APIs

Add a registry-selected, domain-owned M1 transaction preparation adapter. It
must reuse the existing MyBee consumers and public/internal service contracts:

- `NexBusinessApprovalClient` for proposal signoff and final
  `ApprovedDocumentEnvelope` admission;
- `NexVoucherCandidateClient` for Candidate creation, validation, review
  submission, and review projection;
- WC public approval APIs and durable events for human decisions;
- EOS posting-admission and accounting-proof projections; and
- fresh OA authorization at every approval or governed-write boundary.

The adapter is product code used by the installed worker. It is selected by
the Product Capability Registry and exact adapter identity, not by tenant,
amount, model text, test filename, or Golden scenario branch.

Only the exact operations needed by M1 may become active in this corrective
packet:

```text
PROJECT.WORK_CODE_SET.GET
FINANCE.VOUCHER_CANDIDATE.CREATE_V2
FINANCE.VOUCHER_CANDIDATE.VALIDATE
FINANCE.VOUCHER_POSTING.ADMIT
FINANCE.VOUCHER.APPROVE_AND_POST
FINANCE.COST_ALLOCATION.RUN
FINANCE.COST_ALLOCATION.VERIFY
FINANCE.PROJECT_PNL.GET
```

The signed D12 and D04 Skills remain the only NSL Skills activated by M1.
Preparation and post-write service adapters do not masquerade as signed NSL
Skills. Activating another Tool or Skill requires its own exact contract,
artifact, trust, and release decision.

### 4.5 ADR-05: Materialize D12/D04 Inputs From Authorities, Never The Model

After proposal and accounting approval complete, the installed PA runtime
builds and verifies the exact deterministic invocation plan with
`build_pa_nsl_invocation_plan()` and the existing compiler/persistence path.

Input origins are fixed as follows:

| Input | Authoritative origin |
| --- | --- |
| `tenant_id`, requester | authenticated execution and OA subject |
| `project_id`, Project Code, PA | EOS Project resolution, OA entitlement, synchronized AE PA projection |
| Project work-code set | D12 `PROJECT.WORK_CODE_SET.GET` result |
| `company_id` | EOS LegalEntity resolution against the admitted company selector |
| Candidate ID/version/revision/hash | EOS VoucherCandidate create/validate/review projection |
| accounting approval evidence ID | final EOS accounting-proof projection backed by WC human decision and fresh OA authority |
| effective/recognition date | admitted request context followed by EOS period validation |
| Skill ID/version/hash and Tool adapter | Product Capability Registry and signed M1 release |

The model may classify intent and extract bounded business candidates. It
cannot choose or override any value in the right-hand authority column.

The materialized plan must use the ordinary AE `AgentPlan -> validation ->
ExecutablePlan -> schedule_next()` path. The domain builder cannot directly
insert executable steps or runtime jobs.

### 4.6 ADR-06: Complete Post-Write Work Through Product APIs

After verified Journal commit, the installed orchestration must:

1. resolve the eligible source-pool component from the immutable Posted GL;
2. run the already released allocation plan with the requested Project ratios
   admitted against current EOS authority;
3. verify conservation, idempotency, and zero unallocated amount for the M1
   sample;
4. read both Project P&L projections through `NexProjectPnlClient` using fresh
   OA Project entitlement and privacy guards;
5. publish a redacted PA WorkResult with authoritative Journal, FX snapshot,
   allocation, P&L watermark, and evidence references;
6. deliver and ACK the WorkResult through WC;
7. allow WA to consume the published source projection; and
8. publish the owner-scoped IA result without private payroll, approval-body,
   token, or internal diagnostic content.

Allocation and P&L remain EOS authorities. WorkResult and IA publication are
projections, not alternative financial SoRs.

### 4.7 ADR-07: Preserve Human Approval Separation

The journey retains distinct approval boundaries:

- business proposal `BUSINESS_FORMAL` approval;
- human accounting approval and EOS accounting proof;
- NSL WRITE checkpoint approval for the exact D04 invocation; and
- current OA authorization at execution time.

No proof satisfies another proof type. The requester cannot self-approve when
the admitted policy prohibits it. Revocation, expiry, changed Candidate
revision, changed context hash, or changed Project authority invalidates the
pending transition and fails closed.

### 4.8 ADR-08: Golden A Cannot Return As A Fallback

If the `01B` context, adapter, release, or authority is unavailable, the M1
request becomes unavailable, clarification-required, or retryable according
to the typed error. It cannot fall back to Golden A, a Demo fixture, a direct
consumer, or a success payload.

Rollback targets the preceding generalized installed runtime release and
disables new M1 transaction admission. Historical Golden A files remain
hash-pinned quarantine evidence only.

## 5. Data-Origin And Ownership Matrix

| Value or transition | Owner | Runtime consumer | Prohibited substitute |
| --- | --- | --- | --- |
| authenticated tenant/requester | OA-backed AE session | IA admission, WC, PA | fixed tenant or employee in product code |
| user business values | owner-scoped AE interaction and hash-bound context | PA preparation | runner fixture after request start |
| Project identity/state | EOS; authorization in OA | IA/PA | model-selected UUID or runner mapping |
| PA identity/state | synchronized AE projection sourced from EOS lifecycle | WC/AE | scenario-owned PA ID |
| proposal and document approval | WC workflow plus EOS envelope | PA preparation | fabricated approval receipt |
| Candidate and accounting validation | EOS | PA preparation and D04 | runner-created Candidate or direct SQL |
| accounting human proof | WC decision, EOS proof, fresh OA authority | D04 admission | NSL approval or model text |
| FX and period | EOS approved policy/snapshot/period | Candidate validation and Posting | embedded rate or OPEN flag |
| Journal | EOS atomic Posting | allocation and result publication | direct insert or fabricated journal ID |
| allocation | EOS released plan and batch | P&L and result publication | arithmetic-only runner assertion |
| P&L | EOS privacy-protected projection | PA/IA/WA result | direct cross-service DB read |
| Skill and operation identity | signed release and Product Capability Registry | AE worker | filename, prompt, or directory order |
| WorkResult and publication | PA/AE/WC/WA durable transitions | IA user result | runner-owned success payload |

## 6. Corrective Slice Plan

### CP-M1-E2E-FX-01B.1: Contract And Source Boundary Freeze

- inventory every source and persistence boundary from IA prompt to final
  result;
- admit `ae.business_request_context.v1` and its JSON Schema;
- freeze `WorkIntent v1.2`, `DelegationSpec v1.2`, and claimed planning source
  v2 compatibility rules;
- define context size, field, classification, hash, and error contracts;
- record the exact operation/adapter activation set; and
- add static guards for raw prompt, authority field, fixed business value,
  Golden A, direct SQL, and runner-owned transition residue.

Remote provider: not required. Database migration: none.

### CP-M1-E2E-FX-01B.2: Durable WorkIntent Business Context Admission

- normalize admitted intent candidates into the typed context;
- preserve exact source and model provenance without storing hidden reasoning;
- persist the context and hash in WorkIntent v1.2;
- reject malformed decimals, currency, dates, allocation totals, ambiguous
  Project selectors, authority-bearing fields, oversized context, and tamper;
- preserve v1.1 replay behavior; and
- prove two different valid business requests generate different context and
  WorkIntent hashes.

Remote provider: mock required for regression; live provider deferred to
`.7`. Database migration: none.

### CP-M1-E2E-FX-01B.3: AE-WC-PA Context Propagation And Replay Guard

- carry the exact context/hash through DelegationSpec v1.2, WC WorkItem,
  ClaimExecutionHandoff, and claimed planning source v2;
- bind idempotency and same-semantics replay to the context hash;
- preserve requester, tenant, Project, parent execution, claim generation,
  and result-contract lineage;
- reject changed-context replay, cross-tenant context, stale claim,
  unsupported legacy context, and missing context; and
- prove actual AE/WC PostgreSQL persistence and restart replay.

Remote provider: not required. Database migration: none by default.

Checkpoint Gate after `.3`:

- focused AE/WC unit and regression;
- contract/schema/OpenAPI validation where applicable;
- actual AE/WC PostgreSQL smoke;
- replay/tamper/cross-tenant matrix; and
- repository diff and residue checks.

### CP-M1-E2E-FX-01B.4: Authoritative Transaction Preparation And Approval

- implement the registry-selected installed preparation adapter;
- resolve company and Projects through EOS and fresh OA authority;
- submit the business proposal and wait for WC BUSINESS_FORMAL approval;
- admit the final EOS ApprovedDocumentEnvelope;
- create and validate the VoucherCandidate;
- request human accounting review and wait for final EOS accounting proof;
- preserve SoD, expiry, revision, payload hash, and idempotency; and
- prove exact retry and changed-request conflict behavior.

Remote provider: not required after admitted context. Actual OA/WC/EOS/AE
PostgreSQL smoke: required.

### CP-M1-E2E-FX-01B.5: Deterministic D12/D04 Plan Materialization

- call D12 for current Project work-code context;
- construct and verify the exact PA invocation plan from authority results;
- lower it through the existing AgentPlan validation and ExecutablePlan
  compiler rather than direct runtime inserts;
- bind all D04 literals from EOS/OA/WC outputs;
- execute approval wait/resume, controlled WRITE, verification,
  reconciliation, and UNKNOWN recovery through the installed worker; and
- prove signature, version, hash, ordering, dependency, replay, restart, and
  stale-authority failure cases.

Remote provider: not required for deterministic materialization. Actual
AE/OA/WC/EOS PostgreSQL smoke: required.

### CP-M1-E2E-FX-01B.6: Allocation, P&L, WA, And IA Result Integration

- run and verify deterministic allocation from the verified Posted Journal;
- enforce exact conservation and no duplicate batch;
- read both Project P&L projections with current entitlement and privacy
  policy;
- produce a redacted PA WorkResult containing exact authority references;
- complete WC delivery/ACK, WA source consumption, and IA publication;
- prove lost ACK, duplicate event, restart, unauthorized Project read,
  cross-tenant read, and privacy-difference negatives; and
- prove final result idempotency without duplicate Journal or allocation.

Remote provider: not required. Actual OA/AE/WC/EOS/WA PostgreSQL smoke:
required.

Checkpoint Gate after `.6`:

- complete focused product regression;
- actual five-service PostgreSQL protected smoke;
- controlled restart and replay matrix;
- no duplicate financial mutation;
- authorization/privacy negatives; and
- installed runtime, Compose, OCI, and zero-residue audit.

### CP-M1-E2E-FX-01B.7: Protected Product Closure And Resume Decision

- run authenticated public API and Playwright acceptance;
- use live Qwen3.5-9B INTENT and PLAN generation;
- execute at least two non-identical positive business requests through the
  same product composition;
- execute the exact M1 USD 10,000 at KRW 1,350.20, 40/60 allocation journey;
- prove retry, lost ACK, restart, revocation, UNKNOWN/reconciliation, privacy,
  tamper, and cross-tenant negatives;
- register and audit the successor Golden Journey runner;
- run the Repository Full Gate; and
- issue the explicit original `CP-M1-E2E-FX-01` resume decision.

Remote provider: required. Actual OA/AE/WC/EOS/WA PostgreSQL: required.
Authenticated Playwright: required. Repository Full Gate: required.

## 7. Verification Matrix

### 7.1 Positive Variants

At minimum, prove:

1. USD 10,000 with 40/60 allocation and two authorized Projects;
2. a different amount, currency/date or allocation ratio using the same
   runtime and registry; and
3. exact replay of each request returning original authoritative identities.

Product source, registry, Compose, and process environment must remain
unchanged between variants.

### 7.2 Contract And Tamper Negatives

- missing, unknown, duplicate, oversized, or authority-bearing context field;
- invalid decimal, currency, date, ratio, or ratio total;
- mismatched context hash at every propagation boundary;
- same delegation identity with changed business context;
- stale or altered Candidate version/revision/hash;
- wrong approval evidence type or expired/revoked proof;
- unsigned/wrong Skill, adapter, registry, or release identity; and
- direct legacy v1 claimed source attempting D04 execution.

### 7.3 Authorization And Privacy Negatives

- unauthenticated IA request;
- inactive or unauthorized requester;
- missing, inactive, ambiguous, or unauthorized Project;
- inactive PA or wrong tenant/Project PA;
- requester self-approval when prohibited;
- unauthorized accountant;
- cross-company, cross-Project, and cross-tenant Candidate/P&L access;
- payroll/private source leakage; and
- difference-attack suppression regression.

### 7.4 Reliability And Exactly-Once Negatives

- duplicate public request;
- duplicate WC claim/handoff;
- duplicate approval decision and resume;
- worker crash before and after each durable checkpoint;
- provider timeout before authority mutation;
- EOS `UNKNOWN_COMMIT_STATE` with reconciliation;
- outbox or WorkResult ACK loss;
- restart between proposal, Candidate, approval, D04, allocation, and result
  publication; and
- cleanup followed by zero acceptance-owned residue.

## 8. M1 Exact Acceptance Assertions

The final `.7` Gate must prove:

```text
transaction amount              = USD 10,000.00
approved FX market-base rate    = KRW 1,350.20 / USD
functional amount               = KRW 13,502,000
Project A allocation            = KRW 5,400,800
Project B allocation            = KRW 8,101,200
allocated total                 = KRW 13,502,000
unallocated total               = KRW 0
PostedJournal count             = 1
allocation batch count          = 1
duplicate Journal/Batch         = 0
Project P&L authorization       = PASS for authorized Projects only
PA WorkResult delivery/ACK      = PASS
WA consumption                  = PASS
IA owner-visible result         = PASS
```

These values are acceptance inputs and assertions in the protected runner.
They cannot appear as runtime constants, tenant-specific branches, default
business values, or fabricated success responses.

## 9. Prohibited Shortcuts

The following cannot satisfy `01B` or the original M1 Gate:

- preserving business values only in raw prompt text;
- serializing structured context into a free-text goal or description;
- placing approval proofs, account IDs, FX rates, or Candidate identities in
  model output authority;
- direct AE/WC/EOS/WA private-state SQL from a runner;
- runner-created approved Candidate, Journal, allocation, P&L, WorkResult, or
  IA result after the public request starts;
- calling EOS Journal/allocation/P&L directly from the E2E runner in place of
  installed PA execution;
- adding an M1, tenant, Project, amount, rate, or allocation branch to generic
  admission, compiler, dispatcher, worker, or NSL runtime code;
- reactivating Golden A or its direct consumer as fallback;
- treating unsigned candidate Tool descriptors as active signed Skills;
- using a test-only runtime factory, adapter, token, or service route; or
- claiming E2E closure from component tests or mock-only acceptance.

## 10. Stop Conditions

Implementation stops for an explicit design decision if any of the following
is proven:

1. the typed context cannot fit existing JSON authorities without overloading
   their ownership or query requirements;
2. a new durable transaction-orchestration entity or migration is required;
3. an existing service API cannot express a required authority transition;
4. the current Product Capability Registry cannot admit the exact adapter
   identity without weakening signed Skill semantics;
5. the existing AgentPlan/ExecutablePlan compiler cannot materialize the
   verified D12/D04 plan without a domain branch in generic code;
6. human business or accounting approval would require direct private-state
   mutation;
7. allocation/P&L completion cannot be tied to the exact Journal lineage;
8. PA WorkResult or WA/IA publication requires fabricated success state; or
9. the protected runner would need to own a product transition.

## 11. Closure And Original Slice Resume

`CP-M1-E2E-FX-01B` closes only when:

1. user business inputs survive public admission through PA planning as one
   exact typed and hash-bound context;
2. no model or runner value becomes authority without owner-service
   validation;
3. installed product code creates and approves the exact Candidate through
   existing APIs;
4. the ordinary AgentPlan/ExecutablePlan path materializes and executes signed
   D12 then D04 with authority-derived inputs;
5. Journal, allocation, P&L, PA/WC/WA, and IA result lineage is complete and
   exactly-once;
6. actual PostgreSQL, live generation, Playwright, restart/replay, privacy,
   tamper, and zero-residue evidence pass;
7. no Golden A, Demo fixture, direct SQL, private-state call, or fixed business
   runtime value is active; and
8. the Repository Full Gate passes without reducing coverage or exclusions.

After these conditions pass, implementation returns to the original
`CP-M1-E2E-FX-01` and executes its final public M1 Golden journey. `01B`
closure is a prerequisite and does not by itself declare W70 or M1 complete.
