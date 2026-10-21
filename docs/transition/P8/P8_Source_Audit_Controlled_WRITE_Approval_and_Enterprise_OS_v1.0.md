# P8 Source Audit — Controlled WRITE, Approval, and Enterprise OS v1.0

**Status:** SOURCE AUDIT COMPLETE / CONTRACT CLOSURE REQUIRED BEFORE FINAL SRS  
**Phase:** P8 — Controlled WRITE / Approval / Enterprise OS  
**Predecessor:** P8 Pre-Architecture Decision v1.0 / P7 Final Contract Freeze  
**Platform Repository:** `nurigitdev/2607_nex_platform`  
**Platform Baseline Commit:** `ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a`  
**Platform Baseline Tree:** `c0901e9e2af266b400adc07dddd815c77fae2ae1`  
**NSL Repository:** `nurigitdev/2608_nsl`  
**NSL v0.2 As-Built Branch:** `master`  
**NSL v0.2 As-Built Commit:** `5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6`  
**NSL v0.2 As-Built Tree:** `71dbea8cca563867b12acd07462a2dcd42d9a8ac`  
**NSL Release-Certification Commit Message:** `Slice 0069: certify performance and v0.2 release`  
**Date:** 2026-10-21

---

## 1. Purpose

This Source Audit verifies the actual source state that P8 will build upon.

P8 is no longer starting from:

```text
NSL v0.2 = design target to be implemented
```

The actual state is now:

```text
NSL v0.2 Frozen Architecture
        ↓
implemented in independent NSL repository
        ↓
Controlled WRITE source complete
        ↓
automated certification complete
        ↓
wheel release reported complete
        ↓
P8 Platform admission / integration remains
```

Therefore the P8 implementation problem has materially changed.

The primary P8 task is now:

```text
NSL v0.2 As-Built
        +
P7 Platform As-Built
        +
new NeX-EOS
        +
Approval / Human Gate integration
        +
Delegation Guard
        ↓
Controlled Business WRITE Golden A
```

This audit distinguishes:

```text
Verified As-Built Fact
Pre-Architecture Decision
Expected P8 Implementation Gap
Contract Closure Gap
Release / Governance Hygiene Gap
```

An expected missing P8 feature is not automatically classified as a defect.

---

## 2. Governing Baselines

### 2.1 Platform

The P7 final handoff source baseline is:

```text
repository = nurigitdev/2607_nex_platform
branch     = transition/p4-agent-runtime-foundation
commit     = ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a
tree       = c0901e9e2af266b400adc07dddd815c77fae2ae1
```

P7 declares:

```text
P7 CLOSED
P7-CA02 CLOSED
P7-CA02A VERIFIED
P7-CA02B CLOSED
P8 ENTRY AUTHORIZED
```

P8 SHALL extend this baseline additively.

### 2.2 NSL v0.2 Frozen Architecture Authority

The actual NSL repository contains the five Frozen authority documents used for
the v0.2 implementation:

```text
00_0_NSL_v0.2_Architecture_Delta_Decision_Record_v1.0_FROZEN.docx
00_1_NSL_v0.2_Batch_A_Execution_Contract_Alignment_Decision_Record_v1.0_FROZEN.docx
00_2_NSL_v0.2_Batch_B_Compiler_Architecture_Alignment_Decision_Record_v1.0_FROZEN.docx
00_3_NSL_v0.2_Batch_C_Runtime_Architecture_Alignment_Decision_Record_v1.0_FROZEN.docx
00_4_NSL_v0.2_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0_FROZEN.docx
```

Their SHA-256 fingerprints are pinned by the NSL readiness baseline:

```text
Architecture Delta
364751bcdc08664e89a9ee8a65ca7060dc6af764af76a8b7d4dd415eacb6bca5

Batch A
c8e0719e729dbf1198604bf9d97ad6def7e0da88817c9a5a5b24ac783977a4ee

Batch B
c15d5aef84e12758dc24e251c523ca977f7b72523ff77ec502aaacd26ddda720

Batch C
13c94e77318385500c955c8ab60fdea1d92730cfec645cd6cde5a1eb3e4197b4

Architecture Consistency Closure
88dd3ae9eec62d93170ad8a605aab14ea4d6b86803a661e1be2204e8cee7401d
```

These documents remain architecture authority for P8 integration.

---

## 3. NSL v0.2 As-Built Baseline

Observed repository state:

```text
repository     = nurigitdev/2608_nsl
default branch = master
master HEAD    = 5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6
tree           = 71dbea8cca563867b12acd07462a2dcd42d9a8ac
```

Latest source commit:

```text
Slice 0069: certify performance and v0.2 release
```

The repository also contains a `main` branch, but it is materially behind the
certified v0.2 `master` baseline.

> **P8 SHALL use the certified `master` v0.2 baseline, not infer equivalence from the stale `main` branch.**

---

## 4. NSL v0.2 Implementation Status

The Source Audit confirms that Controlled WRITE is implemented as source code.

Major modules include:

```text
nsl/approval.py
nsl/checkpoints.py
nsl/idempotency.py
nsl/preflight.py
nsl/write_intent.py
nsl/write_execution.py
nsl/verification.py
nsl/write_replay.py
nsl/write_replay_execution.py
nsl/trust.py
nsl/runtime.py
nsl/runtime_models.py
nsl/integration.py
nsl/worker.py
```

P8 disposition changes from:

```text
NEW / IMPLEMENT
```

to:

```text
IMPLEMENTED / ADMIT / INTEGRATE
```

for the deterministic WRITE kernel.

---

## 5. NSL v0.2 Requirement Certification

The current v0.2 traceability baseline records:

```text
baseline_id             = NSL-V0.2-SRS-RB1
requirement count       = 123
requirement fingerprint = 47ef551d51cddddf23a0b9b5745a5630403d333043db0350268245b9a361256b
current slice           = 0069
```

The implementation sequence reaches:

```text
0032  Requirement Baseline
0033  Shared Core Semantic Kernel
0034  Tool Contract Static Model
0035  Tool Contract Identity
0036  IR 1.1 Object Model
0037  IR Codec / Compatibility
0038  Version-aware Lexer
0039  Approval / WRITE Parser AST
0040  Approval Symbol Semantics
0041  Static WRITE Safety
0042  IR 1.1 Lowering
0043  Execution Identity / Context
0044  Checkpoint / Restore
0045  Structured Runtime Result
0046  PreWriteEligibility
0047  Approval Request / Protected Evidence
0048  Durable Approval Suspension
0049  Resume / Approval Evidence Validation
0050  Write Intent
0051  Idempotency
0052  WriteGuard
0053  Durable WRITE_REQUESTED
0054  Commit / Reconciliation
0055  Signed NSP Trust Evidence
0056  Production WRITE Trust
0057  Post-write Verification
0058  Verification Audit
0059  Replay Evidence
0060  No-live-WRITE Replay
0061  Voucher Validation
0062  Voucher Approval
0063  Voucher Write E2E
0064  Project Validation
0065  Project Controlled WRITE E2E
0066  CLI Run / Resume
0067  Trust Diagnostics
0068  Architecture / Backward Compatibility Certification
0069  Performance / Negative Acceptance / Release Certification
```

This is strong evidence that P8 shall not duplicate NSL v0.2 semantics inside
the Platform repository.

---

## 6. NSL v0.2 Quality Gate

The current NSL source defines:

```text
Statement Coverage threshold = 99%
Branch Coverage threshold    = 98%
```

The latest `master` commit has a successful GitHub Actions run of the
authoritative NSL quality command.

The quality command includes:

```text
v0.1 traceability
v0.2 traceability
v0.2 readiness
extension traceability
pytest regression
statement / branch coverage
architecture certification
performance acceptance
SRS certification
v0.2 final certification
```

Therefore:

```text
NSL standalone quality baseline = ACCEPTED
```

P8 SHALL NOT lower the NSL repository quality gate.

Platform P8 quality policy remains:

```text
Statement Coverage >= 96%
Branch Coverage    >= 94%
```

---

## 7. NSL v0.2 Acceptance Surface

The final acceptance baseline contains:

```text
Mandatory v0.2 tests           = 32
Vertical acceptance scenarios  = 2
Backward compatibility cases   = 8
Performance acceptance cases   = 6
Negative safety cases          = 15
```

Important accepted semantics include:

```text
WRITE requires declaration
WRITE Tool capability validation
Approval before WRITE
Approval↔WRITE bounded linkage
WRITE forbidden in FOREACH
multiple WRITE rejected
FAIL/UNKNOWN blocks WRITE
checkpoint-before-approval-publish
approval request idempotent publish
approval binding validation
approval expiry
stable BusinessOperationId
idempotent duplicate
payload conflict rejection
write-time precondition
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
post-write verification
Signed NSP trust
principal/data policy restoration
no-live-WRITE replay
IR 1.0 compatibility
Language 0.1 → IR 1.0
Language 0.2 → IR 1.1
```

Vertical acceptance includes:

```text
AC-W01 — Voucher
AC-W02 — Project
```

---

## 8. NSL Shared Semantic Types — As-Built

The current NSL source provides:

```text
ExecutionStatus.WAITING_FOR_APPROVAL
ExecutionStatus.RECONCILIATION_REQUIRED

ApprovalStatus
ApprovalDecision
ApprovalEvidenceValidation
PreWriteEligibility

CommitState
  COMMITTED
  NOT_COMMITTED
  UNKNOWN_COMMIT_STATE

VerificationStatus

BusinessOperationId
ApprovalRequestId
IdempotencyKey
PayloadHash
```

P8 Platform SHALL consume these semantics through stable NSL public APIs or
integration contracts.

P8 SHALL NOT create duplicate Platform-owned semantic enums.

---

## 9. Approval Suspend / Resume — NSL As-Built

Implemented source includes:

```text
ApprovalRequest
ApprovalEvidence
ApprovalPort
CheckpointPort
ApprovalSuspensionCoordinator
ResumeToken
ApprovalResumeBindings
ApprovalEvidenceValidator
ApprovalResumeCoordinator
```

Observed ordering:

```text
WriteIntent frozen
        ↓
checkpoint captured
        ↓
checkpoint persisted
        ↓
ApprovalRequest published
        ↓
WAITING_FOR_APPROVAL
```

The Platform therefore does not implement NSL suspension semantics.

Platform supplies durable workflow/adapters around the already-implemented
NSL ports.

---

## 10. Approval Evidence Validation — NSL As-Built

NSL resume validation checks:

```text
BusinessOperationId binding
ApprovalRequestId binding
WriteIntentHash binding
PayloadHash binding
approval validity
approval expiration
evidence verification
```

Platform SHALL NOT duplicate this semantic validation.

Platform owns:

```text
workflow
routing
human decision
current authorization
event delivery
resume scheduling
```

NSL owns:

```text
approval request semantics
WriteIntent binding
resume-time ApprovalEvidence integrity
```

---

## 11. BusinessOperationId — NSL As-Built

`BusinessOperationId` is carried through:

```text
ExecutionRequest
ExecutionIdentity
ExecutionCheckpoint
ApprovalRequest
ApprovalEvidence
ResumeToken
WriteIntent
Idempotency identity
WriteCallRequest
Replay evidence
```

P8 Platform must supply and preserve it across:

```text
Suspend
Human approval wait
Resume
Runtime retry
Re-execution
Reconciliation
```

It remains distinct from:

```text
AgentExecutionId
NSLExecutionId
RuntimeJobId
WorkItemId
ApprovalRequestId
ApprovalWorkItemId
```

---

## 12. Idempotency — NSL As-Built

The implementation explicitly preserves:

```text
IdempotencyKey != PayloadHash
```

and provides:

```text
IdempotencyKeyFactory
IdempotencyIdentity
ProviderIdempotencyEvidence
IdempotencyRetentionValidator
IdempotencyEvidenceRecord
IdempotencyEvidencePort
IdempotencyCoordinator
```

Required semantics:

```text
same key + same payload
→ reuse

same key + different payload
→ conflict
```

EOS SHALL preserve the same semantics at its authoritative command boundary.

---

## 13. Durable WRITE_REQUESTED — NSL As-Built

The implemented WRITE boundary preserves:

```text
WriteIntent
→ Idempotency reservation
→ WriteGuard
→ durable WRITE_REQUESTED
→ provider WRITE
```

P8 must provide production persistence/adapters without changing this ordering.

---

## 14. Commit Outcome — NSL As-Built

NSL implements:

```text
WriteCommitted
WriteNotCommitted
WriteCommitUnknown
```

with typed `CommitState`.

`UNKNOWN_COMMIT_STATE` is not reduced to generic Tool failure.

P8 mapping:

```text
UNKNOWN_COMMIT_STATE
→ RECONCILIATION_REQUIRED
→ authoritative EOS query
→ no blind business retry
```

---

## 15. Post-Write Verification — NSL As-Built

NSL provides:

```text
PostWriteVerificationPort
PostWriteVerifier
VerificationRequest
VerificationObservation
VerificationResult
```

Critical invariant:

```text
CommitState = COMMITTED
VerificationStatus = FAILED / UNKNOWN
```

does not become NOT_COMMITTED.

Therefore:

```text
COMMITTED + Verification FAILED
→ no duplicate business WRITE
```

---

## 16. Production Package Trust — NSL As-Built

The source contains:

```text
Signed NSP verification
PackageTrustEvidence
VerifiedSkillArtifact
ExecutionTrustProfile
RuntimePreflightValidator
```

Production WRITE fails closed for missing, invalid, stale, or mismatched trust.

P8 SHALL reuse:

```text
Signed NSP → Verified Package
```

and SHALL NOT introduce a second signing model.

---

## 17. Replay — NSL As-Built

NSL protected WRITE replay preserves:

```text
Approval Evidence
WRITE_REQUESTED
Commit Outcome
Verification Outcome
```

and enforces:

```text
Replay
→ no live approval decision calls
→ no live business WRITE
```

P8 recovery/replay must preserve this distinction.

---

## 18. Framework-Neutral NSL Public API

The current repository exports Controlled WRITE integration through:

```text
nsl/api/__init__.py
```

including:

```text
ApprovalRequest / ApprovalEvidence
ApprovalSuspensionCoordinator
ApprovalResumeCoordinator
CheckpointPort / ResumeCheckpointPort
IdempotencyCoordinator / IdempotencyEvidencePort
WriteIntent / WriteIntentBuilder
WriteGuard
WriteExecutionPort
WriteEvidencePort
WriteExecutionCoordinator
WriteOutcomeCoordinator
PostWriteVerificationPort
RuntimePreflightValidator
VerifiedSkillArtifact
SkillExecutionWorker
RuntimeResultEnvelope
```

This strongly supports the Pre-Architecture decision:

> **NSL remains an independent repository and Platform integrates through a stable adapter boundary.**

---

## 19. NSL Release Identity Audit

The user reports that NSL v0.2 implementation, testing, and wheel release are
complete.

Source-verifiable facts:

```text
v0.2 source implementation      = VERIFIED
v0.2 final certification commit = VERIFIED
v0.2 CI quality run             = PASS
```

However, repository release metadata currently contains a hygiene inconsistency.

At the certified source revision:

```toml
[project]
name = "nex-skill-language"
version = "0.1.0"
```

Also observed:

```text
Git tag v0.1 exists
Git tag v0.2 not observed
GitHub Release v0.2 not observed
README still contains stale v0.1 scope wording
workflow name still says "NSL v0.1 Quality Gate"
CI artifact name still says "nsl-v0.1-quality-evidence-*"
```

This does **not** prove that the released wheel itself has the wrong version.
An external/release-time override may have been used.

But source alone does not prove:

```text
wheel filename
wheel package version
wheel SHA256
wheel source revision
wheel source tree digest
```

Therefore actual wheel identity SHALL be independently verified during P8
Platform admission.

---

## 20. P8 Release Admission Requirement

Before `NSL_V02_IN_PROCESS` is activated, P8 SHALL record:

```text
repository
source_revision
source_tree
package_name
package_version
wheel_filename
wheel_sha256
requires_python
dependency requirements
public API inventory
Platform dependency-lock hash
```

Recommended target:

```text
deployment/locks/nsl-v0.2-wheel.json
```

or a versioned evolution of the current lock format.

The released wheel, not a label, is the admission evidence source.

---

## 21. Release Hygiene Disposition

Recommended NSL release-hygiene closure:

```text
1. align pyproject package version with v0.2 release identity;
2. update README current-scope wording;
3. rename GitHub Actions workflow from v0.1 to a neutral/current NSL gate;
4. rename CI artifact accordingly;
5. create immutable v0.2 tag or equivalent immutable release ref;
6. record release wheel SHA256 and source tree.
```

This is release/governance hygiene, not a runtime redesign.

---

## 22. Platform NSL Admission — Current As-Built

P7 Platform already has reusable wheel admission:

```text
services/_shared/nex_runtime/nsl_package_admission.py
```

It validates:

```text
distribution
package version
Python requirement
source revision
clean tree evidence
wheel filename
wheel SHA256
dependencies
Platform lock digest
public API
installed package origin
installed package version
wheel RECORD integrity
```

> **P8 SHALL extend/reuse this framework, not build a second NSL v0.2 loader.**

---

## 23. Platform NSL Runtime Profile — Current Gap

Current Platform source is still v0.1-specific:

```text
NSL_V01_IN_PROCESS
NSL_V01_PROCESS_ISOLATED
DEFAULT_NSL_V01_BACKEND_PROFILE
```

Current AE NSL bindings validate those v0.1 profiles.

Disposition:

```text
EXTEND
```

Recommended target:

```text
NSL_V02_IN_PROCESS
```

Optional:

```text
NSL_V02_PROCESS_ISOLATED
```

only when justified.

Do not silently reinterpret `NSL_V01_IN_PROCESS` as v0.2.

---

## 24. Platform NSL Binding — Reuse vs Extend

P6/P7 already implemented:

```text
Verified Skill artifact persistence
NSLStepExecutionBinding
NSLExecutionId
BusinessOperationId field
Runtime backend selection
NSL result integration
wheel admission
```

Disposition:

```text
Artifact / execution binding       = REUSE + EXTEND
BusinessOperationId field          = REUSE
NSLExecutionId                     = REUSE
wheel admission                    = REUSE + VERSION
READ result path                   = REUSE
Approval resume integration        = EXTEND
WRITE evidence/result projection   = EXTEND
```

---

## 25. P7 Wait / Resume Source Audit

P7 established durable:

```text
WaitRegistration
External Event Inbox
RESUME_EXECUTION RuntimeJob
deduplication
one satisfied wait
→ at most one semantic resume
```

This architecture is reusable.

But the current concrete source:

```text
services/nex-ae-api/nex_ae_api/work_result_resume.py
```

is specifically bound to WorkResult resume.

It expects:

```text
WORK_RESULT_SUBMITTED
```

and an exact WorkResult resume payload.

Therefore:

```text
P7 wait/resume architecture = REUSE
WorkResultResumeSource      = NOT directly reusable for NSL approval
```

P8 requires a generalized or sibling resume adapter for:

```text
wait_source = NSL_APPROVAL
```

without weakening P7 semantics.

---

## 26. Recommended P8 Resume Architecture

Preferred:

```text
AE Durable Wait / Event / Resume Core
        │
        ├─ WC_WORK_RESULT adapter
        └─ NSL_APPROVAL adapter
```

Avoid:

```text
NSL Approval
→ fake WorkResult event
```

Target:

```text
NSL WAITING_FOR_APPROVAL
→ AE WaitRegistration(NSL_APPROVAL)
→ Approval decision event
→ exact event/wait match
→ one RESUME_EXECUTION
→ NSL ApprovalResumeCoordinator
```

---

## 27. WC Delegation Guard — Current As-Built

Current P7 WC source owns:

```text
WorkItem
RoutingDecision
Assignment
Claim
ClaimGeneration
ClaimExecutionHandoff
WorkResult
Outbox
```

The broader WorkItem model contains `parent_work_item_id`, but the active P7
delegation path does not yet persist a recursive lineage sufficient for
depth/budget enforcement.

Current P7 DelegationSpec does not contain:

```text
root_work_item_id
delegation_depth
max_delegation_depth
delegation_budget
```

No implementation was found for:

```text
hop-limit enforcement
cycle detection
fan-out budget
root descendant budget
```

Disposition:

```text
Delegation Guard = NEW P8 WC capability
```

---

## 28. Delegation Guard Contract Gap

P8 must close semantics for:

```text
root_work_item_id
parent_work_item_id
delegation_depth
max_delegation_depth
max_children_per_work_item
max_descendants_per_root
```

and decide which are:

```text
canonical WorkItem state
DelegationSpec metadata
WC policy state
derived projection
```

The LLM SHALL NOT own or increase these limits.

---

## 29. Delegation Guard Atomicity Requirement

Recommended normative conjunction:

```text
fresh OA work:delegate
AND
parent lineage valid
AND
prospective depth <= max depth
AND
cycle check PASS
AND
child fan-out budget PASS
AND
root descendant budget PASS
→ child WorkItem commit
```

Checks that can race with concurrent child creation SHALL be enforced at the
same durable WC transaction boundary as child admission.

A non-transactional check-then-write design is insufficient.

---

## 30. Delegation Cycle Detection

No canonical materialized Agent ancestry chain exists yet.

Candidate implementations:

```text
A. parent WorkItem traversal + Claim/Assignment lookup
B. materialized ancestor Agent refs
C. root lineage table
D. lineage projection + explicit ancestor rows
```

Selection criteria:

```text
transactional correctness
query cost
auditability
no Agent identity duplication
restart safety
concurrent delegation correctness
```

P8 contract closure must select the canonical shape.

---

## 31. Enterprise OS — Current Platform Source

No production source was found for:

```text
services/nex-eos/
database/nex-eos/
```

Therefore:

```text
NeX-EOS runtime = NEW
```

This is expected. P7 explicitly deferred EOS transactions to P8.

Approved DB names:

```text
nex_eos_dev
nex_eos_test
```

Service-local ownership and no cross-service direct DB access remain mandatory.

---

## 32. EOS Source Authority

Frozen Platform material establishes EOS as authoritative for:

```text
NVT / Project
Formal Approval
Voucher / Expense
Project Financial Ledger
Project P/L
```

and explicitly not authoritative for:

```text
WC WorkItem
Employee identity
RoleBinding
```

EOS uses stable OA identity refs.

This supports:

```text
EOS = Business Organization / Business Transaction / Formal Approval
OA  = Principal / RoleBinding / Current Authorization
WC  = Work / Human Work coordination
```

---

## 33. EOS Initial Physical Topology

Recommended:

```text
services/nex-eos/
database/nex-eos/
contracts/openapi/nex-eos.openapi.yaml
```

Databases:

```text
development = nex_eos_dev
test        = nex_eos_test
```

Production naming shall follow deployment policy rather than being guessed.

---

## 34. EOS Architecture Shape

Frozen requirements support:

```text
modular monolith
+
bounded contexts
```

Initial logical contexts:

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

Later:

```text
ledger
P/L
procurement
period
legacy integration
```

as needed.

---

## 35. EOS Golden A Minimum Scope

Source-backed minimum scope:

```text
Project reference validation
Account reference validation
Voucher Draft aggregate
Canonical Voucher Draft command
idempotency acceptance
expected-version policy where applicable
write-time business preconditions
business commit result
transactional outbox
trace / evidence refs
authoritative verification read
```

First command:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

Full Ledger/P&L is not required for first Golden A.

---

## 36. EOS Voucher Requirements Already Supported by Frozen Source

Frozen EOS requirements already require:

```text
Voucher deterministic lifecycle
ProjectRef
Money / Decimal
idempotent Draft creation
expected-version stale-write protection
Approval / payload binding
no overwrite of posted transaction
UNKNOWN_COMMIT_STATE / reconciliation
trace to WorkItem / AgentExecution / NSL / evidence
```

These are compatible with implemented NSL v0.2 Controlled WRITE.

---

## 37. Organization Model — Current Source

No current production Platform service was found to own:

```text
OrgUnit hierarchy
management reporting line
PART_LEAD / TEAM_LEAD / GROUP_LEAD / CEO / CHAIRMAN chain
effective PositionAssignment
ActingAuthority
```

Disposition:

```text
EOS Organization = NEW P8 bounded context
```

The approved Pre-Architecture ladder is:

```text
PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
```

This is a P8 transition decision, not claimed as a pre-existing Frozen source
contract.

---

## 38. OA / EOS Organization Boundary

Canonical split:

```text
OA
= Principal
+ RoleBinding
+ Tenant
+ Effective Authorization
+ Current PDP Decision

EOS
= Business Organization
+ Reporting Hierarchy
+ Business Position
+ ApprovalPolicy
+ ApprovalInstance / Stage
```

EOS assignments reference stable OA `principal_ref`.

At decision time:

```text
EOS determines intended business approver
OA determines current authority to decide
```

---

## 39. Acting Authority

No production ActingAuthority model was found.

Disposition:

```text
NEW / OPTIONAL INITIAL EXTENSION
```

If introduced:

```text
EOS owns business substitution relation
OA performs current authorization
```

EOS substitution alone never grants security authority.

---

## 40. Approval Platform Contracts — Existing Frozen Assets

Platform contains Frozen machine-readable contracts for:

```text
ApprovalWorkItem
NSLWriteApprovalRequest
ApprovalDecision
ApprovalEvidence
HumanGateView
NSLApprovalResume
Approval protocols
```

P8 Approval is therefore not green-field semantic design.

Implementation must follow these contracts or close a controlled amendment.

---

## 41. ApprovalWorkItem Domain — Current Contract

Current Frozen `ApprovalWorkItem` supports:

```text
approval_domain =
  AGENT_FORMAL
  NSL_WRITE
```

and contains:

```text
agent_execution_id
executable_step_id
nsl_execution_id
business_operation_id
approval_request_id
target_approver_ref
target_role_ref
target_org_scope_ref
target_project_scope_ref
protected_evidence_ref
resume_target_ref
```

This is a strong P8 NSL WRITE Approval foundation.

---

## 42. EOS Formal Approval Contract Gap

Frozen EOS requirements say EOS owns:

```text
ApprovalPolicy
ApprovalInstance
ApprovalStage
ApprovalDecision
ApprovalProof
```

But current WC ApprovalWorkItem does not contain an explicit:

```text
EOS_BUSINESS_FORMAL
```

domain.

This does not automatically require a new enum.

A Frozen `BusinessApprovalAdapter` seam already exists.

P8 must decide:

```text
Option A
EOS Formal Approval remains EOS-owned;
WC carries only human-task projection.

Option B
WC receives a new explicit business-approval workflow domain.

Option C
Reuse AGENT_FORMAL only if normative authority proves semantic equivalence.
```

Option C SHALL NOT be assumed.

This is a contract closure item.

---

## 43. HumanGateView Contract Gap

Current Frozen `HumanGateView` supports:

```text
AGENT_FORMAL
NSL_WRITE
HUMAN_CONFIRMATION
STEP_UP
```

No explicit EOS Formal Business Approval domain exists.

Yet P8 intends one IA-facing approval experience.

P8 must close one of:

```text
1. add EOS business approval domain;
2. define provider-typed projection preserving EOS semantics;
3. prove an existing domain is normatively correct.
```

UI unification SHALL NOT collapse semantics.

---

## 44. Approval Protocol Seams — Existing Frozen Source

Frozen protocols already define:

```text
ApprovalWorkflowProvider
  create_or_get
  submit_decision
  get_status

NSLApprovalResumePublisher
  publish_resume

BusinessApprovalAdapter
  ensure_domain_approval
```

P8 SHOULD implement around these seams before adding another approval
orchestration abstraction.

---

## 45. IA Human Approval — Current Source Gap

Frozen contracts contain HumanGate/AE-WEB concepts, but the current P7 runtime
does not yet implement the complete P8 approval-inbox journey.

Disposition:

```text
IA Approval Inbox = NEW P8 integration/UI capability
```

Initial channel:

```text
IA / AE-WEB
```

Future notification channels are not Golden A requirements.

---

## 46. Multi-Stage Corporate Approval

Implemented NSL v0.2 preserves bounded Approval↔WRITE semantics.

Therefore:

```text
NSL approve != corporate stage engine
```

Do not model:

```text
approve PART_LEAD
approve TEAM_LEAD
approve GROUP_LEAD
approve CEO
approve CHAIRMAN
WRITE
```

Instead:

```text
one NSL ApprovalRequest
        ↓
EOS ApprovalPolicy / ApprovalInstance
        ↓
PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
        ↓
final business approval proof
        ↓
NSL ApprovalEvidence
        ↓
NSL resume
```

Policy may select only required stages.

---

## 47. Approval SoR Matrix

| Concern | Authoritative Owner | P8 Disposition |
|---|---|---|
| Principal identity | OA | REUSE |
| Current approver authorization | OA | REUSE / EXTEND |
| Human work item | WC | NEW Approval runtime |
| Agent formal approval | WC / Agent contract | IMPLEMENT |
| NSL exact WRITE approval binding | NSL | IMPLEMENTED / INTEGRATE |
| Business approval policy | EOS | NEW |
| Business approval instance/stages | EOS | NEW |
| IA approval presentation | AE-WEB / IA | NEW |
| Approval resume scheduling | AE Runtime | EXTEND |
| ApprovalEvidence semantic validation | NSL | IMPLEMENTED / REUSE |

---

## 48. NSL / Platform Responsibility Matrix

| Capability | Actual Current Source | Target Owner | Disposition |
|---|---|---|---|
| READ runtime | NSL v0.2 | NSL | REUSE |
| Compiler / IR 1.1 | NSL v0.2 | NSL | REUSE |
| Approval syntax/static binding | NSL v0.2 | NSL | REUSE |
| WriteIntent | NSL v0.2 | NSL | REUSE |
| Approval suspension semantics | NSL v0.2 | NSL | REUSE |
| Approval evidence validation | NSL v0.2 | NSL | REUSE |
| BusinessOperationId support | NSL + AE field | Platform supplies / NSL consumes | INTEGRATE |
| Actual NSL IdempotencyKey | NSL v0.2 | NSL | REUSE |
| Durable WRITE_REQUESTED | NSL v0.2 | NSL + production port | ADAPTER |
| CommitState | NSL v0.2 | NSL | REUSE |
| VerificationStatus | NSL v0.2 | NSL | REUSE |
| Package trust | NSL v0.2 | NSL / Platform admission | REUSE |
| Approval routing | not NSL | WC/EOS | NEW |
| Human UI | not NSL | IA/AE-WEB | NEW |
| Resume job scheduling | P7 AE | AE | EXTEND |
| Business transaction | absent | EOS | NEW |

---

## 49. WC P8 Capability Matrix

| Capability | P7 Source | P8 Disposition |
|---|---|---|
| WorkItem | IMPLEMENTED | REUSE |
| RoutingDecision | IMPLEMENTED | REUSE |
| Assignment / Claim | IMPLEMENTED | REUSE |
| ClaimGeneration | IMPLEMENTED | REUSE |
| Handoff | IMPLEMENTED | REUSE |
| WorkResult | IMPLEMENTED | REUSE |
| `work:delegate` authorization | IMPLEMENTED | REUSE |
| ApprovalWorkItem runtime | contract only | NEW |
| Delegation depth | absent | NEW |
| Delegation cycle detection | absent | NEW |
| Child fan-out budget | absent | NEW |
| Root descendant budget | absent | NEW |
| NSL Approval decision event | absent | NEW |
| Approval event → AE resume | absent | NEW |

---

## 50. EOS P8 Capability Matrix

| Capability | Existing Source | P8 Disposition |
|---|---|---|
| EOS service | none | NEW |
| `nex_eos_dev` | none | NEW |
| `nex_eos_test` | none | NEW |
| Organization | design requirement only | NEW |
| Position hierarchy | none | NEW |
| Project minimal model | design requirement only | NEW |
| Account minimal model | design requirement only | NEW |
| Voucher Draft | design requirement only | NEW |
| Business approval | design requirement only | NEW |
| Canonical Command API | requirement only | NEW |
| Idempotency persistence | requirement only | NEW |
| Transactional outbox | requirement only | NEW |
| Reconciliation query | requirement only | NEW |
| Verification read API | requirement only | NEW |

---

## 51. Key Positive Audit Findings

```text
P8-SA-PASS-01
NSL v0.2 remains independent repository.

P8-SA-PASS-02
Controlled WRITE core semantics are already implemented.

P8-SA-PASS-03
BusinessOperationId exists in actual NSL runtime.

P8-SA-PASS-04
IdempotencyKey and PayloadHash are separate.

P8-SA-PASS-05
Approval suspend/resume semantics are implemented.

P8-SA-PASS-06
Checkpoint-before-approval-publish is implemented.

P8-SA-PASS-07
WRITE_REQUESTED-before-provider semantics are implemented.

P8-SA-PASS-08
UNKNOWN_COMMIT_STATE is first-class.

P8-SA-PASS-09
CommitState and VerificationStatus are separate.

P8-SA-PASS-10
Production WRITE package trust is implemented.

P8-SA-PASS-11
Replay no-live-WRITE protection is implemented.

P8-SA-PASS-12
P7 durable Wait/Resume architecture is reusable.

P8-SA-PASS-13
Existing Platform wheel admission is reusable.

P8-SA-PASS-14
EOS modular-monolith direction is Frozen-compatible.

P8-SA-PASS-15
EOS business approval and OA identity ownership are source-separated.
```

---

## 52. Contract Closure Findings

### P8-SA-CG-01 — NSL v0.2 Release Identity / Wheel Admission

Need exact:

```text
wheel filename
wheel package version
wheel SHA256
source revision
source tree
```

before Platform activation.

### P8-SA-CG-02 — NSL v0.2 Platform Backend Profile

Current Platform profiles are v0.1-specific.

Need exact new versioned profile/admission mapping.

### P8-SA-CG-03 — NSL Approval → AE Wait/Resume

Need exact:

```text
NSL WAITING_FOR_APPROVAL
→ WaitRegistration
→ Approval event
→ RESUME_EXECUTION
→ NSL resume
```

contract.

### P8-SA-CG-04 — EOS Formal Approval vs WC ApprovalWorkItem

Need exact ownership/projection mapping.

### P8-SA-CG-05 — EOS Formal Approval in HumanGateView

Need IA-safe projection semantics without collapsing approval domains.

### P8-SA-CG-06 — Delegation Guard

Need canonical depth/root/budget/cycle contract.

### P8-SA-CG-07 — EOS Organization

Need minimal:

```text
OrgUnit
Position
PositionAssignment
reporting relation
```

and stable OA Principal refs.

### P8-SA-CG-08 — Golden A EOS Command

Need exact:

```text
FINANCE.CREATE_VOUCHER_DRAFT
request
result
idempotency
commit
reconciliation
verification
```

contracts.

---

## 53. Release Hygiene Findings

These do not require runtime redesign but should be closed before production
admission:

```text
P8-SA-RH-01  pyproject still declares package version 0.1.0.
P8-SA-RH-02  README contains stale v0.1 scope wording.
P8-SA-RH-03  GitHub Actions workflow name still says v0.1.
P8-SA-RH-04  CI artifact name still says v0.1.
P8-SA-RH-05  master is authoritative while main is stale.
P8-SA-RH-06  no v0.2 Git tag was observed.
P8-SA-RH-07  no GitHub Release was observed.
```

Resolve or explicitly accept through release governance.

---

## 54. Repository Governance Observation

NSL `master` is currently not branch-protected and the latest commit is
unsigned.

For P8 cross-repository admission, stronger immutable provenance is
recommended:

```text
source commit
source tree
tag or immutable ref
wheel SHA256
CI run id
certification evidence
Platform lock
```

This is a governance recommendation, not a runtime defect.

---

## 55. Revised P8 Implementation Interpretation

Because NSL v0.2 is already implemented, the earlier conceptual step:

```text
P8.1 — implement NSL v0.2
```

shall become:

```text
P8.1 — NSL v0.2 Release Admission & Platform Integration Acceptance
```

Platform SHALL NOT repeat standalone NSL implementation work.

---

## 56. Recommended Revised P8 Sequence

```text
P8 Source Audit
        ↓
P8-CA01 Contract Closure
        ↓

P8.1
NSL v0.2 Release Admission
+ Platform Backend Profile
+ Integration Acceptance
        │
        ├──────────────────┐
        ▼                  ▼

P8.2              P8.2A
NeX-EOS           WC Delegation Guard
Foundation        Foundation
        │                  │
        └─────────┬────────┘
                  ▼

P8.3
Human Approval Foundation
EOS Organization / ApprovalPolicy
WC ApprovalWorkItem
IA HumanGateView
OA current authorization
                  ↓

P8.4
NSL Approval Suspend / Resume
AE WaitRegistration / Resume
                  ↓

P8.5
Governed WRITE → EOS
                  ↓

P8.6
Golden A — Voucher Draft
                  ↓

P8.7
Dual / Formal Business Approval
                  ↓

P8.8
Fault / Reconciliation Closure
                  ↓

Repository Full Gate
```

Exact numbering may be refined in the Implementation Slice Plan.

---

## 57. Recommended P8-CA01

This audit recommends a source-backed contract closure before finalizing the P8
SRS.

Suggested title:

```text
P8-CA01:
Controlled WRITE / Approval / Delegation / EOS Contract Closure
```

P8-CA01 should resolve architecture/contract ambiguity, not implement product
features.

---

## 58. P8-CA01 Required Decisions

### A. NSL Release Admission

```text
v0.2 wheel identity
package version
source commit/tree
SHA256
public API
NSL_V02_IN_PROCESS profile
Platform lock format
```

### B. NSL Approval Bridge

```text
WAITING_FOR_APPROVAL mapping
WaitRegistration source
Approval event
ResumeJob payload
same NSLExecutionId
same BusinessOperationId
checkpoint version
ApprovalEvidence
```

### C. Approval Domain Mapping

```text
NSL_WRITE
AGENT_FORMAL
EOS Formal Business Approval
HUMAN_CONFIRMATION
STEP_UP
```

### D. HumanGateView

```text
how EOS Formal Approval is represented
without semantic collapse
```

### E. Delegation Guard

```text
root
parent
depth
max depth
fan-out
descendant budget
cycle detection
atomic enforcement
```

### F. EOS Organization

```text
OrgUnit
Position
PositionAssignment
PART_LEAD
TEAM_LEAD
GROUP_LEAD
CEO
CHAIRMAN
OA Principal refs
```

### G. Golden A EOS Contract

```text
Voucher Draft command
idempotency
commit result
reconciliation
verification read
outbox event
```

---

## 59. P8 SRS Input Baseline After CA01

After CA01, the SRS can treat these as fixed:

```text
NSL deterministic WRITE semantics
NSL package trust
BusinessOperationId stability
NSL IdempotencyKey semantics
CommitState / VerificationStatus
P7 AE Runtime
P7 WC Claim authority
P7 Wait/Resume core
OA current authorization
EOS service ownership
Approval domain separation
Delegation Guard ownership
Organization ownership
Golden A business command boundary
```

---

## 60. Quality Baseline for P8

### NSL

Keep repository-native release thresholds:

```text
Statement >= 99%
Branch    >= 98%
```

### Platform

Use approved P8 thresholds:

```text
Statement >= 96%
Branch    >= 94%
```

Protected PostgreSQL/provider/cross-repository E2E tests remain required where
applicable.

---

## 61. P8 Database Baseline

EOS follows environment-specific DB naming:

```text
nex_eos_dev
nex_eos_test
```

Role naming shall follow current Platform repository policy during
implementation rather than being guessed here.

Cross-service direct DB access remains forbidden.

---

## 62. Golden A Source-Backed Target

The first protected business WRITE remains:

```text
Voucher Draft
```

Canonical target:

```text
User Prompt
→ IA Plan
→ LOCAL_SKILL
→ NSL READ / CHECK
→ PreWriteEligibility
→ WriteIntent
→ ApprovalRequest
→ durable NSL Checkpoint
→ WAITING_FOR_APPROVAL
→ WC ApprovalWorkItem
→ IA HumanGate
→ OA-authorized Human Decision
→ RESUME_EXECUTION
→ NSL ApprovalEvidence Validation
→ WriteGuard
→ Idempotency
→ durable WRITE_REQUESTED
→ EOS FINANCE.CREATE_VOUCHER_DRAFT
→ CommitState
→ Post-Write Verification
→ AgentResult / WorkResult
```

---

## 63. Golden A Evidence Requirements

Protected acceptance SHOULD capture:

```text
Platform source revision/tree
NSL source revision/tree
NSL wheel filename/SHA256
NSL installed-package readiness
AE migration head
WC migration head
OA migration head
EOS migration head
actual test DB identities
BusinessOperationId
NSLExecutionId
ApprovalRequestId
ApprovalWorkItemId
IdempotencyKey hash-safe reference
VoucherRef
CommitState
VerificationStatus
authorization decisions
zero duplicate WRITE count
zero owned residue
```

Raw business payloads, credentials, secrets, and private approval content SHALL
not be copied into generic evidence.

---

## 64. Reliability Scenarios Required After Golden A

At minimum:

```text
duplicate RuntimeJob
duplicate approval decision event
approval replay / binding mismatch
approval expiry
package trust failure
current authorization revoked
WriteGuard failure
same idempotency key + different payload
response lost after commit
UNKNOWN_COMMIT_STATE
reconciliation result
COMMITTED + Verification FAILED
publication retry after committed WRITE
```

Expected business mutation count:

```text
0 when admission/control fails before WRITE

1 when WRITE committed even if response/publication/verification later fails
```

---

## 65. Source Audit Verdict

```text
NSL v0.2 Architecture             = FROZEN / SOURCE-BACKED
NSL v0.2 Implementation           = COMPLETE
NSL v0.2 Certification            = PASS
NSL Controlled WRITE Core         = IMPLEMENTED
NSL Approval Suspend/Resume       = IMPLEMENTED
NSL Idempotency                   = IMPLEMENTED
NSL Commit/Reconciliation         = IMPLEMENTED
NSL Verification                  = IMPLEMENTED
NSL Package Trust                 = IMPLEMENTED
NSL Replay Safety                 = IMPLEMENTED

P7 Runtime Foundation             = REUSABLE
P7 WC Claim Authority             = REUSABLE
P7 Wait/Resume Core               = REUSABLE / ADAPTER EXTENSION REQUIRED
Platform NSL v0.2 Profile         = NOT YET IMPLEMENTED
Platform NSL v0.2 Wheel Admission = NOT YET CLOSED
WC Delegation Guard               = NOT IMPLEMENTED
WC Approval Runtime               = NOT IMPLEMENTED
IA Human Approval                 = NOT IMPLEMENTED
EOS Runtime                       = NOT IMPLEMENTED
EOS Organization                  = NOT IMPLEMENTED
EOS Golden A Command              = NOT IMPLEMENTED

Approval cross-domain mapping     = CONTRACT CLOSURE REQUIRED
Delegation Guard exact contract   = CONTRACT CLOSURE REQUIRED
NSL release identity hygiene      = CLOSURE REQUIRED BEFORE ADMISSION
```

---

## 66. P8 Entry Recommendation

P8 may proceed, but the next step should not be an unconstrained final SRS.

Recommended sequence:

```text
P8 Pre-Architecture Decision
        = ACCEPTED

P8 Source Audit
        = COMPLETE

        ↓

P8-CA01
Controlled WRITE / Approval /
Delegation / EOS Contract Closure

        ↓

P8 SRS

        ↓

P8 Implementation Slice Plan

        ↓

Implementation
```

This follows the successful P7 pattern:

```text
architecture
→ source audit
→ contract closure
→ SRS
→ slice implementation
→ protected acceptance
```

---

## 67. Final Source-Audit Position

The most important conclusion is:

> **NSL v0.2 is no longer a P8 implementation target. It is a completed and certified deterministic WRITE runtime that P8 must admit and integrate.**

Platform SHALL avoid duplicating:

```text
ApprovalEvidence validation
WriteIntent hashing
IdempotencyKey derivation
WriteGuard
CommitState
VerificationStatus
Replay safety
Package trust
```

Platform shall focus on:

```text
NSL v0.2 admission
AE integration
WC human workflow
Delegation safety
OA current authorization
IA approval experience
EOS authoritative business state
EOS formal approval
Golden A E2E reliability
```

The central P8 integration rule is:

> **Agent intelligence proposes and coordinates; WC bounds delegated/human work; OA authorizes current actors; NSL deterministically controls side effects; EOS owns authoritative business state.**
