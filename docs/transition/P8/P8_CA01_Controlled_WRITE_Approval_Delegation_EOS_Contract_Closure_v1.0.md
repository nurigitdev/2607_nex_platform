# P8-CA01 — Controlled WRITE / Approval / Delegation / EOS Contract Closure v1.0

**Status:** CONTROLLED ARCHITECTURE / CONTRACT CLOSURE — PROPOSED BASELINE  
**Phase:** P8 — Controlled WRITE / Approval / Enterprise OS  
**Purpose:** Close source-backed P8 contract gaps before P8 SRS and implementation slicing  
**Predecessor:** P8 Pre-Architecture Decision v1.0 / P8 Source Audit v1.0  
**Platform Repository:** `nurigitdev/2607_nex_platform`  
**Platform Baseline Commit:** `ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a`  
**Platform Baseline Tree:** `c0901e9e2af266b400adc07dddd815c77fae2ae1`  
**NSL Repository:** `nurigitdev/2608_nsl`  
**NSL v0.2 Source Commit:** `5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6`  
**NSL v0.2 Source Tree:** `71dbea8cca563867b12acd07462a2dcd42d9a8ac`  
**Date:** 2026-10-21

---

## 1. Closure Objective

P8 Source Audit confirmed that NSL v0.2 is already implemented and certified.

Therefore P8 SHALL NOT reimplement:

```text
ApprovalEvidence validation
WriteIntent construction / hashing
IdempotencyKey derivation
WriteGuard
durable WRITE_REQUESTED semantics
CommitState algebra
VerificationStatus semantics
Signed NSP trust
WRITE Replay no-live-write safety
```

P8-CA01 closes the remaining contracts needed to connect that deterministic
runtime to:

```text
NeX-AE
NeX-WC
NeX-OA
IA / AE-WEB
NeX-EOS
```

and to introduce bounded recursive Agent delegation.

The required closure areas are:

```text
CA01-A  NSL v0.2 Release Admission
CA01-B  NSL Approval Request / Evidence Bridge
CA01-C  AE Wait / Resume Generalization
CA01-D  WC ApprovalWorkItem Runtime
CA01-E  EOS Formal Approval / HumanGate Domain
CA01-F  WC Delegation Guard
CA01-G  EOS Organization
CA01-H  Golden A Canonical Business WRITE
```

---

# 2. Normative Authority

P8-CA01 SHALL follow:

```text
Integrated Frozen Platform v2.1 / Agent v2.1 / NSL v0.2
> Frozen machine-readable contracts
> NSL v0.2 certified As-Built source
> P7 Final As-Built / P7-CA02B
> P8 Pre-Architecture Decision
> P8 Source Audit
> this P8-CA01
> P8 SRS
> implementation convenience
```

Frozen files SHALL NOT be edited.

Where P8 requires an additive contract extension, the extension SHALL be placed
under a P8 transition/controlled-amendment contract set.

---

# 3. Closure Summary

The following decisions are fixed by P8-CA01.

```text
DEC-01  NSL v0.2 is admitted as an immutable release artifact.
DEC-02  P8 introduces NSL_V02_IN_PROCESS; v0.1 profiles remain distinct.
DEC-03  NSL execution_id maps exactly to Platform nsl_execution_id.
DEC-04  Platform persists the exact NSL ApprovalRequest as protected evidence.
DEC-05  NSL Approval publication registers AE wait before creating WC work.
DEC-06  NSL Approval decisions require fresh OA approval:decide authority.
DEC-07  Platform full ApprovalEvidence and NSL ApprovalEvidence projection are separated.
DEC-08  AE RESUME_EXECUTION is source-neutral; source adapters remain typed.
DEC-09  WC owns ApprovalWorkItem / human task lifecycle.
DEC-10  BUSINESS_FORMAL is introduced as a distinct approval domain.
DEC-11  EOS owns business ApprovalPolicy / Instance / Stage / Proof.
DEC-12  IA provides one approval inbox without merging approval semantics.
DEC-13  WC owns delegation depth, fan-out, root budget, and cycle guard.
DEC-14  Nested delegation requires current parent Claim authority.
DEC-15  EOS owns Organization; OA owns Principal / RoleBinding / authorization.
DEC-16  Corporate ladder supports PART_LEAD → TEAM_LEAD → GROUP_LEAD → CEO → CHAIRMAN.
DEC-17  FINANCE.CREATE_VOUCHER_DRAFT is the first authoritative EOS WRITE.
DEC-18  EOS performs fresh current authorization immediately before mutation.
DEC-19  UNKNOWN_COMMIT_STATE never causes blind retry.
DEC-20  Golden A closes before Dual/Formal Business Approval expansion.
```

---

# 4. DEC-01 — NSL v0.2 Release Artifact Is the Integration Unit

The P8 Platform SHALL not import arbitrary source checkout state.

Admission unit:

```text
nex-skill-language wheel
```

Required immutable evidence:

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
Platform dependency-lock SHA256
CI certification reference
```

Recommended Platform lock:

```text
deployment/locks/nsl-v0.2-wheel.json
```

The existing:

```text
services/_shared/nex_runtime/nsl_package_admission.py
```

SHALL be reused and versioned only where needed.

No second wheel inspection/admission framework is authorized.

---

# 5. NSL v0.2 Release Admission Gate

The current NSL source tree still reports:

```toml
name = "nex-skill-language"
version = "0.1.0"
```

while the source implementation is certified as NSL v0.2.

Therefore P8 admission SHALL inspect the actual released wheel.

Required:

```text
distribution == nex-skill-language
package_version is explicitly admitted as 0.2.x
source_revision == approved NSL v0.2 release source
wheel SHA256 == lock SHA256
public API == admitted inventory
```

If the actual wheel METADATA still identifies the package as `0.1.0`:

```text
P8 NSL v0.2 admission = FAIL CLOSED
```

and a corrected wheel SHALL be released.

Do not solve release identity by silently treating package version `0.1.0` as
v0.2.

---

# 6. DEC-02 — Versioned NSL Backend Profiles

Existing P7 profiles remain valid:

```text
NSL_V01_IN_PROCESS
NSL_V01_PROCESS_ISOLATED
```

P8 adds:

```text
NSL_V02_IN_PROCESS
```

Optional only if needed:

```text
NSL_V02_PROCESS_ISOLATED
```

Initial P8 Controlled WRITE profile:

```text
DEFAULT_P8_WRITE_NSL_PROFILE = NSL_V02_IN_PROCESS
```

The existing v0.1 profile SHALL NOT be renamed or silently reinterpreted.

This preserves regression and historical evidence.

---

# 7. NSL Backend Selection

Backend profile selection SHALL be deterministic.

At minimum it must consider:

```text
admitted Skill language version
IR version
required feature set
release lock
configured deployment profile
```

Example:

```text
NSL 0.1 / IR 1.0 / READ-only
→ admitted v0.1 or backward-compatible admitted v0.2 path according to explicit policy

NSL 0.2 / IR 1.1 / WRITE
→ NSL_V02_IN_PROCESS only
```

A WRITE Skill SHALL never fall back to `NSL_V01_*`.

---

# 8. DEC-03 — NSL Execution Identity Mapping

The certified NSL v0.2 public API uses:

```text
ApprovalRequest.execution_id
ApprovalEvidence.execution_id
ResumeToken.execution_id
```

The Platform Frozen integration terminology uses:

```text
nsl_execution_id
```

P8 fixes the mapping:

```text
NSL execution_id
==
Platform nsl_execution_id
```

This is a naming-boundary mapping only.

Do not create a second NSL execution identity.

The following remain distinct:

```text
AgentExecutionId
ExecutableStepId
NSLExecutionId
BusinessOperationId
RuntimeJobId
ApprovalRequestId
ApprovalWorkItemId
```

---

# 9. BusinessOperationId Mapping

Platform creates and owns the stable business-operation identity.

The same value SHALL be passed unchanged into NSL:

```text
Platform business_operation_id
==
NSL BusinessOperationId
```

It remains stable across:

```text
approval suspension
human wait
resume
RuntimeJob retry
AE worker restart
provider response loss
reconciliation
verification recovery
```

A RuntimeJob retry SHALL NOT generate a new BusinessOperationId.

---

# 10. Source-Observed Approval Request Difference

The actual NSL v0.2 `ApprovalRequest` contains:

```text
tenant_id
execution_id
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
risk_level
message
expires_at
display_safe_summary
protected_payload_ref
data_classification
```

The existing Frozen Platform `NSLWriteApprovalRequest v2.1` contains a narrower
projection:

```text
tenant_id
nsl_execution_id
business_operation_id
approval_id
approval_request_id
skill_semantic_hash
write_node_id
tool_id
payload_hash
write_intent_hash
checkpoint_version
display_safe_summary
expires_at
```

P8 SHALL NOT force either side to redefine its canonical model.

---

# 11. DEC-04 — Exact NSL ApprovalRequest Is Preserved as Protected Evidence

When NSL publishes an `ApprovalRequest`, the Platform adapter SHALL persist an
exact canonical serialized copy as protected evidence.

Required:

```text
protected_request_ref
approval_request_hash
```

The protected snapshot contains the complete NSL request.

The WC/IA projection contains only metadata-safe fields.

This preserves:

```text
NSL source semantics
+
Platform workflow semantics
+
data minimization
```

---

# 12. P8 NSL Approval Publication Envelope

Introduce a P8 transition contract:

```text
P8NSLWriteApprovalEnvelope v1
```

Recommended fields:

```text
schema_version

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

Mapping:

```text
NSL ApprovalRequest.execution_id
→ nsl_execution_id

NSL protected_payload_ref
→ remains inside protected request evidence

NSL display_safe_summary
→ safe IA/WC presentation projection
```

`message` SHALL not automatically be copied to generic notification channels.

---

# 13. Approval Request Identity

Canonical NSL approval identity:

```text
tenant_id
+
nsl_execution_id
+
business_operation_id
+
approval_request_id
+
write_intent_hash
+
payload_hash
+
checkpoint_version
```

`ApprovalRequestId` SHALL be idempotent.

Same `ApprovalRequestId` + same semantic envelope:

```text
→ same ApprovalWorkItem
```

Same `ApprovalRequestId` + different semantic envelope:

```text
→ conflict
→ fail closed
```

---

# 14. DEC-05 — Approval Publication Ordering

Certified NSL already enforces:

```text
checkpoint persisted
before
ApprovalPort.publish()
```

P8 Platform extends the publish path as:

```text
NSL checkpoint persisted
        ↓
ApprovalPort.publish(request)
        ↓
AE ensure WaitRegistration(NSL_APPROVAL)
        ↓
commit AE wait
        ↓
WC create_or_get ApprovalWorkItem
        ↓
human workflow
```

The AE wait SHALL be durable before the approval can become human-decisionable.

This prevents:

```text
approval decision
→ arrives before any durable resume target exists
```

---

# 15. Approval Publication Failure Semantics

If:

```text
AE wait committed
but
WC ApprovalWorkItem creation fails
```

then:

```text
NSL remains WAITING_FOR_APPROVAL
AE wait remains PENDING
approval publication is retryable
same ApprovalRequestId is reused
```

If:

```text
WC create commits
but response is lost
```

retry SHALL:

```text
create_or_get same ApprovalWorkItem
```

and SHALL NOT create duplicate human work.

---

# 16. DEC-06 — Approval Decision Authorization

A human decision is authority-bearing.

P8 introduces OA scopes:

```text
approval:read
approval:decide
```

Minimum behavior:

```text
Approval Inbox read
→ current approval:read

APPROVE / REJECT
→ fresh OA effective authorization
→ active == true
→ approval:decide present
→ target approver/role/org scope compatible
```

Failure:

```text
inactive principal
missing approval:decide
target mismatch
scope mismatch
OA unavailable
malformed authorization
→ FAIL CLOSED
→ no decision committed
```

No cached planning-time authority may substitute for decision-time authority.

---

# 17. Approval Decision Must Preserve OA Evidence

A committed approval decision SHALL preserve metadata-safe authority evidence:

```text
decided_by principal_ref
decided_at
oa_decision_ref
authorization_revision_hash or equivalent
authorization_checked_at
```

Do not persist:

```text
raw access token
raw credential
full authentication payload
```

---

# 18. DEC-07 — Platform Approval Evidence and NSL ApprovalEvidence Are Different Layers

The Frozen Platform approval evidence includes Platform authority lineage such
as:

```text
approval_work_item_ref
oa_decision_ref
```

The certified NSL `ApprovalEvidence` intentionally contains the deterministic
binding fields required by NSL:

```text
tenant_id
execution_id
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
evidence_integrity
```

P8 SHALL preserve both layers.

---

# 19. Canonical Platform Approval Evidence Record

P8 SHALL persist a full immutable approval evidence object containing:

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

Recommended:

```text
evidence_integrity
= sha256(canonical immutable approval evidence)
```

The object is immutable after creation.

---

# 20. NSL ApprovalEvidence Projection

AE constructs the NSL public `ApprovalEvidence` projection from the canonical
Platform evidence.

Mapping:

```text
Platform nsl_execution_id
→ NSL execution_id

Platform APPROVE
→ NSL APPROVED

Platform REJECT
→ NSL REJECTED

Platform evidence_integrity
→ NSL evidence_integrity
```

No Platform field may override:

```text
BusinessOperationId
ApprovalRequestId
PayloadHash
WriteIntentHash
```

from the original request binding.

---

# 21. ApprovalEvidenceVerifier Adapter

P8 SHALL provide an NSL `ApprovalEvidenceVerifier` implementation.

It SHALL verify the full Platform evidence corresponding to:

```text
approval_request_id
+
evidence_integrity
```

and at minimum prove:

```text
WC ApprovalWorkItem exists
terminal decision matches
decision is immutable/current
approver matches
OA decision evidence exists
tenant matches
approval request binding matches
canonical evidence hash matches
```

NSL then performs its own deterministic semantic validation.

Thus:

```text
Platform verifier
= provenance / authority verification

NSL ApprovalEvidenceValidator
= deterministic semantic binding verification
```

Neither replaces the other.

---

# 22. DEC-08 — Generalize AE Wait/Resume by Source, Not by Fake Event

P7 wait/resume architecture is retained.

P8 extends:

```text
wait_type =
  WORK_RESULT
  NSL_APPROVAL
```

No approval event SHALL be disguised as a WorkResult event.

Target architecture:

```text
AE Wait / Inbox / Resume Core
        │
        ├─ WORK_RESULT source adapter
        └─ NSL_APPROVAL source adapter
```

---

# 23. AE WaitRegistration Target Contract

P8 target fields:

```text
wait_id
tenant_id
agent_execution_id
executable_step_id

wait_type

external_ref
resume_contract_ref

state
version

matched_event_id
resume_runtime_job_id

created_at
satisfied_at
```

`external_ref` SHALL support string identities because:

```text
WorkItemId
ApprovalRequestId
```

need not share a UUID type contract.

Current P7 UUID-specific persistence SHALL be generalized without breaking
existing WORK_RESULT rows.

---

# 24. Wait State Model

Retain:

```text
PENDING
SATISFIED
RESUME_QUEUED
CONSUMED
CANCELLED
```

For `NSL_APPROVAL`:

```text
external_ref = ApprovalRequestId
resume_contract_ref = P8 NSL approval resume contract
```

One wait may be satisfied only by the exact approval lineage.

---

# 25. NSL Approval Event

Introduce typed event:

```text
NSL_APPROVAL_DECIDED
```

Minimum event projection:

```text
schema_version
tenant_id
event_id
approval_work_item_ref
approval_request_id
nsl_execution_id
business_operation_id
decision
approval_evidence_ref
evidence_integrity
correlation_id
causation_id
occurred_at
```

The event contains references and metadata-safe fields only.

No raw protected payload.

---

# 26. RESUME_EXECUTION Payload — NSL Approval

Recommended RuntimeJob payload:

```text
wait_id
event_id
approval_request_id
approval_work_item_ref
approval_evidence_ref
resume_token_ref
```

Required RuntimeJob lineage:

```text
job_type = RESUME_EXECUTION
agent_execution_id = exact parent AgentExecution
executable_step_id = exact LOCAL_SKILL step
wait_id = exact NSL_APPROVAL wait
```

Existing unique constraint:

```text
one RESUME_EXECUTION per wait
```

SHALL remain.

---

# 27. NSLApprovalResumeSource

Implement a sibling adapter to the P7 WorkResult resume source.

It SHALL admit resume only when:

```text
RuntimeJob is RUNNING
job_type == RESUME_EXECUTION
wait_type == NSL_APPROVAL
wait.state == RESUME_QUEUED
event inbox state == MATCHED
event_id matches
approval_request_id matches
approval_work_item_ref matches
approval_evidence_ref matches
resume_runtime_job_id matches
```

Anything else:

```text
fail closed
```

---

# 28. NSL Resume Identity

The adapter SHALL reconstruct:

```text
NSL ResumeToken
```

using:

```text
execution_id = existing nsl_execution_id
business_operation_id = existing BusinessOperationId
checkpoint_version = exact persisted checkpoint version
approval_evidence = verified NSL projection
```

No new:

```text
NSLExecutionId
BusinessOperationId
ApprovalRequestId
```

may be created on resume.

---

# 29. DEC-09 — WC Owns ApprovalWorkItem Runtime

WC is the durable human-task SoR.

P8 SHALL implement:

```text
wc_approval_work_item
wc_approval_decision
approval event outbox
```

or semantically equivalent service-local persistence.

WC owns:

```text
human task state
target approver/role/org/project scope
decision submission
decision deduplication
decision event publication
expiry/cancel task state
```

WC does NOT own:

```text
NSL approval semantic validation
EOS business approval policy
OA authorization policy
```

---

# 30. ApprovalWorkItem State

Retain Frozen state model:

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

Decision values:

```text
APPROVE
REJECT
```

Decision history SHALL be append-only.

The WorkItem projection may move to a terminal state, but a previous human
decision record SHALL not be overwritten.

---

# 31. ApprovalWorkItem Idempotency

Recommended semantic identity:

```text
tenant_id
approval_domain
source_ref
```

For NSL:

```text
source_ref = NSL ApprovalRequestId
```

Recommended deterministic WorkItem ID:

```text
UUIDv5(
  tenant_id
  + approval_domain
  + source_ref
)
```

Equivalent deterministic identity is acceptable if repository conventions
require another format.

---

# 32. Duplicate Decision Semantics

Same decision replay:

```text
same ApprovalWorkItem
same decision
same approver
same semantic decision
→ idempotent success
```

Conflicting second decision:

```text
APPROVED
then REJECTED
```

or different immutable authority binding:

```text
→ 409 conflict
→ original decision preserved
```

---

# 33. DEC-10 — Add BUSINESS_FORMAL Approval Domain

P8 introduces an additive transition contract value:

```text
BUSINESS_FORMAL
```

Canonical approval domains become:

```text
AGENT_FORMAL
NSL_WRITE
BUSINESS_FORMAL
```

`BUSINESS_FORMAL` SHALL NOT be represented as `AGENT_FORMAL`.

The Frozen contract files remain untouched.

P8 transition contracts SHALL extend them.

---

# 34. BUSINESS_FORMAL ApprovalWorkItem

For `BUSINESS_FORMAL`:

```text
source_ref
= EOS ApprovalStage stable ref

resume_target_ref
= EOS ApprovalInstance / stage transition target

business_operation_id
= required

protected_evidence_ref
= exact business approval payload/proof input ref
```

The WC WorkItem is the human-task projection.

EOS remains the authoritative business-approval state owner.

---

# 35. DEC-11 — EOS Owns Formal Business Approval

EOS owns:

```text
ApprovalPolicy
ApprovalInstance
ApprovalStage
ApprovalDecision
ApprovalProof
```

WC owns:

```text
ApprovalWorkItem
human assignment
human decision capture
decision event
```

Flow:

```text
EOS ApprovalPolicy
        ↓
ApprovalInstance
        ↓
active ApprovalStage
        ↓
WC BUSINESS_FORMAL ApprovalWorkItem
        ↓
Human decision
        ↓
fresh OA authorization
        ↓
WC approval event
        ↓
EOS stage transition
        ↓
next stage OR final ApprovalProof
```

---

# 36. Multi-Stage Corporate Approval

Corporate stages are NOT repeated NSL approve statements.

Canonical ladder capability:

```text
PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
```

EOS ApprovalPolicy may select any ordered subset.

Examples:

```text
PART_LEAD

PART_LEAD → TEAM_LEAD

TEAM_LEAD → GROUP_LEAD → CEO

GROUP_LEAD → CEO → CHAIRMAN
```

LLM output SHALL NOT authoritatively determine the approval chain.

---

# 37. NSL WRITE Approval vs BUSINESS_FORMAL Approval

They remain distinct.

```text
NSL_WRITE
= may this exact frozen WriteIntent execute?

BUSINESS_FORMAL
= does the company/domain approve this business operation?
```

One proof SHALL NOT satisfy the other.

When both are required:

```text
NSL ApprovalEvidence
AND
EOS BusinessApprovalProof
```

must each be valid.

Exact ordering for a specific dual-approval business scenario may be defined in
P8.7, but semantic substitution is forbidden now.

---

# 38. Golden A Approval Scope

Initial Golden A:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

closes:

```text
NSL_WRITE Approval
```

as the mandatory WRITE approval.

EOS Formal Business Approval is not required for the first Draft acceptance
unless the EOS policy explicitly requires it.

This prevents P8 Golden A from becoming a full corporate approval project.

---

# 39. HumanGateView Additive Extension

P8 HumanGate domain set:

```text
AGENT_FORMAL
NSL_WRITE
BUSINESS_FORMAL
HUMAN_CONFIRMATION
STEP_UP
```

For `BUSINESS_FORMAL`:

```text
approval_provider_type = EOS
approval_target_ref = EOS ApprovalStage ref
```

For `NSL_WRITE`:

```text
approval_provider_type = NSL
approval_target_ref = ApprovalRequestId
```

IA can render one inbox while preserving the exact domain.

---

# 40. DEC-12 — IA Is Presentation / Interaction, Not Approval SoR

Initial P8 interaction:

```text
User logs in
→ IA / AE-WEB
→ pending HumanGateView list
→ detail
→ APPROVE / REJECT
→ WC decision API
```

IA SHALL NOT:

```text
directly mutate NSL checkpoint
directly mutate EOS ApprovalInstance
store authoritative decision state
invent target approver
```

`action_ref` SHALL resolve to a controlled approval decision API.

---

# 41. Notification Boundary

Initial P8:

```text
online / next login
→ IA inbox
```

Deferred:

```text
Email
Push
Teams / Slack
mobile
```

When Email is introduced:

```text
notification + authenticated deep link
```

is preferred.

Email-reply approval is outside initial P8 scope.

---

# 42. DEC-13 — WC Owns Delegation Guard

Delegation safety is an admission concern of the Work SoR.

WC owns:

```text
root lineage
parent lineage
delegation depth
fan-out budget
root descendant budget
cycle admission
```

OA still owns:

```text
work:delegate current authorization
```

AE carries lineage context but does not become Delegation Guard SoR.

---

# 43. Delegation Guard Initial Policy

Initial P8 profile:

```text
max_delegation_depth       = 10
max_children_per_work_item = 5
max_descendants_per_root   = 50
cycle_detection            = ENABLED
```

These are WC/AG governed policy values.

The LLM may not:

```text
increase
override
disable
```

them.

Later policy changes require governance and regression.

---

# 44. Delegation Depth Definition

Canonical depth:

```text
first WorkItem created by an Agent DELEGATE_WORK
→ depth = 1

child delegated by claimed Agent
→ child depth = parent depth + 1
```

Claiming an existing WorkItem does not change depth.

At:

```text
depth == max_delegation_depth
```

the current WorkItem remains executable.

Only a new child delegation is denied.

---

# 45. Root / Parent Semantics

For first-level delegation:

```text
root_work_item_id   = current WorkItemId
parent_work_item_id = null
delegation_depth    = 1
```

For nested delegation:

```text
root_work_item_id   = parent.root_work_item_id
parent_work_item_id = current parent WorkItemId
delegation_depth    = parent.depth + 1
```

The root identity never changes.

---

# 46. DEC-14 — Nested Delegation Requires Current Parent Claim Authority

A background CA/PA/EA may create a child delegated WorkItem only when its parent
claim is still current.

Required nested lineage:

```text
parent_work_item_id
parent_claim_ref
parent_claim_generation
delegating_agent_ref
parent_agent_execution_id
```

WC SHALL verify immediately before child commit:

```text
parent Claim exists
Claim state == ACTIVE
Claim generation matches
lease not expired
Assignment matches
claimant_agent_ref == delegating_agent_ref
parent AgentExecution lineage matches
```

Stale parent authority:

```text
→ no child WorkItem
```

---

# 47. Delegation Lineage Persistence

Recommended new WC relation:

```text
wc_delegation_lineage
```

Logical fields:

```text
tenant_id
work_item_id

root_work_item_id
parent_work_item_id

parent_claim_ref
parent_claim_generation
delegating_agent_ref

delegation_depth

policy_ref
policy_hash

created_at
```

Primary relation:

```text
(tenant_id, work_item_id)
```

Indexes SHOULD support:

```text
root descendant count
parent child count
parent traversal
```

---

# 48. Child / Root Budget Semantics

Definitions:

```text
children(parent)
= direct delegated child WorkItems of one parent

descendants(root)
= all delegated WorkItems below the root
  excluding the root itself
```

Admission:

```text
current children(parent) + 1
<= max_children_per_work_item

current descendants(root) + 1
<= max_descendants_per_root
```

Concurrent child creation must not oversubscribe these limits.

---

# 49. Delegation Guard Atomicity

Child creation transaction must evaluate:

```text
fresh OA work:delegate
parent authority if nested
depth
child budget
root descendant budget
```

at the durable child-admission boundary.

Where concurrent creation can race, row/advisory locking or equivalent
transactional protection SHALL be used.

A read-count-then-insert sequence without concurrency protection is not
sufficient.

---

# 50. Cycle Detection Timing

Actual target Agent is not known when `DelegationSpec` is created.

Therefore:

```text
cycle detection at WorkItem create
```

is not sufficient.

P8 defines:

```text
depth / budget checks
→ child WorkItem create

routing
→ candidate selection

claim admission
→ candidate Agent cycle check
```

Cycle safety SHALL be rechecked immediately before Claim commit.

---

# 51. Cycle Definition

A candidate claimant is cyclic when:

```text
candidate_agent_ref
∈
ancestor delegating_agent_refs
```

within the same root lineage.

Example:

```text
PA-A
→ EA-B
→ CA-C
→ PA-A
```

The final PA-A candidate is ineligible.

Outcome:

```text
wc.delegation_cycle_detected
```

No Claim / child AgentExecution authority is created for that candidate.

---

# 52. Delegation Guard Error Codes

Recommended stable codes:

```text
wc.delegation_hop_limit_exceeded
wc.delegation_child_budget_exceeded
wc.delegation_root_budget_exceeded
wc.delegation_cycle_detected
wc.delegation_parent_authority_stale
wc.delegation_lineage_invalid
```

These are deterministic control failures, not LLM errors.

---

# 53. Delegation Failure Does Not Auto-Fail Current WorkItem

When another delegation is blocked:

```text
no child WorkItem
no child Claim
no child AgentExecution
```

The current Agent may still:

```text
complete locally
return failure result
request allowed input
produce partial result according to contract
```

P8 SHALL NOT add a generic WorkItem `FAILED` state only for hop exhaustion.

---

# 54. DEC-15 — EOS Owns Business Organization

EOS owns:

```text
OrgUnit
Position
PositionAssignment
Reporting hierarchy
business management ladder
business approval policy
```

OA owns:

```text
Principal
Authentication
Credential
RoleBinding
security scope
current authorization
```

EOS stores stable OA Principal refs only.

---

# 55. EOS Organization Minimal Model

### OrgUnit

```text
org_unit_id
org_unit_code
name
org_unit_type
parent_org_unit_ref
status
effective_from
effective_until
version
```

Initial `org_unit_type`:

```text
PART
TEAM
GROUP
COMPANY
```

### Position

```text
position_id
position_type
org_unit_ref
status
```

### PositionAssignment

```text
position_assignment_id
position_ref
principal_ref
effective_from
effective_until
status
version
```

No credential data is stored in EOS.

---

# 56. DEC-16 — Canonical Leadership Ladder

P8 supports:

```text
PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
```

This is a policy ladder, not a universal mandatory route.

For an ordinary requester, a simple NSL WRITE approval policy may resolve:

```text
first eligible superior position
```

from this ladder.

If no eligible approver can be resolved:

```text
approval routing fails closed
```

No self-approval fallback is allowed by default.

---

# 57. Separation of Duties

Initial approval rule:

```text
requester principal
!=
approver principal
```

unless an explicit, source-backed exception policy exists.

Future ActingAuthority:

```text
EOS identifies acting business relationship
OA still authorizes the acting principal at decision time
```

ActingAuthority is not required for first Golden A.

---

# 58. Organization Query Boundary

WC may call EOS through an internal organization-resolution API.

Example logical operation:

```text
ORGANIZATION.RESOLVE_APPROVER
```

Input:

```text
tenant_id
requester_principal_ref
approval_domain
risk_level
org_scope_ref
project_ref
policy_ref
```

Output:

```text
resolved_principal_ref
resolved_position_type
org_unit_ref
resolution_policy_ref
resolution_hash
```

This is a business organization resolution.

It does not grant security authority.

OA decision remains mandatory afterward.

---

# 59. DEC-17 — Golden A Canonical Business WRITE

First authoritative EOS command:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

The command creates a Draft only.

It does not:

```text
POST ledger
finalize accounting
close period
create P/L facts
```

unless later slices explicitly add those transitions.

---

# 60. Voucher Draft Command Request

Introduce:

```text
CreateVoucherDraftCommand v1
```

Recommended fields:

```text
schema_version
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

lines[]

nsl_approval_request_id
nsl_approval_evidence_ref

business_approval_proof_ref  # nullable for Golden A

trace
```

Each line:

```text
line_no
account_ref
signed_amount
economic_category
evidence_refs[]
```

Money SHALL use decimal-safe representation.

Binary floating point is not allowed for financial amount identity.

---

# 61. Voucher Draft Balance Rule

For the initial general accounting voucher profile:

```text
sum(signed_amount) == 0
```

unless a future explicit transaction type defines another equivalent invariant.

Golden A test data SHALL provide a balanced command.

EOS SHALL not rely on the LLM to assert balance.

---

# 62. Voucher Stable References

Input uses:

```text
ProjectRef
AccountRef
EvidenceRef
PrincipalRef
```

not display names as business identity.

EOS rejects:

```text
inactive project
closed/ineligible project
inactive/expired account
cross-tenant reference
ambiguous unresolved reference
```

according to current domain policy.

---

# 63. Canonical Payload Binding

The EOS request carries:

```text
payload_hash
```

from NSL WriteIntent.

EOS SHALL reconstruct the canonical Tool-contract business payload and verify:

```text
computed payload hash
==
provided payload_hash
```

Trace fields, transport metadata, OA decision refs, and idempotency metadata are
not silently mixed into the business payload hash unless the canonical Tool
Contract explicitly includes them.

Hash mismatch:

```text
→ fail closed
→ zero business mutation
```

---

# 64. EOS Idempotency Contract

EOS SHALL persist a durable record keyed by:

```text
tenant_id
idempotency_key
```

bound to:

```text
business_operation_id
payload_hash
operation
```

Semantics:

```text
same key + same payload
→ same original result

same key + different payload
→ IDEMPOTENCY_CONFLICT

same BusinessOperationId + inconsistent key/payload
→ semantic conflict
```

The committed Voucher count remains one.

---

# 65. Create vs Expected Version

`CREATE_VOUCHER_DRAFT` creates a new aggregate.

Therefore initial Draft creation relies on:

```text
BusinessOperationId
IdempotencyKey
PayloadHash
domain uniqueness
```

rather than an artificial `expected_version = 0`.

`expected_version` becomes mandatory for later important transitions on an
existing Voucher, such as Submit/Approve/Post when those slices are activated.

---

# 66. DEC-18 — EOS Performs Fresh Authorization at Mutation Boundary

NSL WriteGuard upstream authorization is required but does not replace EOS
business-command authorization.

Immediately before authoritative mutation EOS SHALL verify:

```text
authenticated service caller
current on-behalf-of principal
active == true
required business scope present
tenant/project/org/resource scope valid
```

Initial required scope:

```text
finance:voucher-draft:create
```

Failure:

```text
→ zero mutation
```

EOS may additionally verify a valid upstream GovernedWriteAuthorization.

An upstream ALLOW SHALL never override a current EOS/OA DENY.

---

# 67. Governed WRITE Authority Conjunction

Before EOS mutation, the overall P8 chain is:

```text
valid Signed NSP / package trust
AND
valid NSL RuntimePreflight
AND
valid NSL ApprovalEvidence
AND
WriteGuard ALLOW
AND
valid durable idempotency reservation
AND
fresh OA business command authorization
AND
EOS domain preconditions
→ business mutation
```

Any required DENY or INDETERMINATE:

```text
→ no WRITE
```

---

# 68. Voucher Draft Result

Introduce:

```text
CreateVoucherDraftResult v1
```

Recommended fields:

```text
schema_version
tenant_id
business_operation_id
idempotency_key
payload_hash

commit_state

idempotency_disposition

voucher_ref
business_transaction_ref

committed_at
outbox_event_ref

reason_code
reconciliation_ref
```

Rules:

```text
COMMITTED
→ voucher_ref required

NOT_COMMITTED
→ no committed business ref

UNKNOWN_COMMIT_STATE
→ reconciliation_ref required
```

---

# 69. EOS Transaction Boundary

One EOS database transaction SHALL atomically persist:

```text
Voucher Draft
idempotency record
business operation record
transactional outbox record
```

A committed business transaction SHALL not be rolled back merely because event
delivery later fails.

---

# 70. EOS Outbox Events

Initial events:

```text
VOUCHER_DRAFT_CREATED
BUSINESS_TRANSACTION_COMMITTED
```

At minimum include metadata-safe:

```text
tenant_id
event_id
business_operation_id
business_transaction_ref
voucher_ref
correlation_id
occurred_at
```

Do not publish raw financial detail by default.

---

# 71. DEC-19 — Reconciliation Query

EOS SHALL expose an authoritative operation-status query.

Logical API:

```text
GET /api/v1/business-operations/{business_operation_id}
```

It returns:

```text
business_operation_id
operation
payload_hash
commit_state
business_transaction_ref
voucher_ref
reconciliation_status
last_observed_at
```

NSL/AE may use it when provider invocation outcome is uncertain.

---

# 72. UNKNOWN_COMMIT_STATE

Forbidden:

```text
timeout
→ retry FINANCE.CREATE_VOUCHER_DRAFT
```

Required:

```text
timeout / connection loss / ambiguous response
→ NSL UNKNOWN_COMMIT_STATE
→ AE RECONCILIATION_REQUIRED
→ EOS authoritative operation query
→ determine COMMITTED / NOT_COMMITTED / still UNKNOWN
```

No blind WRITE retry.

---

# 73. Post-Write Verification Query

EOS SHALL provide a read-only canonical query suitable for NSL
`PostWriteVerificationPort`.

Logical operation:

```text
FINANCE.GET_VOUCHER_DRAFT
```

Input:

```text
tenant_id
voucher_ref
business_operation_id
```

Output includes enough stable state to verify the committed result.

Verification never mutates the Voucher.

---

# 74. COMMITTED + Verification Failure

If:

```text
CommitState = COMMITTED
VerificationStatus = FAILED or UNKNOWN
```

then:

```text
Voucher remains committed
no CREATE retry
verification/reconciliation path only
```

This is an explicit P8 acceptance invariant.

---

# 75. BUSINESS_FORMAL Proof in EOS Command

For Golden A:

```text
business_approval_proof_ref = null
```

is allowed if Draft policy does not require formal business approval.

When later EOS policy requires formal approval:

```text
business_approval_proof_ref
```

must reference an EOS-owned immutable final proof bound to:

```text
BusinessOperationId
PayloadHash
WriteIntentHash or protected operation fingerprint
ApprovalInstance
final stage decisions
```

NSL ApprovalEvidence does not replace it.

---

# 76. P8 Contract Package Layout

Recommended:

```text
docs/transition/P8/contracts/

  nsl/
    p8-nsl-write-approval-envelope-v1.schema.json
    p8-nsl-approval-event-v1.schema.json
    p8-nsl-approval-evidence-envelope-v1.schema.json
    p8-nsl-approval-resume-v1.schema.json

  wc/
    p8-approval-work-item-v2.schema.json
    p8-approval-decision-v1.schema.json
    p8-delegation-lineage-v1.schema.json
    p8-delegation-policy-v1.schema.json

  eos/
    eos-org-unit-v1.schema.json
    eos-position-v1.schema.json
    eos-position-assignment-v1.schema.json
    eos-create-voucher-draft-command-v1.schema.json
    eos-create-voucher-draft-result-v1.schema.json
    eos-business-operation-status-v1.schema.json

  ui/
    p8-human-gate-view-v1.schema.json
```

Exact filenames may follow repository conventions.

---

# 77. API Boundary Summary

Recommended service interactions:

```text
AE → WC
create/get NSL_WRITE ApprovalWorkItem

AE-WEB / IA → WC
list pending HumanGate
submit decision

WC → OA
fresh approval:decide authorization

WC → AE
NSL_APPROVAL_DECIDED event

WC → EOS
organization resolution request
(optional depending implementation direction)

EOS → WC
create BUSINESS_FORMAL ApprovalWorkItem

WC → EOS
BUSINESS_FORMAL decision event

AE / NSL WriteExecutionPort → EOS
FINANCE.CREATE_VOUCHER_DRAFT

AE / reconciliation → EOS
BusinessOperation status query

NSL PostWriteVerificationPort → EOS
FINANCE.GET_VOUCHER_DRAFT
```

No cross-service DB access.

---

# 78. Service Trust

All internal calls SHALL preserve existing service-trust rules.

Minimum:

```text
authenticated service identity
exact audience
service:call
tenant lineage
correlation lineage
```

Business scopes are additional controls, not substitutes for service trust.

---

# 79. Database Ownership

### AE

Owns:

```text
AgentExecution
RuntimeJob
NSL execution binding
NSL integration persistence
WaitRegistration
external event inbox
resume lineage
```

### WC

Owns:

```text
WorkItem
Delegation lineage
Routing / Assignment / Claim
ApprovalWorkItem
ApprovalDecision
WorkResult
work/approval outbox
```

### OA

Owns:

```text
Principal
RoleBinding
Effective Authorization
authorization evidence
```

### EOS

Owns:

```text
Organization
Project
Account
Voucher
BusinessOperation
Idempotency acceptance
Formal Approval
Business transaction outbox
```

NSL source remains in its independent repository.

---

# 80. Suggested Database Evolution

Exact migration numbers SHALL be allocated from current heads.

Logical additions:

### AE

```text
generalize wait_type to include NSL_APPROVAL
generalize external_ref to string identity
add resume_contract_ref if needed
persist NSL v0.2 approval/checkpoint integration references
```

### WC

```text
delegation lineage
delegation policy snapshot/ref
approval work item
approval decision
approval event outbox
```

### EOS

```text
service baseline
organization
project/account minimum master
business operation/idempotency
voucher draft
business approval
transactional outbox
```

Database names:

```text
nex_eos_dev
nex_eos_test
```

---

# 81. P8 Golden A Canonical Flow

```text
User
  ↓
IA Prompt
  ↓
P6.5 Planning
  ↓
LOCAL_SKILL
  ↓
NSL v0.2
READ / CHECK
  ↓
PreWriteEligibility
  ↓
WriteIntent
  ↓
Checkpoint persisted
  ↓
ApprovalRequest
  ↓
AE WaitRegistration(NSL_APPROVAL)
  ↓
WC NSL_WRITE ApprovalWorkItem
  ↓
IA HumanGate
  ↓
Human APPROVE
  ↓
fresh OA approval:decide
  ↓
immutable ApprovalDecision
  ↓
Platform ApprovalEvidence
  ↓
NSL_APPROVAL_DECIDED
  ↓
AE RESUME_EXECUTION
  ↓
same NSLExecutionId
same BusinessOperationId
  ↓
NSL ApprovalEvidenceValidator
  ↓
WriteGuard
  ↓
Idempotency
  ↓
durable WRITE_REQUESTED
  ↓
fresh EOS/OA finance:voucher-draft:create
  ↓
EOS CREATE_VOUCHER_DRAFT
  ↓
COMMITTED
  ↓
FINANCE.GET_VOUCHER_DRAFT
  ↓
VERIFIED
  ↓
NSL ExecutionResult
  ↓
AgentResult
```

---

# 82. Golden A Expected Identity Chain

The protected test SHALL trace:

```text
tenant_id
correlation_id

AgentExecutionId
ExecutableStepId

NSLExecutionId
BusinessOperationId

ApprovalRequestId
ApprovalWorkItemId
ApprovalDecision event id

IdempotencyKey
PayloadHash
WriteIntentHash

EOS BusinessOperation ref
VoucherRef
BusinessTransactionRef

RuntimeJobId
WaitId
Resume event id
```

All identities remain distinct unless explicitly defined as a naming projection.

---

# 83. Golden A Exactly-Once Business Mutation

Required assertion:

```text
Voucher Draft business mutation count = 1
```

under:

```text
duplicate approval event
duplicate RESUME_EXECUTION attempt
AE worker restart
EOS response lost after commit
result/publication retry
```

A retry may re-read or reconcile.

It may not produce another Voucher Draft.

---

# 84. Delegation Guard Protected Tests

At minimum:

```text
DG-01 depth 1 creation PASS
DG-02 depth 10 current WorkItem may execute
DG-03 depth 10 → child creation DENIED
DG-04 claim does not increase depth
DG-05 max children 5 → sixth child DENIED
DG-06 root descendants 50 → next child DENIED
DG-07 A → B → A cycle DENIED at claim
DG-08 stale parent Claim cannot delegate
DG-09 expired Claim cannot delegate
DG-10 concurrent child creation cannot oversubscribe budget
DG-11 current work:delegate revoked → no child
DG-12 no guard failure creates child AgentExecution
```

---

# 85. Approval Protected Tests

At minimum:

```text
AP-01 checkpoint saved before publish
AP-02 WaitRegistration before WC human task availability
AP-03 duplicate ApprovalRequestId idempotent
AP-04 same ID / different hash conflict
AP-05 inactive approver DENIED
AP-06 missing approval:decide DENIED
AP-07 target mismatch DENIED
AP-08 OA unavailable fail closed
AP-09 APPROVE produces one immutable decision
AP-10 duplicate APPROVE is idempotent
AP-11 APPROVE then REJECT conflict
AP-12 duplicate event creates one RESUME_EXECUTION
AP-13 approval hash mismatch blocks NSL resume
AP-14 payload hash mismatch blocks NSL resume
AP-15 expired approval requires reapproval
AP-16 reject never reaches EOS WRITE
```

---

# 86. EOS Protected Tests

At minimum:

```text
EOS-01 CREATE_VOUCHER_DRAFT success
EOS-02 invalid ProjectRef denied
EOS-03 inactive AccountRef denied
EOS-04 unbalanced lines denied
EOS-05 missing current finance:voucher-draft:create denied
EOS-06 OA unavailable fail closed
EOS-07 same key + same payload returns same result
EOS-08 same key + different payload conflict
EOS-09 payload hash mismatch zero mutation
EOS-10 response loss after commit reconciles to same VoucherRef
EOS-11 UNKNOWN_COMMIT_STATE never blind retries
EOS-12 transaction + outbox atomic
EOS-13 verification read is side-effect free
EOS-14 COMMITTED + verification failure does not recreate Voucher
EOS-15 cross-tenant refs denied
```

---

# 87. Approval Domain Tests

Required:

```text
AD-01 NSL_WRITE cannot satisfy BUSINESS_FORMAL
AD-02 BUSINESS_FORMAL cannot satisfy NSL_WRITE
AD-03 AGENT_FORMAL cannot satisfy NSL_WRITE
AD-04 HumanGateView preserves domain
AD-05 EOS multi-stage decisions are distinct from one NSL ApprovalRequest
AD-06 one IA inbox may contain multiple domains without state collision
```

---

# 88. NSL Release Admission Tests

Required actual wheel tests:

```text
RA-01 distribution exact
RA-02 package version admitted as v0.2
RA-03 source revision exact
RA-04 source tree exact
RA-05 wheel SHA256 exact
RA-06 RECORD integrity
RA-07 public API import
RA-08 Python requirement
RA-09 dependency compatibility
RA-10 installed package origin exact
RA-11 v0.2 Approval/WRITE public symbols available
RA-12 wrong/stale wheel fails closed
```

---

# 89. Quality Gates

## NSL repository

Keep its own certified gate:

```text
Statement >= 99%
Branch    >= 98%
```

## Platform repository

P8 required minimum:

```text
Statement >= 96%
Branch    >= 94%
```

No threshold weakening is authorized.

---

# 90. P8-CA01 Non-Goals

This closure does not require:

```text
full ERP
Ledger posting
Project P/L
Procurement
Accounting close
Email approval
Mobile approval
ActingAuthority implementation
Bulk WRITE
multiple NSL WRITE nodes
WRITE inside FOREACH
Kafka
EOS microservice decomposition
```

Those are later controlled slices.

---

# 91. Controlled Amendment Rule

P8-CA01 extends transition contracts only.

Do not modify Frozen Platform/Agent/NSL documents.

If implementation finds that an actual Frozen invariant must change:

```text
Issue
→ source evidence
→ impact analysis
→ separate controlled amendment
→ contract tests
→ only then implementation
```

---

# 92. Recommended P8 Implementation Order After CA01

Once CA01 closes:

```text
P8.1
NSL v0.2 Release Admission
+ NSL_V02 backend
+ compatibility smoke

P8.2
NeX-EOS Foundation
+ nex_eos_dev / nex_eos_test
+ Organization / Project / Account / Voucher minimum

P8.2A
WC Delegation Guard

P8.3
WC ApprovalWorkItem
+ IA HumanGate
+ OA approval authority
+ Organization resolution

P8.4
NSL Approval Wait / Resume integration

P8.5
Governed WRITE → EOS

P8.6
Golden A Voucher Draft

P8.7
BUSINESS_FORMAL / multi-stage / dual approval

P8.8
UNKNOWN_COMMIT_STATE / Verification / fault closure

Full Gate
```

P8.2 and P8.2A may proceed in parallel after their contracts are fixed.

---

# 93. P8 SRS Entry Baseline

After CA01 approval, the P8 SRS SHALL treat these as fixed:

```text
NSL v0.2 independent artifact boundary
NSL v0.2 exact wheel admission
NSL_V02_IN_PROCESS
NSL execution_id == Platform nsl_execution_id mapping
BusinessOperationId stability
protected exact ApprovalRequest persistence
wait-before-human-task publication
fresh approval:decide authority
Platform evidence vs NSL evidence separation
typed NSL_APPROVAL resume source
WC ApprovalWorkItem ownership
BUSINESS_FORMAL distinct domain
EOS business approval ownership
IA unified-but-domain-safe inbox
Delegation Guard policy and ownership
current parent Claim for nested delegation
EOS Organization ownership
PART_LEAD→TEAM_LEAD→GROUP_LEAD→CEO→CHAIRMAN ladder
FINANCE.CREATE_VOUCHER_DRAFT first WRITE
fresh EOS command authorization
EOS idempotency / outbox / reconciliation
no blind retry after UNKNOWN_COMMIT_STATE
```

---

# 94. CA01 Closure Checklist

P8-CA01 is closed when the team accepts:

```text
[ ] actual NSL v0.2 wheel admission fields
[ ] package version / source revision policy
[ ] NSL_V02 backend profile
[ ] execution_id ↔ nsl_execution_id mapping
[ ] P8 Approval publication envelope
[ ] exact protected request rule
[ ] WaitRegistration NSL_APPROVAL extension
[ ] NSL approval event / resume payload
[ ] ApprovalEvidence two-layer model
[ ] fresh OA approval:decide rule
[ ] WC ApprovalWorkItem runtime ownership
[ ] BUSINESS_FORMAL domain extension
[ ] EOS ApprovalPolicy/Instance/Stage ownership
[ ] HumanGateView BUSINESS_FORMAL projection
[ ] delegation depth = 10 initial policy
[ ] max children = 5 initial policy
[ ] max descendants = 50 initial policy
[ ] nested delegation current Claim requirement
[ ] claim-time cycle detection
[ ] EOS Organization model ownership
[ ] PART_LEAD → TEAM_LEAD → GROUP_LEAD → CEO → CHAIRMAN
[ ] Golden A Voucher Draft command contract
[ ] fresh finance:voucher-draft:create authority
[ ] EOS idempotency semantics
[ ] EOS reconciliation query
[ ] EOS verification query
[ ] no blind retry invariants
```

---

# 95. Exit State

After closure:

```text
P8 Pre-Architecture Decision = ACCEPTED
P8 Source Audit              = COMPLETE
P8-CA01                      = CLOSED

P8 SRS ENTRY                 = AUTHORIZED
```

No production feature is claimed implemented merely by closing this document.

---

# 96. Final Architecture Position

P8 resolves into five cooperating authorities:

```text
IA / AE
────────────────────────
Interaction
AgentExecution
RuntimeJob
Wait / Resume
NSL integration


WC
────────────────────────
WorkItem
Claim
Delegation Guard
ApprovalWorkItem
Human task lifecycle


OA
────────────────────────
Principal
RoleBinding
Current authorization


NSL v0.2
────────────────────────
Deterministic Skill Runtime
Approval binding
WriteIntent
Idempotency
WriteGuard
Commit / Verification
Replay safety


EOS
────────────────────────
Organization
Project / Account
Formal Business Approval
Voucher / Business Transaction
Authoritative business state
```

The P8 safety chain is:

```text
LLM Plan Candidate
        ↓
Deterministic PlanValidation
        ↓
NSL deterministic validation
        ↓
exact Approval binding
        ↓
current human authority
        ↓
WriteGuard
        ↓
durable WRITE_REQUESTED
        ↓
current EOS business authority
        ↓
authoritative business transaction
        ↓
CommitState
        ↓
Verification
```

Final invariant:

> **No natural-language decision, Agent delegation, human approval, retry, or transport success may independently authorize an Enterprise OS mutation. The mutation occurs only when every required deterministic control is simultaneously valid.**
