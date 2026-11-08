# P8 Pre-Architecture Decision — Controlled WRITE, Approval, and Enterprise OS v1.0

**Status:** DRAFT FOR REVIEW / P8 SOURCE AUDIT ENTRY CANDIDATE  
**Phase:** P8 — Controlled WRITE / Approval / Enterprise OS  
**Predecessor:** P7 Final Contract Freeze / P7-CA02B Closed  
**P7 Baseline Commit:** `ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a`  
**P7 Baseline Tree:** `c0901e9e2af266b400adc07dddd815c77fae2ae1`  
**Primary Goal:** Connect deterministic NSL v0.2 Controlled WRITE to authoritative Enterprise OS business transactions without transferring execution authority to an LLM  
**Date:** 2026-10-20

---

## 1. Purpose

P8 is the first NeX Platform transition phase in which an Agent-selected plan may ultimately produce an authoritative business side effect.

P4-P7 established:

```text
Prompt
→ Intent / Context / Plan Candidate
→ deterministic admission
→ AgentExecution
→ JobQueue / Runtime
→ NSL READ
→ DELEGATE_WORK
→ WC WorkItem / Claim
→ CA / PA / EA execution
→ WorkResult
→ RESUME_EXECUTION
```

P8 extends this into:

```text
Prompt
→ Agent Plan
→ deterministic PlanValidation
→ LOCAL_SKILL
→ NSL v0.2 READ / CHECK
→ WriteIntent Freeze
→ Approval
→ Suspend / Resume
→ WriteGuard
→ durable WRITE_REQUESTED
→ idempotent Canonical WRITE
→ Enterprise OS
→ CommitState
→ Post-Write Verification
→ AgentResult / WorkResult
```

P8 SHALL preserve the core NeX design principle:

> **The LLM may propose what should be done, but deterministic systems decide whether a business side effect is authorized, safe, committed, and verified.**

---

## 2. Architecture Authority

The P8 implementation SHALL follow this authority order:

```text
Integrated Frozen Platform v2.1 / Agent v2.1 / NSL v0.2 Final Freeze
> Frozen normative machine-readable contracts
> P7 Final As-Built / P7-CA02B closure baseline
> NSL v0.1 As-Built source
> P8 source-backed contract closure
> P8 SRS
> P8 implementation slice plan
> implementation convenience
```

Frozen documents SHALL NOT be edited to match implementation convenience.

If current source and Frozen semantics differ, P8 SHALL create an explicit source-backed transition decision before changing runtime semantics.

---

## 3. P8 Is Not an ERP Big-Bang

P8 does **not** implement the entire Enterprise OS business scope.

The long-term EOS domain may include:

```text
Organization
Project
Account
Voucher / Expense
Formal Approval
Ledger
Project P/L
Procurement
Accounting Period
Legacy ERP / Groupware integration
```

P8 initially implements only the minimum business domain needed to validate Controlled WRITE end-to-end.

Initial target:

```text
Minimal Organization
Minimal Project
Minimal Account
Voucher Draft
Approval binding
Canonical WRITE API
Idempotency
Commit semantics
Transactional Outbox
Audit / Trace lineage
```

The canonical first protected WRITE journey is:

```text
Golden A — Voucher Draft WRITE
```

Ledger posting, P/L, procurement lifecycle, accounting close, and broad ERP replacement SHALL NOT be prerequisites for the first P8 Golden A acceptance.

---

## 4. Primary Architecture Decisions

P8 adopts the following top-level decisions.

```text
PAD-01  NSL v0.2 remains in the independent NSL repository.
PAD-02  Separate Repository != Separate Runtime Process.
PAD-03  NeX-EOS is implemented inside the NeX Platform monorepo.
PAD-04  NeX-EOS starts as a modular monolith with explicit bounded contexts.
PAD-05  NeX-EOS owns authoritative business transactions, not WC Work.
PAD-06  NSL owns deterministic WRITE semantics, not business domain semantics.
PAD-07  WC remains the Work / Human WorkItem coordination SoR.
PAD-08  OA remains Principal / RoleBinding / authorization SoR.
PAD-09  EOS becomes Business Organization / formal business approval SoR.
PAD-10  IA is the initial Human Approval interaction channel, not Approval SoR.
PAD-11  Approval domains remain semantically distinct.
PAD-12  Multi-stage corporate approval is not implemented as repeated NSL approve statements.
PAD-13  WC gains a deterministic Delegation Guard.
PAD-14  UNKNOWN_COMMIT_STATE never triggers blind business retry.
PAD-15  Golden A is closed before broader EOS expansion.
```

---

## 5. Repository Decision — NSL v0.2

NSL v0.2 SHALL continue to be developed in the independent NSL repository:

```text
nurigitdev/2608_nsl
```

The target is an additive upgrade of the real NSL v0.1 codebase.

```text
NSL v0.1
Compiler / IR / Runtime / Security / Audit / Replay / NSP Trust
                         │
                         │ preserve + extend
                         ▼
NSL v0.2
same deterministic kernel
+ Controlled WRITE
+ Approval Suspend / Resume semantics
+ BusinessOperationId / Idempotency
+ CommitState
+ VerificationStatus
```

P8 SHALL NOT move NSL compiler/runtime source into `2607_nex_platform`.

### 5.1 Distribution into Platform

Recommended production integration:

```text
2608_nsl source
    ↓
build / test / certify
    ↓
nex_skill_language-0.2.x.whl
    ↓
exact source revision
exact wheel SHA256
exact package version
    ↓
Platform package admission
    ↓
NSL_V02_IN_PROCESS
```

Initial runtime profile:

```text
NSL source ownership    = independent repository
runtime deployment      = AE in-process library allowed
production admission    = exact revision + wheel SHA256
```

A later process-isolated NSL profile may be added if WRITE isolation, blast-radius reduction, or operational independence justifies it. It is not a P8 entry requirement.

---

## 6. Enterprise OS Repository Decision

NeX-EOS SHALL be added to the NeX Platform monorepo.

Recommended structure:

```text
2607_nex_platform/

services/
  nex-eos/

database/
  nex-eos/

contracts/
  openapi/
    nex-eos.openapi.yaml
```

Expected service-local database:

```text
nex_eos_dev
nex_eos_test
nex_eos_user
```

Cross-service direct database writes remain forbidden.

---

## 7. Enterprise OS Internal Architecture

NeX-EOS SHALL initially be a modular monolith.

Recommended logical bounded contexts:

```text
nex_eos/
│
├─ organization/
├─ project/
├─ account/
├─ approval/
├─ finance/
│   └─ voucher/
├─ ledger/              # later P8/P9 expansion
├─ common/
├─ api/
└─ persistence/
```

This is a logical responsibility structure, not a mandatory physical package tree.

Do not split each EOS domain into a microservice during the initial P8 slice.

A later service split is permitted only after domain ownership, transaction boundary, operational scaling need, team ownership, or failure isolation justify it.

---

## 8. NSL vs Enterprise OS Responsibility Boundary

The fundamental P8 responsibility split is:

```text
NSL
= how a WRITE is performed safely and deterministically

EOS
= what that WRITE means in the business domain
```

NSL owns:

```text
static WRITE safety
WriteIntent
PayloadHash / WriteIntentHash
ApprovalRequest binding
Checkpoint / suspend semantics
ApprovalEvidence validation
actual IdempotencyKey derivation
WriteGuard
WRITE_REQUESTED evidence
CommitState interpretation
VerificationStatus
Replay / no-live-WRITE safety
detailed NSL execution/write evidence
```

EOS owns:

```text
business aggregate state
business invariants
Project / Account / Voucher identity
authoritative transaction state machine
write-time business preconditions
business idempotency acceptance
business commit result
domain events
formal business approval where required
```

NSL SHALL NOT implement accounting policy or voucher lifecycle semantics.

EOS SHALL NOT implement NSL compiler/runtime semantics.

---

## 9. Canonical P8 WRITE Path

```text
User Prompt
    ↓
IA AgentExecution
    ↓
Intent / Context / Plan Candidate
    ↓
Deterministic PlanValidation
    ↓
LOCAL_SKILL
    ↓
NSL v0.2
READ / CHECK
    ↓
PreWriteEligibility
    ↓
WriteIntent Freeze
    ↓
ApprovalRequestId
    ↓
durable Checkpoint
    ↓
WAITING_FOR_APPROVAL
    ↓
Agent / Platform Control Plane
    ↓
Human Approval
    ↓
RESUME_EXECUTION
    ↓
same NSLExecutionId
same BusinessOperationId
    ↓
ApprovalEvidence validation
    ↓
WriteGuard
    ↓
IdempotencyKey
    ↓
durable WRITE_REQUESTED
    ↓
GovernedWriteExecutionPort
    ↓
EOS Canonical Command API
    ↓
CommitState
    ↓
Post-Write Verification
    ↓
AgentResult / WorkResult
```

---

## 10. Delegation Guard — Motivation

P7 enabled background Agent delegation:

```text
IA
→ DELEGATE_WORK
→ WC WorkItem
→ Claim
→ CA / PA / EA
```

A claimed background Agent may itself produce another valid `DELEGATE_WORK`.

Without a deterministic boundary, unintended recursion may occur:

```text
PA-A
→ EA-B
→ CA-C
→ PA-A
→ EA-B
→ ...
```

or exponential fan-out:

```text
A
├─ B1
├─ B2
├─ B3
├─ B4
└─ B5

Each child
→ five more children
→ ...
```

P8 SHALL therefore add a WC-owned Delegation Guard.

---

## 11. Delegation Guard — Hop Limit

The networking concept of TTL is useful, but canonical P8 terminology SHALL prefer:

```text
Delegation Hop Limit
Delegation Depth
Delegation Budget
```

over generic `TTL`, because this is not a time-to-live value.

Initial logical model:

```text
root_work_item_id
parent_work_item_id
delegation_depth
max_delegation_depth
```

Recommended initial policy:

```text
max_delegation_depth = 10
```

The exact default remains policy-configurable.

The LLM SHALL NOT select or increase the maximum depth.

---

## 12. Delegation Depth Semantics

Delegation depth is consumed only when a new delegated child WorkItem is created.

```text
Claim existing WorkItem
→ no depth change

Agent handles WorkItem directly
→ no depth change

Agent executes DELEGATE_WORK
→ prospective child depth = parent depth + 1
```

Example:

```text
Root W1
  depth = 1
  max   = 10

W1 → W2
  depth(W2) = 2

...

W10
  depth = 10
```

If the Agent processing W10 attempts another delegation:

```text
prospective depth = 11
max depth         = 10
```

then:

```text
Child WorkItem creation = REJECTED
```

---

## 13. Hop Limit Exhaustion Does Not Automatically Fail the Current WorkItem

P8 SHALL distinguish:

```text
cannot delegate further
```

from:

```text
cannot complete current work
```

Therefore `delegation_depth == max_delegation_depth` does NOT automatically invalidate the current claimed WorkItem.

The current Agent may still:

```text
complete locally
return a WorkResult
produce a deterministic failure result
request allowed human input
```

Only the attempted new delegation is blocked.

Because the current P7 WorkItem state contract does not define a generic `FAILED` state, P8 SHALL NOT casually add one merely for hop-limit exhaustion.

Preferred behavior:

```text
DELEGATE_WORK Step
→ deterministic DELEGATION_HOP_LIMIT_EXCEEDED
→ child WorkItem count = 0
→ child Claim count = 0
→ child AgentExecution count = 0
```

The parent execution handles the failed step through existing Agent runtime/result semantics.

---

## 14. Delegation Cycle Detection

Hop Limit alone eventually stops a cycle but permits unnecessary repeated work.

P8 SHALL additionally provide cycle detection.

Logical rule:

```text
new selected claimant Agent
must not recreate a forbidden ancestor-agent cycle
within the same root delegation lineage
```

Example:

```text
PA-A
→ EA-B
→ CA-C
→ PA-A
```

The final candidate `PA-A` is rejected as a cyclic delegation candidate.

Required outcome:

```text
DELEGATION_CYCLE_DETECTED
→ no new execution authority
```

The exact persisted lineage representation SHALL be chosen during Source Audit.

Possible implementations include:

```text
parent WorkItem ancestry traversal
claim/assignment lineage traversal
materialized delegation lineage
hash-safe lineage projection
```

Do not duplicate Agent Registry identity ownership inside WC.

---

## 15. Delegation Fan-Out Guard

Depth control does not prevent exponential growth.

P8 SHALL also define bounded fan-out.

Logical controls:

```text
max_children_per_work_item
max_descendants_per_root
```

Recommended initial profile may use conservative values such as:

```text
max_delegation_depth       = 10
max_children_per_work_item = 5
max_descendants_per_root   = 50 or 100
```

Exact values SHALL remain policy-configurable and require Source Audit / performance review before implementation.

Core invariant:

> **An LLM plan may request delegation, but only WC deterministic policy may admit the delegated child WorkItem.**

---

## 16. Delegation Guard Ownership

Delegation Guard is a WC responsibility.

```text
WC owns:
  WorkItem
  parent/child Work lineage
  delegation depth
  delegation budget
  deterministic cycle/fan-out admission
```

AE may carry the resulting metadata for execution context and traceability.

AE SHALL NOT become the canonical delegation-budget SoR.

OA may authorize delegation permission:

```text
work:delegate
```

but OA does not decide hop-depth or cycle safety.

Final admission conjunction:

```text
Plan contains DELEGATE_WORK
AND current OA work:delegate
AND WC hop limit PASS
AND WC cycle check PASS
AND WC fan-out budget PASS
→ child WorkItem create
```

---

## 17. Organization Ownership Decision

P8 SHALL separate security identity from business organization structure.

### OA owns

```text
Principal
Authentication identity
Credential / service identity
RoleBinding
Security scopes
current authorization decision
decision-time policy evidence
```

### EOS owns

```text
Organization
OrgUnit
business reporting hierarchy
business position
management chain
approval policy
approval instance / stage
formal business approval proof
```

EOS SHALL reference people through stable OA Principal refs.

EOS SHALL NOT become the authentication identity SoR.

---

## 18. Initial EOS Organization Model

The initial EOS organization model may remain intentionally small.

Logical entities:

```text
OrgUnit
Position
PositionAssignment
ReportingRelation
ActingAuthority       # later/optional initial extension
```

Example:

```text
OrgUnit
────────────────────
org_unit_id
name
org_unit_type
parent_org_unit_id
status
effective_period

Position
────────────────────
position_id
position_type
org_unit_id

PositionAssignment
────────────────────
position_assignment_id
position_id
principal_ref        → OA Principal
effective_from
effective_until
status
```

---

## 19. Management / Approval Escalation Ladder

The initial corporate escalation ladder SHALL support:

```text
PART_LEAD
    ↓
TEAM_LEAD
    ↓
GROUP_LEAD
    ↓
CEO
    ↓
CHAIRMAN
```

This is a canonical **capability / policy ladder**, not a requirement that every approval request traverse every level.

Examples:

```text
small operational request
→ PART_LEAD

team-level request
→ PART_LEAD → TEAM_LEAD

large project expenditure
→ TEAM_LEAD → GROUP_LEAD → CEO

strategic / exceptional transaction
→ GROUP_LEAD → CEO → CHAIRMAN
```

ApprovalPolicy SHALL determine required stages.

LLM output SHALL NOT determine the authoritative corporate approval chain.

---

## 20. Approval Domain Separation

P8 SHALL preserve the Frozen distinction:

```text
Human Confirmation
!= Agent FORMAL_APPROVAL
!= NSL WRITE Approval
!= OA Step-up
```

In addition, EOS formal business approval remains a distinct business-domain concept.

The P8 implementation SHALL not collapse these into a single generic `approval` boolean.

---

## 21. NSL WRITE Approval

NSL WRITE Approval answers:

> **May this exact frozen WriteIntent be executed?**

It is bound to:

```text
NSLExecutionId
BusinessOperationId
ApprovalRequestId
WriteNodeId
PayloadHash
WriteIntentHash
CheckpointVersion
```

NSL owns:

```text
ApprovalRequest semantics
WriteIntent binding
ApprovalEvidence validation
Resume-time integrity validation
```

NSL does not own:

```text
corporate organization chart
approver selection
human UI
notification
multi-stage corporate routing
long-lived approval workflow
```

---

## 22. EOS Formal Business Approval

EOS Formal Business Approval answers:

> **Does the company approve this business operation under its domain policy?**

EOS may use:

```text
transaction type
amount
project
account
risk
organization
requester position
separation-of-duties policy
```

to derive a staged corporate approval route.

Example:

```text
ApprovalPolicy
    ↓
ApprovalInstance
    ↓
Stage 1 PART_LEAD
    ↓
Stage 2 TEAM_LEAD
    ↓
Stage 3 GROUP_LEAD
    ↓
Stage 4 CEO
    ↓
Stage 5 CHAIRMAN
```

Not every policy requires all five stages.

---

## 23. WC ApprovalWorkItem

WC SHALL remain the durable human-work coordination layer.

Expected responsibilities:

```text
ApprovalWorkItem
PENDING / APPROVED / REJECTED / EXPIRED / CANCELLED
target approver / role / org scope
human assignment
decision event delivery
resume trigger linkage
```

P8 Source Audit SHALL confirm exactly how existing Frozen `ApprovalWorkItem` domains and the `BusinessApprovalAdapter` map to EOS formal business approval.

P8 SHALL NOT invent a new ApprovalWorkItem domain enum before this source-backed mapping is closed.

---

## 24. IA Human Approval Interface

IA is the initial approval interaction surface.

IA is not an Approval SoR.

Initial behavior:

```text
Approver logs in
    ↓
IA fetches pending HumanGateView / ApprovalWorkItem projection
    ↓
IA displays:
  title
  safe summary
  request source
  approval domain
  business context
  expiration if applicable
    ↓
Approver selects APPROVE / REJECT
    ↓
current OA authorization check
    ↓
decision submitted
```

Example:

```text
승인 대기

[NSL WRITE]
프로젝트 A 전표 Draft 생성
요청자: 홍길동
금액: 35,000,000 KRW
[상세] [승인] [반려]

[FORMAL APPROVAL]
프로젝트 B 구매 업무
[상세] [승인] [반려]
```

The UI SHALL display only metadata-safe / policy-approved content.

Raw protected WRITE payloads SHALL not be copied into generic notification messages.

---

## 25. Online / Offline Approval Delivery

Initial P8 behavior:

```text
Approver online
→ IA Approval Inbox

Approver offline
→ Approval remains durable PENDING
→ displayed at next IA session
```

Presence-aware real-time push is not required for the first Golden A.

Future extensions may include:

```text
Email notification
mobile push
Teams / Slack
other enterprise messaging
```

Initial Email behavior SHOULD be:

```text
approval notification
+ authenticated deep link
```

rather than insecure email-reply approval.

---

## 26. Long Absence / Acting Authority

Long-term absence is not only a notification problem. It is an authority delegation problem.

Future/extended EOS model:

```text
ActingAuthority
────────────────────
delegator_principal_ref
acting_principal_ref
org_scope_ref
approval_domain / policy scope
valid_from
valid_until
reason_ref
status
```

Decision-time authority SHALL still be checked by OA.

EOS determines:

```text
who is the business substitute candidate?
```

OA determines:

```text
is this principal currently allowed to approve?
```

---

## 27. Multi-Stage Approval Must Not Be Repeated NSL Approve Statements

Frozen NSL v0.2 STRICT semantics are based on a strongly bounded WRITE model.

The default relation remains:

```text
one NSL WRITE
↔ one NSL Approval binding
```

P8 SHALL NOT model corporate routing as:

```text
approve PART_LEAD
approve TEAM_LEAD
approve GROUP_LEAD
approve CEO
approve CHAIRMAN
write FINANCE.CREATE_VOUCHER_DRAFT
```

This would incorrectly make NSL a corporate workflow language.

Instead:

```text
NSL
→ one ApprovalRequestId
→ exact WriteIntent

EOS / WC Approval Workflow
→ Stage 1 PART_LEAD
→ Stage 2 TEAM_LEAD
→ Stage 3 GROUP_LEAD
→ Stage 4 CEO
→ Stage 5 CHAIRMAN
→ final business approval proof

NSL
→ receives required ApprovalEvidence
→ validates exact binding
→ resumes WRITE
```

The exact relationship between final EOS approval proof and NSL ApprovalEvidence SHALL be source-backed in P8 Source Audit.

---

## 28. Approval UI Unification, Semantic Separation

Users should not need multiple confusing approval applications.

P8 SHOULD provide one IA-facing Human Approval experience.

However the backend SHALL preserve:

```text
UI unification
!= semantic/domain unification
```

IA may render:

```text
Human Confirmation
Agent Formal Approval
NSL WRITE Approval
Business Formal Approval
```

through one HumanGate-style inbox while retaining distinct:

```text
source records
policy
authority
evidence
resume behavior
audit lineage
```

---

## 29. P7 Wait/Resume Reuse

P8 SHALL reuse the P7 durable wait/resume architecture.

P7 already established:

```text
durable WaitRegistration
external event inbox
deduplicated resume job
one satisfied wait
→ at most one RESUME_EXECUTION
```

P8 extends the wait source to NSL Approval.

Target flow:

```text
NSL
→ durable checkpoint
→ WAITING_FOR_APPROVAL

AE
→ AgentExecution WAITING_APPROVAL
→ WaitRegistration(wait_source = NSL_APPROVAL)

WC / Approval Provider
→ human decision

Approval Event
→ AE event inbox

AE
→ RESUME_EXECUTION

NSL
→ same NSLExecutionId
→ same BusinessOperationId
→ validate ApprovalEvidence
→ continue
```

Long-running workers SHALL NOT block while waiting for a human decision.

---

## 30. BusinessOperationId

`BusinessOperationId` is a Platform-owned stable semantic operation identity.

It SHALL remain stable across:

```text
NSL suspend
approval wait
resume
RuntimeJob retry
runtime re-execution
reconciliation
```

It is distinct from:

```text
AgentExecutionId
NSLExecutionId
RuntimeJobId
WorkItemId
ApprovalRequestId
ApprovalWorkItemId
```

The Agent Compiler SHALL NOT generate the actual NSL IdempotencyKey.

NSL derives the actual WRITE idempotency domain from the stable business operation identity and write node identity.

---

## 31. Idempotency and Payload Identity

P8 SHALL preserve:

```text
IdempotencyKey
!= PayloadHash
```

Required behavior:

```text
same IdempotencyKey + same PayloadHash
→ same committed/known result

same IdempotencyKey + different PayloadHash
→ semantic conflict
→ no duplicate business mutation
```

The initial EOS canonical command APIs SHALL expose enough contract to enforce this deterministically.

---

## 32. First EOS Canonical WRITE

The first protected EOS write SHOULD be:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

Initial request semantics may include:

```text
BusinessOperationId
IdempotencyKey
PayloadHash
project_ref
account / line refs
amount / currency
evidence refs
requester_ref
source AgentExecution / WorkItem / NSL refs
expected_version where applicable
```

Initial result semantics:

```text
VoucherDraftRef
CommitState
version
business transaction ref
evidence / trace refs
```

Exact schema SHALL be defined only after EOS Source Audit.

---

## 33. UNKNOWN_COMMIT_STATE

P8 SHALL treat transport outcome and business commit outcome separately.

Forbidden:

```text
timeout
→ assume NOT_COMMITTED
→ automatic retry
```

Required:

```text
timeout / ambiguous provider result
→ UNKNOWN_COMMIT_STATE
→ RECONCILIATION_REQUIRED
→ authoritative EOS query
→ decision
```

Core invariant:

> **UNKNOWN_COMMIT_STATE never causes blind business WRITE retry.**

---

## 34. COMMITTED + Verification Failure

P8 SHALL preserve:

```text
CommitState = COMMITTED
VerificationStatus = FAILED or UNKNOWN
```

as a distinct condition.

It SHALL NOT be collapsed into:

```text
WRITE failed, retry WRITE
```

Required:

```text
business mutation remains committed
→ no duplicate WRITE
→ verification/reconciliation path
```

---

## 35. Recommended P8 Implementation Sequence

```text
P7 FROZEN
   ↓

P8.0
Pre-Architecture / Source / Contract Closure
   │
   ├─ Repository boundary
   ├─ Delegation Guard
   ├─ Organization ownership
   ├─ Approval domain mapping
   └─ identity / evidence contracts
   ↓

P8.1
NSL v0.2 Standalone Upgrade
(2608_nsl)
   │
   ├─ regression lock
   ├─ IR / Tool Contract WRITE
   ├─ compiler safety
   ├─ PreWriteEligibility
   ├─ checkpoint
   ├─ approval suspend/resume semantics
   ├─ WriteExecutionPort
   ├─ idempotency
   ├─ CommitState / VerificationStatus
   ├─ Signed NSP trust
   └─ replay safety
   │

P8.2
NeX-EOS Foundation
(2607_nex_platform)
   │
   ├─ service / DB
   ├─ minimal Organization
   ├─ Project / Account
   ├─ Voucher Draft
   ├─ Canonical API
   ├─ Outbox
   └─ audit / trace
   │

P8.3
Human Approval Foundation
   │
   ├─ EOS ApprovalPolicy / Instance / Stage
   ├─ WC ApprovalWorkItem
   ├─ IA HumanGate / Approval Inbox
   ├─ OA decision-time authorization
   └─ PART_LEAD → TEAM_LEAD → GROUP_LEAD → CEO → CHAIRMAN support
   │

P8.4
AE ↔ NSL v0.2 Admission / Suspend / Resume
   │
   ├─ NSL_V02_IN_PROCESS
   ├─ exact wheel admission
   ├─ NSL_APPROVAL WaitRegistration
   └─ same BusinessOperationId resume
   │

P8.5
Governed WRITE → EOS
   │
   ├─ WriteGuard
   ├─ GovernedWriteExecutionPort
   ├─ OA / trust binding
   └─ EOS Canonical Command
   │

P8.6
Golden A Voucher Draft
   │

P8.7
Dual Approval / Business Formal Approval
   │

P8.8
Reliability / Fault Closure
   ├─ duplicate RuntimeJob
   ├─ approval replay/hash mismatch
   ├─ package trust failure
   ├─ operation trust mismatch
   ├─ UNKNOWN_COMMIT_STATE
   └─ COMMITTED + Verification FAILED
   ↓

Repository Full Gate
```

Exact Slice numbering may be refined after P8 Source Audit.

---

## 36. Parallel Development Model

P8 intentionally develops two repositories in parallel.

```text
Track A — NSL
2608_nsl
→ standalone deterministic v0.2 Controlled WRITE acceptance
→ release artifact

Track B — Platform
2607_nex_platform
→ EOS
→ Approval workflow
→ IA interaction
→ AE/WC/OA integration

Integration Point
→ admitted NSL v0.2 wheel
→ P8.4+
```

The two tracks SHOULD remain independently testable before integration.

---

## 37. P8 Initial Non-Goals

The first P8 implementation SHALL NOT require:

```text
full ERP replacement
full ledger / P&L
full procurement workflow
accounting close
bulk WRITE
multiple NSL WRITE nodes per Skill
WRITE inside FOREACH
dynamic WRITE Tool selection
email-reply approval
mobile push
multi-host EOS HA
Kafka
arbitrary direct SQL write
arbitrary direct HTTP write
```

These may be introduced only through later source-backed slices.

---

## 38. Testing Strategy

### NSL repository

At minimum:

```text
v0.1 compatibility regression
WRITE compiler negative tests
Approval suspend/resume
Idempotency
CommitState
VerificationStatus
Replay no-live-WRITE
Signed NSP production WRITE trust
Voucher Draft mock vertical
```

Frozen target minimum:

```text
statement coverage >= 95%
branch coverage    >= 90%
```

If the actual repository policy is stricter, the stricter policy wins.

### Platform repository

Retain the established P7 quality discipline:

```text
refactor first
focused unit tests
PostgreSQL protected smoke where relevant
fault tests
regression
contract validation
Repository Full Gate
```

P8 Platform target should not lower the P7 effective thresholds:

```text
statement coverage >= 98%
branch coverage    >= 96%
```

---

## 39. Golden A Acceptance Shape

The first protected business WRITE should prove:

```text
actual AE PostgreSQL
actual WC PostgreSQL
actual OA PostgreSQL
actual EOS PostgreSQL
live generation provider
admitted NSL v0.2
real approval wait/resume
current approver authorization
idempotent EOS business write
commit evidence
post-write verification
zero duplicate business mutation
zero owned test residue
```

Canonical flow:

```text
Prompt
→ IA
→ Plan
→ LOCAL_SKILL
→ NSL READ / CHECK
→ WriteIntent
→ NSL Approval
→ ApprovalWorkItem
→ Human Approval
→ Resume
→ WriteGuard
→ WRITE_REQUESTED
→ EOS CREATE_VOUCHER_DRAFT
→ COMMITTED
→ Verification
→ AgentResult
```

---

## 40. Dual Approval Acceptance

After Golden A is stable, P8 SHALL separately validate the coexistence of different approval domains.

Candidate:

```text
Agent FORMAL_APPROVAL
+
NSL WRITE Approval
+
EOS business formal approval where domain policy requires it
```

The exact dependency graph SHALL be fixed during Source Audit.

No approval domain may silently satisfy another domain's required evidence.

---

## 41. Key P8 Invariants

```text
LLM Candidate != execution authority

DELEGATE_WORK
requires OA authority
AND WC delegation guard

Claim
= background Agent execution authority

NSL WRITE Approval
!= Agent FORMAL_APPROVAL

NSL WRITE Approval
!= EOS Formal Business Approval

EOS Organization
!= OA Principal identity

EOS approver routing
!= OA authorization decision

IA Approval Inbox
!= Approval SoR

BusinessOperationId
remains stable across wait/resume/reconciliation

IdempotencyKey
!= PayloadHash

UNKNOWN_COMMIT_STATE
→ no blind retry

COMMITTED + Verification FAILED
→ no WRITE retry

NSL source repository
!= Platform source repository

Separate repository
!= mandatory separate runtime process
```

---

## 42. Source Audit Questions That Must Be Closed Next

### Repository / NSL

```text
1. Exact current 2608_nsl branch/tag/commit baseline?
2. Exact v0.1 package structure and extension hotspots?
3. Current wheel/version/admission mechanism?
4. Which Frozen v0.2 features are already partially implemented?
```

### Delegation Guard

```text
5. Best persisted representation for root/depth/budget?
6. Can current WorkItem parent lineage support efficient cycle detection?
7. Where should root descendant count be enforced atomically?
8. Which existing error/result semantics should represent delegation guard denial?
```

### Organization

```text
9. Does any current service already own OrgUnit/manager hierarchy?
10. How should EOS OrgUnit refs integrate with OA RoleBinding scopes?
11. How should effective-dated PositionAssignment be modeled?
12. What is the minimum Organization model for Golden A?
```

### Approval

```text
13. Exact mapping of Frozen ApprovalWorkItem domains to EOS BusinessApprovalAdapter?
14. Does formal EOS business approval require a new WC projection or only adapter linkage?
15. How is HumanGateView exposed to IA?
16. Which service owns Approval notification projection?
17. What exact event satisfies an NSL_APPROVAL WaitRegistration?
18. How is final multi-stage approval proof bound to NSL ApprovalEvidence?
```

### EOS

```text
19. Minimal Project / Account / Voucher schema?
20. Canonical create-voucher-draft command contract?
21. Idempotency storage model?
22. Commit confirmation semantics?
23. Reconciliation query?
24. Transactional outbox/event contract?
```

---

## 43. Required P8 Document Sequence

After this document is approved:

```text
P8 Pre-Architecture Decision
        ↓
P8 Source Audit
        ↓
P8 SRS
        ↓
P8 Implementation Slice Plan
        ↓
Implementation
```

The SRS SHALL not be finalized before the Source Audit resolves the open source-backed questions above.

---

## 44. Recommended Branch Strategy

P7 shall remain a stable reference baseline.

Recommended Platform branch:

```text
transition/p8-controlled-write
```

Recommended NSL branch:

```text
transition/v0.2-controlled-write
```

Exact branch names may follow repository conventions.

Each repository SHALL:

```text
commit small slices
run regression before sync
pin cross-repository dependency by immutable revision/hash
avoid floating integration references
```

---

## 45. P8 Entry Criteria

P8 implementation should begin only when the following Pre-Architecture decisions are accepted:

```text
[ ] NSL remains independent repository
[ ] EOS enters Platform monorepo as new service
[ ] EOS initial scope is Golden-A-minimal, not full ERP
[ ] WC owns Delegation Guard
[ ] Delegation hop-limit semantics accepted
[ ] Cycle detection required
[ ] Fan-out budget required
[ ] EOS owns business organization
[ ] OA owns identity / authorization
[ ] PART_LEAD → TEAM_LEAD → GROUP_LEAD → CEO → CHAIRMAN ladder accepted
[ ] IA is initial Human Approval interface
[ ] Approval domains remain distinct
[ ] multi-stage corporate approval is not repeated NSL approve statements
[ ] P7 Wait/Resume is reused
[ ] BusinessOperationId stability is preserved
[ ] no blind retry after UNKNOWN_COMMIT_STATE
[ ] Golden A is first business WRITE acceptance
```

---

## 46. Final Pre-Architecture Position

The P8 architecture is intentionally split into three planes:

```text
┌─────────────────────────────────────────────────────────┐
│ Agent / Human Control Plane                             │
│                                                         │
│ AE / WC / OA / IA                                       │
│ Planning / Work / Approval interaction / Resume         │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│ Deterministic Skill Execution Plane                     │
│                                                         │
│ NSL v0.2                                                 │
│ READ / CHECK / Approval Binding / WRITE Safety          │
│ Idempotency / Commit / Verification                     │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│ Authoritative Business Plane                            │
│                                                         │
│ Enterprise OS                                            │
│ Organization / Project / Account / Voucher / Approval   │
│ Canonical Business State                                │
└─────────────────────────────────────────────────────────┘
```

The central P8 rule is:

> **Agent intelligence may propose and coordinate work; NSL deterministically controls side-effect execution; Enterprise OS owns the resulting authoritative business state.**

For human approval:

> **One user-facing approval experience may unify interaction, but identity, work coordination, deterministic WRITE approval, and formal business approval remain separate authoritative domains.**

For recursive delegation:

> **Delegation is powerful but bounded: current authorization, hop depth, cycle detection, and fan-out budget must all permit a child WorkItem before another Agent execution can be created.**
