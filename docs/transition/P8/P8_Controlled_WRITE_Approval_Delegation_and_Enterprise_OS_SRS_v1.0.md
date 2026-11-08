# P8 — Controlled WRITE / Approval / Delegation / Enterprise OS
# Software Requirements Specification v1.0

**Document Status:** PRE-IMPLEMENTATION SRS  
**Phase:** P8  
**Predecessor:** P7 CLOSED / P8 Pre-Architecture + Source Audit + CA01 + CA01A  
**Platform Repository:** `nurigitdev/2607_nex_platform`  
**Platform Entry Baseline Commit:** `ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a`  
**Platform Entry Baseline Tree:** `c0901e9e2af266b400adc07dddd815c77fae2ae1`  
**NSL Repository:** `nurigitdev/2608_nsl`  
**NSL v0.2 Certified Source Commit:** `5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6`  
**NSL v0.2 Certified Source Tree:** `71dbea8cca563867b12acd07462a2dcd42d9a8ac`  
**Quality Baseline:** Platform Statement ≥ 96%, Branch ≥ 94%; NSL native gate remains Statement ≥ 99%, Branch ≥ 98%  
**EOS Development DB:** `nex_eos_dev`  
**EOS Test DB:** `nex_eos_test`  
**Date:** 2026-10-21

---

## 1. Purpose

P8 connects the already-certified NSL v0.2 deterministic Controlled WRITE
runtime to NeX Platform human approval, bounded Agent delegation, and a new
Enterprise OS authoritative business transaction service.

The P8 target is:

```text
Natural-language Prompt
→ Intent / Context / Plan Candidate
→ deterministic validation / compile
→ LOCAL_SKILL
→ admitted NSL v0.2
→ READ / CHECK
→ PreWriteEligibility
→ WriteIntent
→ ApprovalRequest
→ durable checkpoint / wait
→ Human Approval
→ RESUME_EXECUTION
→ ApprovalEvidence validation
→ WriteGuard
→ NSL Idempotency
→ durable WRITE_REQUESTED
→ Enterprise OS Canonical Command
→ CommitState
→ Post-Write Verification
→ AgentResult
```

P8 SHALL preserve the central NeX invariant:

> **LLM output is never execution authority. Authoritative business mutation occurs only after every required deterministic trust, authorization, approval, idempotency, and domain control passes.**

---

## 2. Entry Gate

P8 implementation SHALL begin from the following accepted design baseline:

```text
P8 Pre-Architecture Decision
→ P8 Source Audit
→ P8-CA01 Contract Closure
→ P8-CA01A NVT / Voucher Attachment Amendment
→ P8 SRS
```

P8 SHALL preserve P7 behavior unless an explicit P8 versioned extension says
otherwise.

Before activating NSL v0.2 WRITE in Platform, the actual released wheel SHALL
pass P8 Release Admission.

---

## 3. Source-of-Truth Order

P8 implementation SHALL follow:

```text
Integrated Frozen Platform v2.1 / Agent v2.1 / NSL v0.2
> Frozen machine-readable contracts
> Certified NSL v0.2 As-Built source
> P7 Final As-Built / CA02B baseline
> P8 Pre-Architecture Decision
> P8 Source Audit
> P8-CA01 / CA01A
> this SRS
> implementation slice plan
> implementation convenience
```

Frozen files SHALL NOT be modified to fit implementation convenience.

---

## 4. Scope

P8 includes:

```text
NSL v0.2 wheel admission
NSL_V02 runtime profile
AE ↔ NSL v0.2 Controlled WRITE integration

NSL Approval publication
durable approval wait/resume
ApprovalEvidence bridge
WC ApprovalWorkItem runtime
IA HumanGate / Approval Inbox
fresh OA approval authorization

WC Delegation Guard
delegation depth
fan-out budget
root descendant budget
cycle detection
nested delegation Claim authority

NeX-EOS service foundation
nex_eos_dev / nex_eos_test
minimal Organization
NVTProject
Project hierarchy
minimal Account
VoucherDraft
Voucher attachments metadata / RustFS refs
EOS business idempotency
transactional outbox
reconciliation
verification read

Golden A Voucher Draft E2E
Formal Business Approval foundation
fault / reliability closure
```

---

## 5. Out of Scope

The initial P8 baseline does not require:

```text
full ERP replacement
full General Ledger
Project P/L implementation
Procurement lifecycle
Fiscal close
NVT token issuance/accounting
NVT token consumption/valuation
NVT incentive calculation
bulk NSL WRITE
multiple WRITE nodes per Skill
WRITE inside FOREACH
arbitrary SQL/HTTP WRITE
email-reply approval
mobile approval
complete ActingAuthority implementation
Kafka
EOS microservice decomposition
full document-management lifecycle
legal hold / document notarization
```

These require later controlled design.

---

# 6. Service Ownership

## 6.1 NeX-AE

AE SHALL own:

```text
AgentIdentity
AgentExecution
Planning / Validation / Compiler
RuntimeJob / Worker
NSLStepExecutionBinding
NSL integration adapters
NSL checkpoint integration persistence
WaitRegistration
External Event Inbox
RESUME_EXECUTION
AgentResult / ResultDelivery
HumanGate projection integration
```

AE SHALL NOT own business transaction state.

---

## 6.2 NeX-WC

WC SHALL own:

```text
WorkItem
Delegation lineage
Delegation Guard
RoutingDecision
Assignment
Claim / ClaimGeneration
WorkResult
ApprovalWorkItem
ApprovalDecision human-task records
Work / Approval outbox
```

WC SHALL NOT validate NSL WriteIntent semantics.

---

## 6.3 NeX-OA

OA SHALL remain authoritative for:

```text
Principal
Authentication
RoleBinding
Tenant
security scope
Effective Authority
current authorization decision
service trust
```

OA SHALL NOT become Organization hierarchy SoR.

---

## 6.4 NSL v0.2

NSL SHALL own:

```text
deterministic Skill execution
IR / compiler semantics
PreWriteEligibility
ApprovalRequest semantics
WriteIntent
PayloadHash / WriteIntentHash
ApprovalEvidence semantic validation
IdempotencyKey derivation
WriteGuard
WRITE_REQUESTED ordering
CommitState interpretation
VerificationStatus
Replay safety
Signed NSP / package trust semantics
```

NSL remains in its independent repository.

---

## 6.5 NeX-EOS

EOS SHALL own:

```text
Business Organization
NVTProject
Project
Account
VoucherDraft
business operation state
business idempotency acceptance
Formal Business Approval
authoritative business transaction state
business transactional outbox
business reconciliation state
```

EOS SHALL NOT own Employee identity or OA RoleBinding.

---

## 6.6 IA / AE-WEB

IA SHALL provide:

```text
Approval Inbox
HumanGateView
approval detail
Approve / Reject interaction
```

IA is not an Approval SoR.

---

# 7. Version and Release Model

## P8-REL-FR-001 — Immutable NSL v0.2 Admission

Platform SHALL admit NSL v0.2 only from an immutable wheel release identity.

Required evidence:

```text
repository
source_revision
source_tree
distribution
package_version
wheel_filename
wheel_sha256
requires_python
dependency requirements
public API inventory
Platform dependency-lock hash
certification reference
```

---

## P8-REL-FR-002 — v0.2 Package Version

The admitted WRITE-capable wheel SHALL identify an explicitly approved v0.2
package version.

A wheel that still identifies itself as `0.1.0` SHALL fail P8 v0.2 admission.

---

## P8-REL-FR-003 — Existing Admission Reuse

P8 SHALL reuse and extend the existing:

```text
services/_shared/nex_runtime/nsl_package_admission.py
```

mechanism.

No second wheel-admission framework is permitted.

---

## P8-REL-FR-004 — Runtime Profiles

P8 SHALL retain:

```text
NSL_V01_IN_PROCESS
NSL_V01_PROCESS_ISOLATED
```

and add:

```text
NSL_V02_IN_PROCESS
```

`NSL_V02_PROCESS_ISOLATED` MAY be added only if an implementation slice
requires it.

---

## P8-REL-FR-005 — No WRITE Fallback

An NSL 0.2 / IR 1.1 WRITE Skill SHALL never fall back to a v0.1 runtime
profile.

---

## P8-REL-FR-006 — Public API Boundary

Platform SHALL integrate through stable `nsl.api` public symbols.

Platform SHALL NOT depend on arbitrary NSL private implementation internals.

---

# 8. Identity Contract

The following are distinct identities:

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
RuntimeJobId

NSLExecutionId
BusinessOperationId
ApprovalRequestId
ApprovalWorkItemId
WaitId

WorkItemId
ClaimId
ClaimGeneration

WriteNodeId
IdempotencyKey
PayloadHash
WriteIntentHash

EOS BusinessOperationRef
VoucherRef
BusinessTransactionRef
```

No identity SHALL be reused merely because values happen to be correlated.

---

## P8-ID-FR-001 — NSL Execution Mapping

Platform:

```text
nsl_execution_id
```

SHALL map exactly to NSL public:

```text
execution_id
```

for one NSL execution.

No second NSL runtime identity shall be created.

---

## P8-ID-FR-002 — Stable BusinessOperationId

Platform SHALL allocate/persist `BusinessOperationId` before NSL Controlled
WRITE processing.

The same value SHALL survive:

```text
approval suspension
resume
worker restart
RuntimeJob retry
provider response loss
reconciliation
verification recovery
```

---

## P8-ID-FR-003 — Retry Identity Preservation

Technical retry SHALL preserve:

```text
NSLExecutionId
BusinessOperationId
ApprovalRequestId when already created
WriteNodeId
```

where the semantic operation has not changed.

---

## P8-ID-FR-004 — Semantic Change

A semantic change that produces a different business operation SHALL not reuse
a prior `BusinessOperationId`.

A material payload change after approval SHALL require new approval semantics.

---

# 9. NSL v0.2 Controlled Execution Integration

## P8-NSL-FR-001 — Controlled Prefix

AE SHALL invoke the admitted NSL v0.2 Controlled WRITE execution path.

It SHALL preserve:

```text
READ
CHECK
PreWriteEligibility
checkpoint
Approval
resume
WriteGuard
WRITE
commit
verification
```

ordering defined by NSL.

---

## P8-NSL-FR-002 — No Platform Reimplementation

Platform SHALL NOT duplicate:

```text
WriteIntentBuilder
IdempotencyKeyFactory
ApprovalEvidenceValidator
WriteGuard
CommitState algebra
PostWriteVerifier
```

for the purpose of replacing NSL semantics.

---

## P8-NSL-FR-003 — NSLStepExecutionBinding Reuse

Existing AE durable `NSLStepExecutionBinding` SHALL be extended rather than
replaced.

It SHALL retain:

```text
agent_execution_id
executable_step_id
nsl_execution_id
business_operation_id
verified artifact lineage
backend profile
state
```

---

## P8-NSL-FR-004 — v0.2 Binding

A WRITE-capable binding SHALL additionally preserve enough references to
correlate:

```text
checkpoint
approval request
approval evidence
write evidence
commit outcome
verification outcome
```

without copying NSL-internal journal state into unrelated AE tables.

---

## P8-NSL-FR-005 — Production Port Adapters

P8 SHALL provide durable Platform adapters for the NSL public ports required by
the admitted Controlled WRITE flow.

At minimum:

```text
CheckpointPort
ResumeCheckpointPort
ApprovalPort
ApprovalEvidenceVerifier
IdempotencyEvidencePort
RuntimePolicyPort
WriteEvidencePort
WriteOutcomeEvidencePort
WriteExecutionPort
PostWriteVerificationPort
```

Where a port delegates to EOS, the Platform adapter SHALL preserve the EOS
authoritative business boundary.

---

## P8-NSL-FR-006 — Checkpoint Durability

An approval suspension SHALL not be published until the NSL checkpoint is
durably stored.

---

## P8-NSL-FR-007 — Protected Checkpoint

Persisted NSL checkpoint content SHALL be protected according to the highest
data classification carried by the execution.

It SHALL NOT contain raw credentials.

---

## P8-NSL-FR-008 — Resume Claim

NSL checkpoint resume SHALL use exclusive claim/consume semantics so that a
duplicate resume cannot perform the WRITE twice.

---

# 10. NSL Approval Publication

## P8-APR-FR-001 — Exact ApprovalRequest Preservation

Platform SHALL persist the exact canonical NSL `ApprovalRequest` as protected
evidence before or as part of approval publication.

Required references:

```text
protected_request_ref
approval_request_hash
```

---

## P8-APR-FR-002 — Safe Workflow Projection

WC/IA SHALL receive only metadata-safe fields needed for human workflow.

Raw protected business payload SHALL not be copied into generic WorkItem,
notification, or RuntimeJob payloads.

---

## P8-APR-FR-003 — Approval Envelope

The P8 approval publication envelope SHALL preserve:

```text
tenant_id
agent_execution_id
executable_step_id
nsl_execution_id
business_operation_id

approval_id
approval_request_id

skill_id
skill_version
skill_semantic_hash

write_node_id
tool_id
payload_hash
write_intent_hash
checkpoint_version

risk_level
data_classification
display_safe_summary
expires_at

protected_request_ref
approval_request_hash
correlation_id
causation_id
```

---

## P8-APR-FR-004 — Approval Request Idempotency

Same `ApprovalRequestId` + same semantic envelope SHALL resolve to the same
approval workflow identity.

Same `ApprovalRequestId` + different semantic envelope SHALL fail closed.

---

## P8-APR-FR-005 — Publication Ordering

Required order:

```text
NSL checkpoint persisted
→ AE NSL_APPROVAL WaitRegistration committed
→ WC ApprovalWorkItem create/get
→ human task becomes visible
```

A human-decisionable ApprovalWorkItem SHALL NOT exist without a durable resume
target.

---

## P8-APR-FR-006 — Publication Retry

If WC creation fails after AE wait commit:

```text
NSL remains WAITING_FOR_APPROVAL
WaitRegistration remains PENDING
same ApprovalRequestId is retried
```

If WC creation committed but ACK is lost, retry SHALL not create a duplicate
ApprovalWorkItem.

---

# 11. AE Wait / Resume

## P8-WAIT-FR-001 — Wait Types

AE SHALL support:

```text
WORK_RESULT
NSL_APPROVAL
```

as distinct `wait_type` values.

---

## P8-WAIT-FR-002 — No Fake WorkResult

An NSL approval decision SHALL NOT be represented as a fake WorkResult.

---

## P8-WAIT-FR-003 — WaitRegistration

For `NSL_APPROVAL`:

```text
external_ref = ApprovalRequestId
```

and the wait SHALL bind the exact:

```text
AgentExecutionId
ExecutableStepId
NSLExecutionId
BusinessOperationId
checkpoint_version
```

through direct fields or immutable references.

---

## P8-WAIT-FR-004 — External Ref Type

AE wait persistence SHALL support string-based external identities and SHALL
not require all external references to be UUIDs.

Migration SHALL remain compatible with historical P7 WorkResult waits.

---

## P8-WAIT-FR-005 — Wait State

Retain:

```text
PENDING
SATISFIED
RESUME_QUEUED
CONSUMED
CANCELLED
```

Unsupported transitions SHALL fail deterministically.

---

## P8-WAIT-FR-006 — Typed Approval Event

WC SHALL emit:

```text
NSL_APPROVAL_DECIDED
```

with bounded metadata/reference payload.

---

## P8-WAIT-FR-007 — Event Deduplication

Same approval event ID SHALL be consumed idempotently.

One wait SHALL create at most one semantic `RESUME_EXECUTION` RuntimeJob.

---

## P8-WAIT-FR-008 — Resume Job Payload

NSL approval resume payload SHALL contain only bounded refs:

```text
wait_id
event_id
approval_request_id
approval_work_item_ref
approval_evidence_ref
resume_token_ref
```

---

## P8-WAIT-FR-009 — Resume Source Adapter

AE SHALL provide a typed `NSLApprovalResumeSource` or equivalent sibling of the
existing WorkResult resume adapter.

It SHALL validate exact event/wait/job lineage before exposing resume data to
NSL.

---

## P8-WAIT-FR-010 — Resume Identity Preservation

Resume SHALL reuse:

```text
same NSLExecutionId
same BusinessOperationId
same checkpoint_version target
same ApprovalRequestId
```

---

# 12. Approval Evidence

## P8-EVD-FR-001 — Immutable Platform Evidence

Platform SHALL persist immutable approval evidence containing at minimum:

```text
tenant_id
agent_execution_id
executable_step_id
nsl_execution_id
business_operation_id

approval_id
approval_request_id
skill_semantic_hash

decision
approver_id
decided_at
expires_at

payload_hash
write_intent_hash

approval_work_item_ref
oa_decision_ref
protected_request_ref
evidence_integrity
```

---

## P8-EVD-FR-002 — Evidence Integrity

`evidence_integrity` SHALL be a deterministic integrity reference over the
canonical immutable evidence record.

---

## P8-EVD-FR-003 — NSL Projection

AE SHALL project Platform evidence to NSL `ApprovalEvidence`.

Mapping:

```text
Platform nsl_execution_id → NSL execution_id
APPROVE                    → APPROVED
REJECT                     → REJECTED
```

---

## P8-EVD-FR-004 — No Binding Override

Platform SHALL NOT alter:

```text
BusinessOperationId
ApprovalRequestId
PayloadHash
WriteIntentHash
skill_semantic_hash
```

when constructing the NSL projection.

---

## P8-EVD-FR-005 — ApprovalEvidenceVerifier

P8 SHALL provide an `ApprovalEvidenceVerifier`.

It SHALL validate provenance/authority of the Platform evidence.

NSL SHALL separately validate semantic bindings.

---

# 13. WC ApprovalWorkItem Runtime

## P8-WCA-FR-001 — ApprovalWorkItem SoR

WC SHALL persist approval human-task state.

---

## P8-WCA-FR-002 — Approval Domains

P8 active domains SHALL include:

```text
AGENT_FORMAL
NSL_WRITE
BUSINESS_FORMAL
```

Historical Frozen contracts remain immutable; P8 SHALL use an additive
transition contract.

---

## P8-WCA-FR-003 — ApprovalWorkItem State

Required states:

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

---

## P8-WCA-FR-004 — Decision Values

Human decision values:

```text
APPROVE
REJECT
```

---

## P8-WCA-FR-005 — Idempotent Create/Get

Approval WorkItem creation SHALL be `create_or_get` by stable semantic
identity.

For NSL WRITE:

```text
source_ref = ApprovalRequestId
```

---

## P8-WCA-FR-006 — Immutable Decision History

Decision history SHALL be append-only.

A prior terminal decision SHALL not be overwritten by a conflicting later
decision.

---

## P8-WCA-FR-007 — Duplicate Same Decision

Exact same terminal decision replay MAY return idempotent success.

---

## P8-WCA-FR-008 — Conflicting Decision

`APPROVED → REJECTED` or equivalent immutable binding conflict SHALL return a
deterministic conflict and preserve the original decision.

---

# 14. Approval Authorization

## P8-AUTH-FR-001 — Approval Read Scope

Reading actionable Approval Inbox items SHALL require current:

```text
approval:read
```

or a more specific future scope.

---

## P8-AUTH-FR-002 — Approval Decision Scope

Submitting APPROVE/REJECT SHALL require fresh OA authorization containing:

```text
approval:decide
```

---

## P8-AUTH-FR-003 — Decision-Time Check

The authorization check SHALL occur immediately before decision commit.

Planning-time or inbox-read authorization SHALL not substitute.

---

## P8-AUTH-FR-004 — Target Compatibility

WC SHALL verify that the authorized principal matches the exact:

```text
target_approver_ref
or
authorized target role/org/project scope
```

resolved for the ApprovalWorkItem.

---

## P8-AUTH-FR-005 — Authorization Failure

Inactive principal, missing scope, target mismatch, malformed OA response, or OA
dependency failure SHALL result in:

```text
zero approval decision mutation
```

---

## P8-AUTH-FR-006 — Authority Evidence

A committed decision SHALL retain:

```text
decided_by
oa_decision_ref
authorization revision/hash where available
authorization_checked_at
```

No raw token shall be stored.

---

# 15. IA Human Approval

## P8-IA-FR-001 — Unified Approval Inbox

IA SHALL provide one bounded approval inbox for eligible users.

---

## P8-IA-FR-002 — Domain Preservation

Each HumanGate SHALL preserve exact domain:

```text
AGENT_FORMAL
NSL_WRITE
BUSINESS_FORMAL
HUMAN_CONFIRMATION
STEP_UP
```

A unified UI SHALL not imply semantic equivalence.

---

## P8-IA-FR-003 — Safe Fields

HumanGate SHALL contain metadata-safe fields:

```text
gate_id
approval_domain
state
title
summary
action_ref
expires_at
approval_provider_type
approval_target_ref
business_operation_id where permitted
```

---

## P8-IA-FR-004 — Protected Detail

Sensitive payload/detail SHALL be loaded only through authenticated,
authorization-checked detail access.

---

## P8-IA-FR-005 — Initial Delivery Channel

Initial P8 requires IA/AE-WEB approval interaction.

Email/push is not required for Golden A.

---

# 16. Formal Business Approval

## P8-BFA-FR-001 — EOS SoR

EOS SHALL own:

```text
ApprovalPolicy
ApprovalInstance
ApprovalStage
ApprovalDecision
ApprovalProof
```

for formal business approval.

---

## P8-BFA-FR-002 — WC Human Task Projection

An active EOS ApprovalStage MAY create a WC:

```text
approval_domain = BUSINESS_FORMAL
```

ApprovalWorkItem.

WC remains human-task SoR; EOS remains business-approval SoR.

---

## P8-BFA-FR-003 — Multi-Stage Approval

Formal business approval SHALL support ordered multi-stage processing.

Canonical leadership ladder:

```text
PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
```

Policy may use only a subset.

---

## P8-BFA-FR-004 — No Repeated NSL Approve

Corporate stages SHALL NOT be implemented as repeated NSL `approve`
statements.

---

## P8-BFA-FR-005 — Domain Independence

```text
NSL_WRITE
!= BUSINESS_FORMAL
!= AGENT_FORMAL
```

Evidence from one domain SHALL not automatically satisfy another.

---

## P8-BFA-FR-006 — Golden A Scope

Initial `FINANCE.CREATE_VOUCHER_DRAFT` Golden A SHALL require NSL WRITE
Approval.

BUSINESS_FORMAL approval is not mandatory for Draft creation unless an explicit
EOS policy enables it.

---

# 17. Delegation Guard

## P8-DG-FR-001 — WC Ownership

WC SHALL enforce deterministic Delegation Guard policy.

---

## P8-DG-FR-002 — Initial Policy

Initial policy:

```text
max_delegation_depth       = 10
max_children_per_work_item = 5
max_descendants_per_root   = 50
cycle_detection            = ENABLED
```

Values SHALL be governance-controlled and SHALL NOT be LLM-overridable.

---

## P8-DG-FR-003 — Depth Definition

First Agent-created delegated WorkItem:

```text
delegation_depth = 1
```

Nested delegated WorkItem:

```text
child depth = parent depth + 1
```

Claim does not increment depth.

---

## P8-DG-FR-004 — Hop Limit

If prospective child depth exceeds policy:

```text
no child WorkItem
```

The current WorkItem remains executable.

---

## P8-DG-FR-005 — Root Identity

Every delegated lineage SHALL have stable:

```text
root_work_item_id
```

that never changes.

---

## P8-DG-FR-006 — Parent Identity

Nested delegation SHALL persist:

```text
parent_work_item_id
parent_claim_ref
parent_claim_generation
delegating_agent_ref
parent_agent_execution_id
```

---

## P8-DG-FR-007 — Current Parent Claim

Nested delegation SHALL require a current ACTIVE parent Claim with matching
generation, assignment, claimant, and lease.

Stale/expired authority SHALL create zero child WorkItems.

---

## P8-DG-FR-008 — Child Budget

Direct delegated child count SHALL not exceed:

```text
max_children_per_work_item
```

---

## P8-DG-FR-009 — Root Descendant Budget

Total descendants below one delegation root SHALL not exceed:

```text
max_descendants_per_root
```

---

## P8-DG-FR-010 — Atomic Budget Enforcement

Concurrent child creation SHALL not oversubscribe child/root budgets.

Budget checks and child admission SHALL use one transactionally protected
boundary.

---

## P8-DG-FR-011 — Cycle Check Timing

Because actual claimant is known at Claim time, Agent cycle detection SHALL be
rechecked immediately before Claim commit.

---

## P8-DG-FR-012 — Cycle Rule

A candidate Agent is ineligible when:

```text
candidate_agent_ref ∈ ancestor delegating_agent_refs
```

within the same root lineage.

---

## P8-DG-FR-013 — No Authority on Cycle

A cyclic candidate SHALL create:

```text
zero Claim
zero Assignment
zero child AgentExecution
```

---

## P8-DG-FR-014 — Current OA Delegation Authority

Every new child delegation, including idempotent replay, SHALL retain current
OA `work:delegate` authorization requirements.

---

# 18. NeX-EOS Service Foundation

## P8-EOS-FR-001 — New Service

Platform SHALL introduce:

```text
services/nex-eos/
database/nex-eos/
contracts/openapi/nex-eos.openapi.yaml
```

or repository-equivalent locations.

---

## P8-EOS-FR-002 — Database Names

Development:

```text
nex_eos_dev
```

Test:

```text
nex_eos_test
```

---

## P8-EOS-FR-003 — DB Ownership

Only NeX-EOS SHALL mutate EOS-owned tables.

Other services SHALL use authenticated EOS APIs.

---

## P8-EOS-FR-004 — Modular Monolith

Initial EOS SHALL be one service with explicit bounded contexts.

Logical contexts:

```text
organization
project
account
approval
finance/voucher
common
api
persistence
```

---

## P8-EOS-FR-005 — Operational Endpoints

EOS SHALL expose authenticated/operational:

```text
health
readiness
version/build identity
```

consistent with Platform service conventions.

---

## P8-EOS-FR-006 — Service Trust

Internal EOS calls SHALL require existing service-trust controls.

Business authorization is additional to service trust.

---

## P8-EOS-FR-007 — No LLM Dependency

EOS business-domain mutation logic SHALL have no direct LLM dependency.

---

# 19. EOS Organization

## P8-ORG-FR-001 — Organization SoR

EOS SHALL own business organization structure.

---

## P8-ORG-FR-002 — OA Principal Reference

Organization membership/position assignment SHALL reference stable OA
Principal refs.

EOS SHALL not copy credentials or authentication state.

---

## P8-ORG-FR-003 — OrgUnit

Initial OrgUnit SHALL support:

```text
org_unit_id
org_unit_code
name
org_unit_type
parent_org_unit_ref
status
effective period
version
```

---

## P8-ORG-FR-004 — OrgUnit Types

Initial types SHALL support at least:

```text
PART
TEAM
GROUP
COMPANY
```

---

## P8-ORG-FR-005 — Position

Initial Position SHALL support:

```text
PART_LEAD
TEAM_LEAD
GROUP_LEAD
CEO
CHAIRMAN
```

---

## P8-ORG-FR-006 — PositionAssignment

EOS SHALL support effective-dated assignment from Position to OA Principal.

---

## P8-ORG-FR-007 — Approver Resolution

EOS SHALL provide deterministic approver resolution from:

```text
requester
organization
policy
risk
project
approval domain
```

to a stable Principal/Position target.

---

## P8-ORG-FR-008 — No Self-Approval Default

Default approval policy SHALL not select requester as approver.

Any exception requires explicit policy.

---

## P8-ORG-FR-009 — Authority Separation

EOS resolution determines intended business approver.

OA determines whether the resolved principal currently has authority.

---

# 20. NVTProject / Project Hierarchy

## P8-PROJ-FR-001 — Separate NVTProject

EOS SHALL persist `NVTProject` as a separate business object/table from
ordinary `Project`.

---

## P8-PROJ-FR-002 — NVTProject Initial Fields

Initial model SHALL include at least:

```text
nvt_project_id
nvt_project_code
name
status
version
created_at
updated_at
```

---

## P8-PROJ-FR-003 — Mother Project

An ordinary Project with:

```text
parent_project_id = NULL
```

is a Mother Project.

A Mother Project SHALL have:

```text
nvt_project_id != NULL
```

---

## P8-PROJ-FR-004 — Child Project

A non-Mother Project SHALL have:

```text
parent_project_id != NULL
```

and SHOULD not persist a redundant direct `nvt_project_id`.

Its NVT relationship is derived through its Mother ancestor.

---

## P8-PROJ-FR-005 — Maximum Project Depth

Ordinary Project hierarchy SHALL support maximum depth:

```text
3
```

NVTProject does not count as one of those three levels.

---

## P8-PROJ-FR-006 — Project Cycle

A Project SHALL not be its own ancestor.

Any hierarchy cycle SHALL be rejected.

---

## P8-PROJ-FR-007 — Same NVT Lineage

All descendants of one Mother Project SHALL resolve to that Mother's
NVTProject.

---

## P8-PROJ-FR-008 — NVT Aggregation

EOS SHALL support query/aggregation of:

```text
NVTProject
→ Mother Projects
→ all descendant Projects
```

---

## P8-PROJ-FR-009 — Stable Project Identity

Business transactions SHALL use stable `ProjectRef`, not display name.

---

## P8-PROJ-FR-010 — NVT Scope

P8 SHALL NOT require NVT token budget/allocation/consumption/incentive
semantics.

---

# 21. Account Minimum Model

## P8-ACC-FR-001 — Stable Account

EOS SHALL support immutable `account_id` distinct from mutable/display
`account_code`/name semantics.

---

## P8-ACC-FR-002 — Active Account

Voucher Draft creation SHALL reject inactive or expired Account refs.

---

## P8-ACC-FR-003 — Candidate vs Canonical

LLM/user search may suggest Account candidates.

Only canonical resolved stable Account IDs may reach EOS WRITE.

---

# 22. VoucherDraft

## P8-VCH-FR-001 — Draft Business Object

EOS SHALL model `VoucherDraft` as the initial financial/business draft used for
later enterprise approval.

It is not merely a UI form row.

---

## P8-VCH-FR-002 — Initial State

New Voucher Draft state:

```text
DRAFT
```

Later lifecycle transitions may include:

```text
SUBMITTED
APPROVAL_PENDING
APPROVED
REJECTED
POSTED
REVERSED
```

but P8 Golden A needs only Draft creation.

---

## P8-VCH-FR-003 — Required Business Data

Initial Voucher Draft SHALL contain at minimum:

```text
voucher_id
ProjectRef
currency
transaction_date
description
requester/source refs
one or more lines
state
version
created_at
updated_at
```

---

## P8-VCH-FR-004 — Voucher Lines

Each line SHALL support:

```text
line_no
AccountRef
signed_amount or equivalent debit/credit model
economic category
evidence refs
```

---

## P8-VCH-FR-005 — Decimal Money

Financial values SHALL use decimal-safe Money semantics.

Binary floating point SHALL NOT be used for authoritative financial amount
identity.

---

## P8-VCH-FR-006 — Balance Invariant

For the initial general accounting Voucher profile:

```text
sum(signed_amount) == 0
```

unless an explicit transaction type defines an equivalent deterministic balance
rule.

---

## P8-VCH-FR-007 — Stable Project / Account Refs

Voucher creation SHALL reject unresolved/ambiguous display-name-only business
references.

---

# 23. Voucher Attachments / RustFS Boundary

## P8-ATT-FR-001 — Zero or More Attachments

Voucher Draft SHALL support zero or more attachment references.

Attachments are optional for first Golden A.

---

## P8-ATT-FR-002 — Binary Separation

Attachment binary data SHALL NOT be stored directly in the Voucher relational
row.

---

## P8-ATT-FR-003 — Existing RustFS

When binary attachment storage is activated in P8, the existing RustFS object
storage SHALL be reused rather than introducing a new object-storage product.

---

## P8-ATT-FR-004 — Attachment Metadata

EOS SHALL persist stable business metadata such as:

```text
attachment_id
voucher_id
object_ref
display_name
media_type
size_bytes
content_sha256 where available
evidence_ref
created_at
```

---

## P8-ATT-FR-005 — Stable Object Reference

`object_ref` SHALL be a stable opaque reference.

It SHALL NOT be:

```text
access key
secret key
session credential
presigned URL
local filesystem path
```

---

## P8-ATT-FR-006 — Tenant Isolation

Attachment refs SHALL be validated for tenant ownership before association with
a Voucher.

---

## P8-ATT-FR-007 — Future Approval Invalidation

The data model SHALL permit future policy where a material attachment change
invalidates prior business approval.

P8 Golden A does not require a complete attachment-manifest hash policy.

---

# 24. Canonical Golden A WRITE

## P8-WRITE-FR-001 — Operation

Initial authoritative business command:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

---

## P8-WRITE-FR-002 — CREATE Only

Golden A creates a Draft.

It SHALL NOT implicitly:

```text
POST ledger
finalize accounting
close period
calculate P/L
```

---

## P8-WRITE-FR-003 — Command Inputs

Canonical command SHALL bind at least:

```text
tenant_id
business_operation_id
idempotency_key
payload_hash

requester_ref
project_ref
voucher_type
transaction_date
currency
description
lines

attachment/evidence refs where supplied

nsl_approval_request_id
nsl_approval_evidence_ref

correlation lineage
```

---

## P8-WRITE-FR-004 — Payload Hash Verification

EOS SHALL reconstruct the canonical business Tool payload and verify:

```text
computed PayloadHash == supplied PayloadHash
```

Mismatch:

```text
zero mutation
```

---

## P8-WRITE-FR-005 — Current EOS Authorization

Immediately before mutation, EOS SHALL verify fresh current authorization.

Initial scope:

```text
finance:voucher-draft:create
```

---

## P8-WRITE-FR-006 — Authorization Conjunction

Business mutation requires all applicable controls:

```text
valid package trust
AND valid NSL RuntimePreflight
AND valid NSL ApprovalEvidence
AND WriteGuard ALLOW
AND durable NSL idempotency reservation
AND current EOS/OA business authorization
AND EOS business preconditions
```

Any required DENY/INDETERMINATE SHALL block mutation.

---

## P8-WRITE-FR-007 — No Upstream Override

A prior upstream ALLOW SHALL not override a current EOS/OA DENY.

---

# 25. EOS Business Idempotency

## P8-IDM-FR-001 — Durable Key

EOS SHALL persist durable business idempotency keyed by:

```text
tenant_id
idempotency_key
```

---

## P8-IDM-FR-002 — Binding

The idempotency record SHALL bind:

```text
business_operation_id
operation
payload_hash
business result
```

---

## P8-IDM-FR-003 — Exact Duplicate

Same key + same payload SHALL return the same original business result.

---

## P8-IDM-FR-004 — Payload Conflict

Same key + different payload SHALL fail:

```text
IDEMPOTENCY_CONFLICT
```

with zero duplicate mutation.

---

## P8-IDM-FR-005 — BusinessOperation Conflict

Same `BusinessOperationId` with inconsistent idempotency/payload identity SHALL
fail closed.

---

## P8-IDM-FR-006 — Create Expected Version

`CREATE_VOUCHER_DRAFT` SHALL not invent `expected_version = 0` merely to satisfy
a generic update contract.

Creation uses:

```text
BusinessOperationId
IdempotencyKey
PayloadHash
domain uniqueness
```

Later mutation APIs SHALL use explicit `expected_version` as required.

---

# 26. EOS Transaction / Outbox

## P8-TX-FR-001 — Atomic Business Commit

One EOS transaction SHALL atomically persist:

```text
VoucherDraft
business-operation record
idempotency result
transactional outbox record
```

or none.

---

## P8-TX-FR-002 — Outbox

Initial EOS outbox SHALL support at least:

```text
VOUCHER_DRAFT_CREATED
BUSINESS_TRANSACTION_COMMITTED
```

---

## P8-TX-FR-003 — Publication Failure

Committed business state SHALL not be rolled back merely because later event
publication fails.

---

## P8-TX-FR-004 — Metadata-Safe Event

EOS events SHALL not publish raw financial attachment content or credentials.

---

# 27. CommitState / Reconciliation

## P8-CMT-FR-001 — Three-Way Outcome

P8 SHALL preserve NSL:

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
```

---

## P8-CMT-FR-002 — Unknown Is Not Failure

`UNKNOWN_COMMIT_STATE` SHALL NOT be converted to ordinary NOT_COMMITTED or
generic retryable failure.

---

## P8-CMT-FR-003 — No Blind Retry

On unknown commit:

```text
no new business WRITE
```

until reconciliation determines authoritative state.

---

## P8-CMT-FR-004 — Business Operation Query

EOS SHALL provide authoritative query by:

```text
BusinessOperationId
```

returning enough state to resolve or continue reconciliation.

---

## P8-CMT-FR-005 — Reconciliation Result

Reconciliation SHALL determine one of:

```text
COMMITTED
NOT_COMMITTED
still UNKNOWN
```

with stable business references where committed.

---

# 28. Post-Write Verification

## P8-VFY-FR-001 — Read-Only Verification API

EOS SHALL provide a read-only canonical operation equivalent to:

```text
FINANCE.GET_VOUCHER_DRAFT
```

---

## P8-VFY-FR-002 — Verification Binding

Verification SHALL bind:

```text
VoucherRef
BusinessOperationId
Idempotency identity
expected business result
```

---

## P8-VFY-FR-003 — No Mutation

Verification API SHALL have no business side effects.

---

## P8-VFY-FR-004 — Commit Separation

If:

```text
COMMITTED + Verification FAILED
```

the Voucher remains committed.

---

## P8-VFY-FR-005 — No Recreate

Verification failure/unknown SHALL not recreate the Voucher Draft.

---

# 29. Formal Approval and Existing VoucherDraft

## P8-FA-FR-001 — Draft-Then-Business-Approval

Initial architecture SHALL permit:

```text
NSL_WRITE approval
→ create VoucherDraft
→ later BUSINESS_FORMAL approval workflow
```

This reflects VoucherDraft as the approval/draft business object.

---

## P8-FA-FR-002 — Formal Approval Proof

When required, EOS final business ApprovalProof SHALL bind the exact relevant
business operation/payload/intent identity.

---

## P8-FA-FR-003 — Material Change

After formal approval, material change to:

```text
amount
Project
Account
other policy-bound business field
material attachment according to later policy
```

SHALL invalidate/reopen approval as defined by EOS policy.

---

# 30. Security Requirements

## P8-SEC-FR-001 — Fail Closed

Trust, authorization, approval, or identity ambiguity SHALL fail closed.

---

## P8-SEC-FR-002 — No Raw Credentials

Raw credential material SHALL not be persisted in:

```text
NSL checkpoint
ApprovalWorkItem
ApprovalEvidence
RuntimeJob payload
VoucherDraft
EOS outbox
attachment metadata
audit evidence
```

---

## P8-SEC-FR-003 — Cross-Tenant Denial

Cross-tenant:

```text
ProjectRef
AccountRef
AttachmentRef
ApprovalEvidence
WorkItem lineage
```

SHALL be rejected.

---

## P8-SEC-FR-004 — Service DB Isolation

No service SHALL directly write another service's database.

---

## P8-SEC-FR-005 — Protected Evidence

Approval payloads, NSL checkpoints, and sensitive financial evidence SHALL use
protected storage appropriate to their classification.

---

# 31. Audit / Traceability

## P8-AUD-FR-001 — End-to-End Correlation

P8 SHALL support tracing:

```text
tenant_id
correlation_id
AgentExecutionId
ExecutableStepId
NSLExecutionId
BusinessOperationId
ApprovalRequestId
ApprovalWorkItemId
WaitId
RuntimeJobId
IdempotencyKey
EOS BusinessOperationRef
VoucherRef
```

---

## P8-AUD-FR-002 — Evidence by Owner

Ownership:

```text
NSL detailed WRITE evidence     → NSL semantics / protected persistence adapter
Agent execution/runtime         → AE
Work/Claim/Approval human task  → WC
Authorization                   → OA
Business transaction            → EOS
Object bytes                    → RustFS
```

---

## P8-AUD-FR-003 — No Secret Logs

Logs SHALL use safe references/hashes and SHALL not include raw secrets,
credentials, or unbounded protected payloads.

---

# 32. Observability

P8 SHALL expose metrics sufficient to observe:

```text
NSL v0.2 admission/readiness
WAITING_FOR_APPROVAL age/count
ApprovalWorkItem pending/approved/rejected/expired counts
approval authorization denial
resume duplicate suppression
delegation depth/budget denials
delegation cycle denials
EOS Voucher Draft create success/failure
EOS idempotency reuse/conflict
UNKNOWN_COMMIT_STATE count
reconciliation backlog
verification FAILED/UNKNOWN
EOS outbox backlog
```

Metrics SHALL use bounded labels.

---

# 33. Persistence Requirements

## 33.1 AE

P8 SHALL extend AE persistence for:

```text
NSL v0.2 execution binding
protected checkpoint reference/state
NSL_APPROVAL WaitRegistration
typed external approval event
RESUME_EXECUTION linkage
approval evidence refs
```

Current P7 WorkResult rows SHALL remain readable.

---

## 33.2 WC

P8 SHALL add durable structures equivalent to:

```text
wc_delegation_lineage
wc_approval_work_item
wc_approval_decision
wc_approval_outbox
```

Exact migration names are assigned during slices.

---

## 33.3 EOS

P8 initial EOS persistence SHALL support logical structures equivalent to:

```text
eos_nvt_project
eos_project
eos_account

eos_org_unit
eos_position
eos_position_assignment

eos_business_operation
eos_idempotency

eos_voucher_draft
eos_voucher_draft_line
eos_voucher_draft_attachment

eos_approval_policy
eos_approval_instance
eos_approval_stage
eos_approval_decision
eos_approval_proof

eos_outbox
eos_reconciliation
```

Not all formal approval tables must be activated before Golden A if the P8
slice plan stages them later.

---

# 34. Database Integrity Requirements

P8 SHALL enforce where practical:

```text
foreign keys
unique semantic identities
state CHECK constraints
non-negative versions
tenant-qualified uniqueness
append-only decision history
idempotency uniqueness
```

Hierarchy depth/cycle and concurrent descendant-budget controls may require
transactional service logic in addition to database constraints.

---

# 35. Logical API Surface

P8 SHALL implement authenticated service operations sufficient for:

### WC

```text
Create/Get ApprovalWorkItem
List pending ApprovalWorkItems for authorized principal
Read ApprovalWorkItem
Submit ApprovalDecision
Create delegated WorkItem
Route / Claim with cycle guard
```

### EOS Organization

```text
Read NVTProject
Read Project
Resolve Project hierarchy/NVT
Resolve business approver
```

### EOS Finance

```text
FINANCE.CREATE_VOUCHER_DRAFT
FINANCE.GET_VOUCHER_DRAFT
GET BusinessOperation status/reconciliation state
```

### EOS Approval

```text
create/get ApprovalInstance
advance ApprovalStage from validated WC decision
read final ApprovalProof
```

Exact HTTP paths SHALL be fixed in P8 OpenAPI contract slices.

---

# 36. Event Surface

Minimum P8 events:

```text
NSL_APPROVAL_DECIDED
BUSINESS_FORMAL_APPROVAL_DECIDED
VOUCHER_DRAFT_CREATED
BUSINESS_TRANSACTION_COMMITTED
```

Existing P7:

```text
CLAIM_EXECUTION_HANDOFF
WORK_RESULT_SUBMITTED
```

remain unchanged.

All event consumers SHALL be idempotent.

---

# 37. Error Taxonomy

P8 SHALL expose stable safe error codes.

At minimum categories:

```text
NSL_RELEASE_ADMISSION_FAILED
NSL_BACKEND_PROFILE_UNSUPPORTED

APPROVAL_REQUEST_CONFLICT
APPROVAL_AUTHORIZATION_DENIED
APPROVAL_AUTHORIZATION_UNAVAILABLE
APPROVAL_TARGET_MISMATCH
APPROVAL_DECISION_CONFLICT
APPROVAL_EVIDENCE_INVALID
APPROVAL_EXPIRED

DELEGATION_HOP_LIMIT_EXCEEDED
DELEGATION_CHILD_BUDGET_EXCEEDED
DELEGATION_ROOT_BUDGET_EXCEEDED
DELEGATION_CYCLE_DETECTED
DELEGATION_PARENT_AUTHORITY_STALE

EOS_PROJECT_INVALID
EOS_ACCOUNT_INVALID
EOS_VOUCHER_UNBALANCED
EOS_PAYLOAD_HASH_MISMATCH
EOS_AUTHORIZATION_DENIED
EOS_IDEMPOTENCY_CONFLICT
EOS_UNKNOWN_COMMIT_STATE
EOS_VERIFICATION_FAILED
```

Internal exceptions SHALL not leak secrets.

---

# 38. Non-Functional Requirements

## P8-NFR-001 — Determinism

All final:

```text
routing
delegation admission
approval state transition
authorization
idempotency
business mutation
commit/reconciliation interpretation
```

SHALL be deterministic and testable.

---

## P8-NFR-002 — Reliability

Process restart, duplicate event, ACK loss, lease expiry, or response loss SHALL
not produce duplicate authoritative business mutation.

---

## P8-NFR-003 — Compatibility

P7 IA/CA/PA/EA READ and delegation behavior SHALL remain regression compatible
unless explicitly versioned.

---

## P8-NFR-004 — Privacy

Raw prompt, protected business payload, document bytes, and credentials SHALL
not be copied across service boundaries unnecessarily.

---

## P8-NFR-005 — Boundedness

All:

```text
delegation depth
fan-out
list/page result
attachment metadata count
runtime job payload
event payload
approval summary
```

SHALL be bounded.

---

## P8-NFR-006 — Auditability

Every authority-bearing P8 transition SHALL be explainable from durable
metadata/reference evidence.

---

## P8-NFR-007 — Transaction Safety

Financial WRITE paths SHALL prefer immutable/versioned correction over
destructive overwrite.

---

## P8-NFR-008 — Performance

Interactive Project/Account resolution, Approval Inbox, and Voucher Draft
creation SHALL have bounded latency budgets defined and measured in
implementation slices.

No exact numeric SLA is frozen by this SRS without measured baseline evidence.

---

# 39. Golden A Acceptance

Initial protected E2E:

```text
User Prompt
→ P6.5 live planning provider
→ deterministic PlanValidation / Compiler
→ LOCAL_SKILL
→ actual admitted NSL v0.2 wheel
→ READ / CHECK
→ WriteIntent
→ durable checkpoint
→ NSL_WRITE ApprovalWorkItem
→ IA HumanGate
→ fresh OA approval:decide
→ ApprovalEvidence
→ AE RESUME_EXECUTION
→ NSL resume
→ WriteGuard
→ IdempotencyKey
→ WRITE_REQUESTED
→ EOS FINANCE.CREATE_VOUCHER_DRAFT
→ COMMITTED
→ EOS verification read
→ VERIFIED
→ AgentResult
```

Required actual infrastructure:

```text
actual AE PostgreSQL
actual WC PostgreSQL
actual OA PostgreSQL
actual EOS PostgreSQL
actual admitted NSL v0.2 wheel
live generation provider
```

RustFS is required in Golden A only if that scenario includes an actual
attachment.

---

# 40. Golden A Business Example

Representative scenario:

```text
"출장비 84,000원을 A 프로젝트에 처리해줘"
```

Deterministic resolution may produce:

```text
NVT-X
  └─ Mother Project A
       └─ Project A-2

ProjectRef = exact Project A-2 stable ID
AccountRef = exact resolved travel-expense account

Voucher Draft
  ├─ ProjectRef
  ├─ balanced accounting lines
  ├─ description
  ├─ optional AttachmentRefs
  └─ source/evidence refs
```

No NVT token accounting is required.

---

# 41. Delegation Guard Acceptance

Required protected scenarios:

```text
DG-01 depth 1 PASS
DG-02 depth 10 current WorkItem may execute
DG-03 depth 10 child delegation DENIED
DG-04 Claim does not increment depth
DG-05 sixth direct child DENIED
DG-06 descendant 51 denied when max=50
DG-07 A→B→A cycle denied at Claim
DG-08 stale parent Claim cannot delegate
DG-09 expired parent Claim cannot delegate
DG-10 concurrent child creation cannot exceed budget
DG-11 revoked work:delegate blocks create/replay
DG-12 denied delegation creates zero child AgentExecution
```

---

# 42. Approval Acceptance

Required scenarios:

```text
AP-01 checkpoint saved before publish
AP-02 WaitRegistration exists before human task is actionable
AP-03 duplicate ApprovalRequestId create/get
AP-04 same ID / different semantics conflict
AP-05 inactive approver denied
AP-06 missing approval:decide denied
AP-07 wrong target principal denied
AP-08 OA unavailable fail closed
AP-09 one APPROVE creates one immutable decision
AP-10 duplicate exact APPROVE idempotent
AP-11 APPROVE then REJECT conflict
AP-12 duplicate approval event creates one RESUME_EXECUTION
AP-13 wrong BusinessOperationId blocks resume
AP-14 wrong ApprovalRequestId blocks resume
AP-15 WriteIntentHash mismatch blocks resume
AP-16 PayloadHash mismatch blocks resume
AP-17 expired Approval requires reapproval
AP-18 REJECT never reaches EOS WRITE
```

---

# 43. EOS Acceptance

Required scenarios:

```text
EOS-01 valid Voucher Draft commit
EOS-02 invalid ProjectRef denied
EOS-03 inactive AccountRef denied
EOS-04 unbalanced Voucher denied
EOS-05 missing finance:voucher-draft:create denied
EOS-06 OA unavailable fail closed
EOS-07 same key/same payload returns same Voucher
EOS-08 same key/different payload conflict
EOS-09 payload hash mismatch zero mutation
EOS-10 response lost after commit reconciles to same Voucher
EOS-11 UNKNOWN_COMMIT_STATE no blind retry
EOS-12 transaction + outbox atomic
EOS-13 verification read side-effect free
EOS-14 COMMITTED + verification failure no recreate
EOS-15 cross-tenant Project/Account/Attachment denied
```

---

# 44. Project / NVT Acceptance

Required:

```text
PRJ-01 Mother Project requires NVTProject
PRJ-02 Child requires parent Project
PRJ-03 depth 3 PASS
PRJ-04 depth 4 denied
PRJ-05 cycle denied
PRJ-06 NVT aggregate returns all descendant Projects
PRJ-07 descendant resolves correct NVT through Mother
PRJ-08 unrelated NVT lineage cannot be silently crossed
```

---

# 45. Attachment Acceptance

Required metadata tests:

```text
ATT-01 no attachment PASS
ATT-02 one attachment ref PASS
ATT-03 multiple attachment refs PASS
ATT-04 cross-tenant object ref denied
ATT-05 durable row contains object ref, not credential
ATT-06 presigned URL not accepted as durable object identity
```

Actual upload/download smoke is required only when the RustFS integration slice
is activated.

---

# 46. Fault / Recovery Acceptance

At minimum:

```text
duplicate RuntimeJob
duplicate Approval event
Approval publication ACK lost
EOS response lost after commit
provider timeout before known commit
UNKNOWN_COMMIT_STATE
reconciliation still unknown
COMMITTED + Verification FAILED
COMMITTED + Verification UNKNOWN
EOS outbox delivery failure
package trust failure
current authorization revoked
worker crash after checkpoint
worker crash after WRITE_REQUESTED
```

For any scenario where EOS commit occurred:

```text
business mutation count = 1
```

---

# 47. Test Strategy

Every functional slice SHALL follow:

```text
refactor first
unit tests
boundary-value tests
robustness tests
worst-case tests
service integration tests
PostgreSQL protected tests
contract tests
regression tests
Playwright for IA/AE-WEB
commit only after gates pass
```

Database tests SHALL reset/use isolated test data and verify cleanup/residue.

---

# 48. Quality Gate

Platform P8 release gate:

```text
Statement Coverage >= 96%
Branch Coverage    >= 94%
```

NSL repository gate remains:

```text
Statement Coverage >= 99%
Branch Coverage    >= 98%
```

A Platform integration test SHALL not substitute for the native NSL release
certification.

---

# 49. Contract Validation

P8 machine-readable contracts SHALL pass:

```text
JSON Schema Draft 2020-12 validation
OpenAPI parse/validation
positive examples
negative examples
service contract parity tests
runtime/schema semantic parity
```

Contract validation SHALL cover Approval domains and EOS WRITE payload/result
semantics, not only endpoint existence.

---

# 50. Migration Requirements

Migrations SHALL be:

```text
additive
historical-row-safe
service-owned
restart-safe
idempotent where repository convention requires
```

P7 data SHALL remain readable.

No migration SHALL silently reinterpret historical P7 WorkResult waits as
approval waits.

---

# 51. Recommended Implementation Slices

The SRS recommends the following major sequence.

```text
P8.1
NSL v0.2 Release Admission
+ NSL_V02_IN_PROCESS
+ compatibility acceptance

P8.2
NeX-EOS Foundation
+ DB
+ Organization
+ NVTProject / Project
+ Account / Voucher minimum

P8.2A
WC Delegation Guard

P8.3
ApprovalWorkItem
+ IA HumanGate
+ OA approval authorization
+ approver resolution

P8.4
NSL Approval Suspend / Resume Integration

P8.5
Governed WRITE → EOS

P8.6
Golden A Voucher Draft

P8.7
BUSINESS_FORMAL / multi-stage approval

P8.8
Commit uncertainty / reconciliation / verification fault closure

Full Gate
```

`P8.2` and `P8.2A` MAY proceed in parallel after shared contracts are frozen.

---

# 52. P8.1 Exit Gate — NSL v0.2 Admission

Required:

```text
actual wheel verified
package version accepted as v0.2
source revision/tree pinned
wheel SHA256 pinned
public API imported
NSL_V02 profile active
wrong/stale wheel fails closed
v0.1 READ regression PASS
v0.2 READ smoke PASS
v0.2 Controlled WRITE mock smoke PASS
```

No EOS business mutation is required yet.

---

# 53. P8.2 Exit Gate — EOS Foundation

Required:

```text
nex-eos starts/readies
nex_eos_dev works
nex_eos_test works
service trust works
NVTProject / Project depth/cycle works
minimal Account works
VoucherDraft aggregate works
EOS idempotency foundation works
transactional outbox works
```

---

# 54. P8.2A Exit Gate — Delegation Guard

Required:

```text
depth
child budget
root budget
current parent Claim
claim-time cycle detection
concurrency-safe budget enforcement
P7 delegation regression
```

all PASS.

---

# 55. P8.3 Exit Gate — Human Approval Foundation

Required:

```text
ApprovalWorkItem persistence
IA pending inbox
fresh OA approval:read/decide
target validation
Approve/Reject
duplicate/conflict behavior
BUSINESS_FORMAL schema/domain support
```

No NSL resume is required until P8.4.

---

# 56. P8.4 Exit Gate — NSL Approval Resume

Required real flow:

```text
NSL WAITING_FOR_APPROVAL
→ durable AE wait
→ WC decision
→ NSL_APPROVAL_DECIDED
→ one RESUME_EXECUTION
→ exact same NSLExecutionId / BusinessOperationId
→ valid NSL ApprovalEvidence
```

No EOS WRITE is required until P8.5.

---

# 57. P8.5 Exit Gate — Governed WRITE

Required:

```text
NSL WriteGuard
Idempotency
WRITE_REQUESTED
fresh EOS authorization
EOS command
three-way CommitState
reconciliation query
verification read
```

with mock/controlled business data.

---

# 58. P8.6 Exit Gate — Golden A

Golden A SHALL run end-to-end using:

```text
live planning provider
actual admitted NSL v0.2 wheel
actual AE/WC/OA/EOS PostgreSQL
actual IA approval interaction or protected equivalent acceptance client
```

and prove:

```text
exactly one Voucher Draft mutation
```

---

# 59. P8.7 Exit Gate — Formal Business Approval

Required:

```text
BUSINESS_FORMAL distinct from NSL_WRITE
EOS ApprovalPolicy / Instance / Stage
PART_LEAD → TEAM_LEAD → GROUP_LEAD → CEO → CHAIRMAN capability
WC human task projection
fresh OA decision authority
final EOS ApprovalProof
no cross-domain evidence substitution
```

Not every scenario must use all five levels.

---

# 60. P8.8 Exit Gate — Reliability Closure

Required:

```text
duplicate suppression
response-loss recovery
UNKNOWN_COMMIT_STATE
reconciliation
COMMITTED + verification failure
outbox retry
worker crash/restart
approval replay/tamper/expiry
trust failure
authorization revocation
```

all PASS without duplicate business mutation.

---

# 61. Final Full Gate

P8 Full Gate SHALL include:

```text
all prior P4-P7 regression
P8 focused unit/integration
contract validation
PostgreSQL protected tests
IA Playwright approval tests
NSL wheel admission tests
Golden A
fault/recovery suite
coverage thresholds
reference hygiene
zero uncontrolled migration drift
```

---

# 62. Definition of Done

P8 is DONE only when:

```text
[ ] NSL v0.2 exact wheel admission PASS
[ ] NSL v0.2 release identity pinned
[ ] NSL_V02_IN_PROCESS active
[ ] v0.1 historical compatibility preserved

[ ] WC Delegation Guard active
[ ] depth/fan-out/root/cycle controls PASS
[ ] nested delegation requires current Claim

[ ] WC ApprovalWorkItem runtime active
[ ] IA Approval Inbox active
[ ] fresh OA approval decision authorization active
[ ] NSL ApprovalEvidence bridge active
[ ] one approval event → at most one resume

[ ] NeX-EOS service active
[ ] nex_eos_dev / nex_eos_test operational
[ ] Organization minimum active
[ ] NVTProject separate object active
[ ] Project max depth 3 enforced
[ ] Account minimum active
[ ] VoucherDraft active
[ ] attachment stable-ref model active or explicitly deferred with schema support

[ ] FINANCE.CREATE_VOUCHER_DRAFT active
[ ] EOS business idempotency active
[ ] EOS transactional outbox active
[ ] UNKNOWN_COMMIT_STATE reconciliation active
[ ] post-write verification active

[ ] Golden A PASS
[ ] exactly-one business mutation proven
[ ] Formal Business Approval foundation PASS
[ ] required fault variants PASS

[ ] Platform statement coverage >= 96%
[ ] Platform branch coverage >= 94%
[ ] NSL native certification remains PASS
[ ] Repository Full Gate PASS
```

---

# 63. Final P8 SRS Position

The target P8 architecture is:

```text
                    Natural Language
                          │
                          ▼
                  IA / Agent Runtime
                          │
                Plan Candidate only
                          │
                          ▼
                Deterministic Compiler
                          │
                          ▼
                    NSL v0.2
        READ / CHECK / Approval / WRITE Guard
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
       WC Human Work              OA Authority
   Approval / Delegation          Current Decision
             │                         │
             └────────────┬────────────┘
                          ▼
                     Enterprise OS
          Organization / NVT / Project / Account
             Voucher / Formal Approval / Tx
                          │
                          ▼
                  Authoritative State
```

For attachments:

```text
EOS VoucherDraft
→ attachment metadata / stable object_ref
→ existing RustFS binary storage
```

For Project hierarchy:

```text
NVTProject
    ↓
Mother Project
    ↓
Project Level 2
    ↓
Project Level 3
```

For business safety:

```text
LLM proposal
!= Work authority
!= Approval authority
!= WRITE authority
!= Business commit proof
```

Final invariant:

> **P8 SHALL make natural-language enterprise WRITE possible without allowing any probabilistic Agent output, human UI action, retry, or transport event to bypass the deterministic authority chain.**
