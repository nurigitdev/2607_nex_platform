# NeX Platform v2.1
# Architecture Consistency Closure & Unified Change Ledger v1.0

**상태:** FROZEN CHANGE BASELINE — CONTROLLED AMENDMENT REQUIRED  
**목적:** NeX Platform v2.0을 Frozen Agent v2.1 / NSL v0.2 기준으로 v2.1에 Re-baseline하기 위한 최종 Architecture Decision 및 변경 원장  
**근거:** PASS 0~6 + Architecture Decision Pack v1.0

---

# 1. Authority Hierarchy

## 1.1 Frozen Semantic Authority

```text
AUTH-01 NeX Agent v2.1 Final Frozen
AUTH-02 NSL v0.2 Final Frozen
AUTH-03 NeX Agent v2.1 ↔ NSL v0.2 Integration Contract v1.0
AUTH-04 NeX Platform v2.1 Architecture Decision Pack v1.0
```

## 1.2 Re-baseline Target

```text
NeX Platform v2.0 Design / Contract Set
→ NeX Platform v2.1 Controlled Amendment
```

## 1.3 Conflict Rule

```text
Platform v2.0 stale Agent/NSL assumption
→ Frozen Agent/NSL wins

Platform placement/ownership open question
→ ADR Pack v1.0 decision wins

Detailed document conflicts with Closure
→ this Closure / referenced ADR wins
```

---

# 2. Final Architecture Decisions

| ADR | Final Decision |
|---|---|
| ADR-P21-AGENT-ID-01 | Agent Identity/Profile SoR = **NeX-AE Agent Registry** |
| ADR-P21-AGENT-TYPE-01 | WC = **AGENT + agent_type(CA/PA/EA)** |
| ADR-P21-TENANT-01 | `TenantId` = explicit required identity; single-tenant도 configured fixed value |
| ADR-P21-PACKAGE-01 | NSP runtime resolver/verifier = **AE Skill Artifact Gateway** |
| ADR-P21-APPROVAL-01 | **WC Human Workflow + EOS Business Approval Hybrid** |
| ADR-P21-SCHED-01 | Schedule SoR/Engine = **WC Recurring Work / Schedule capability** |

---

# 3. Target v2.1 Responsibility Map

```text
NeX-AE-WEB
= UI / Workspace / Notification surface

IA
= user-facing Agent actor

NeX-AE-API
= Agent Registry + Unified Agent Runtime
  + Agent↔NSL Integration Layer
  + Skill Artifact Gateway

NeX-WC
= Enterprise Work SoR
  + Routing / Claim / Assignment
  + ApprovalWorkItem
  + Recurring Work / Schedule

NeX-OA
= Authentication / Principal / RoleBinding / EAC / PDP
  + current approver authorization
  + Tenant security context

NeX-AG
= PAP / Governance / Kill-switch
  + Agent/PA/EA-Trust governance
  + Skill/NSP/Publisher/Key governance

NeX-CX
= Context / Evidence Retrieval

NeX-MO
= Model Serving / deterministic model routing

NSL v0.2
= deterministic atomic Skill execution
  + NSL WRITE Approval semantics
  + actual WRITE IdempotencyKey
  + Commit / Verification evidence

Enterprise OS
= Business Transaction SoR
  + Business Formal Approval SoR where domain requires
  + Canonical Business API

NeX-WA
= Work Asset / Post-work Activity / Reporting
  NOT Scheduler
```

---

# 4. Change Package Register

| ID | Title | Status | Severity |
|---|---|---|---|
| PLAT-CP01 | Agent Runtime Authority & Execution Re-baseline | **FROZEN / TO AMEND** | Blocker |
| PLAT-CP02 | Agent Identity / PA / WC Routing & Claim Extension | **FROZEN / TO AMEND** | Blocker |
| PLAT-CP03 | NSL Runtime / WRITE / Artifact Trust Re-baseline | **FROZEN / TO AMEND** | Blocker |
| PLAT-CP04 | Approval Architecture / Human Workflow Re-baseline | **FROZEN / TO AMEND** | Blocker |
| PLAT-CP05 | Schedule / Recurring Work Platform Contract | **FROZEN / NEW CAPABILITY** | High |
| PLAT-CP06 | Security / Tenant / RuntimePolicy Re-baseline | **FROZEN / TO AMEND** | High |
| PLAT-CP07 | Governance Re-baseline | **FROZEN / TO AMEND** | High |
| PLAT-CP08 | AE-WEB / IA / Notification & Approval UX | **FROZEN / TO AMEND** | Medium |
| PLAT-CP09 | CX Context / Evidence Contract Alignment | **FROZEN / TO AMEND** | Low/Medium |

---

# 5. PLAT-CP01 — Agent Runtime Authority & Execution

## Root Cause

Platform AE is bound to pre-Agent-v2.1 Coworker Runtime.

## Canonical Resolution

```text
AE-API
→ Frozen Agent v2.1 Runtime authority

Agent Type:
IA / CA / PA / EA

Triggers:
IA → PROMPT
CA/PA/EA → CLAIMED_WORKITEM

AgentExecution 1:N RuntimeJob
```

## Required Documents

```text
11 / 12 / 13
29 AE
29A AE-WEB
31 E2E
32 Reliability
00/03/04/05/06 references
```

## Required Contracts

```text
ExecutionTrigger v2.1
AgentExecution v2.1
RuntimeJob v2.1
AE Runtime Facade v2.1
```

## Acceptance

```text
CP01-G01 old 11/12 not normative
CP01-G02 IA/CA/PA/EA represented
CP01-G03 CLAIMED_WORKITEM represented
CP01-G04 AgentExecution 1:N RuntimeJob
CP01-G05 Frozen Wait/Resume/Reconcile semantics used
```

---

# 6. PLAT-CP02 — Agent Identity / PA / WC

## Canonical Resolution

Agent Registry:

```text
Owner = AE-API
```

WC:

```text
assignee_type = HUMAN | AGENT | EXTERNAL_AGENT | SYSTEM
agent_type = CA | PA | EA
```

PA:

```text
Project 1:1 persistent logical identity
project-scoped WorkItem
→ eligible PA
→ atomic claim
→ PA AgentExecution
```

OA keeps security authority; AG keeps governance.

## Required Documents / Contracts

```text
14 / 15 WC
26 OA
29 AE
29A AE-WEB
30 AG
31 E2E

WC WorkItem / RoutingDecision / Claim
AE Agent Registry
OA EAC
```

## Acceptance

```text
CP02-G01 PA registry exists in AE
CP02-G02 one active PA per project
CP02-G03 WC can route/claim PA work
CP02-G04 claim materializes actual assignee
CP02-G05 PA remains non-business-SoR
```

---

# 7. PLAT-CP03 — NSL Runtime / WRITE / Package Trust

## Canonical Resolution

```text
ExecutableStep
→ SkillExecutionRequest
→ AE Skill Artifact Gateway
→ exact Signed NSP
→ PackageTrustEvidence
→ VerifiedSkillArtifact
→ NSL ExecutionRequest
→ NSL Runtime
```

Identity:

```text
Agent/Platform → BusinessOperationId

NSL Runtime:
TenantId + BusinessOperationId + WriteNodeId
→ actual IdempotencyKey
```

EOS receives actual NSL key.

No raw Runtime SignatureVerifier path.

## Required Documents

```text
16 / 17
29
30
31
37 / 38
08
19 / 24 / 26 / 32 references
```

## Acceptance

```text
CP03-G01 BusinessOperationId first-class
CP03-G02 caller does not generate actual NSL key
CP03-G03 Signed NSP used
CP03-G04 VerifiedSkillArtifact Runtime entry
CP03-G05 typed Commit/Verification/Suspension
CP03-G06 no blind retry
CP03-G07 EOS canonical transaction semantics preserved
```

---

# 8. PLAT-CP04 — Approval Architecture / Human Workflow

## Canonical Control Separation

```text
Human Confirmation
!=
Agent FORMAL_APPROVAL
!=
NSL WRITE Approval
!=
OA Step-up
```

## Final Placement

### WC

```text
ApprovalWorkItem
Routing / Assignment
Notification Event
Timeout / Escalation / Delegation
Human Decision Workflow
Decision Event
```

### EOS

```text
Business Formal Approval SoR
when domain transaction requires formal approval
```

### NSL

```text
WriteIntent
ApprovalRequestId
PayloadHash / WriteIntentHash
Approval binding / validation
```

### OA

```text
current approver authorization
```

### AE / IA / AE-WEB

```text
WAIT / Resume
Notification / Presentation
```

## Required Contracts

```text
ApprovalWorkflowProvider
ApprovalWorkItem v1
AgentFormalApprovalRequest/Decision
NSLWriteApprovalRequest/Evidence
EOS BusinessApprovalAdapter
```

## Acceptance

```text
CP04-G01 confirmation cannot satisfy NSL approval
CP04-G02 Agent formal cannot substitute NSL approval
CP04-G03 NSL binding immutable through WC
CP04-G04 OA check at decision
CP04-G05 decision event triggers Resume
CP04-G06 replay/hash mismatch → WRITE=0
CP04-G07 EOS domain approval linked when required
```

---

# 9. PLAT-CP05 — Schedule / Recurring Work

## Final Placement

```text
Owner / SoR = NeX-WC Recurring Work capability
```

PA can manage project schedule policy through WC API.

PA does not hold timer.

WA is excluded.

## Canonical Flow

```text
ScheduleSpec
→ WC Durable Scheduler
→ ScheduleOccurrence
→ Project-scoped WorkItem
→ Eligible PA
→ Atomic Claim
→ CLAIMED_WORKITEM
→ PA AgentExecution
```

## Required New Contracts

```text
ScheduleSpec v1
ScheduleOccurrence v1
ScheduleTarget v1
ScheduleHistory
```

Required fields include:

```text
tenant_id
schedule_id
owner_ref
project_id
target_work_definition
timezone
cron/calendar
enabled
misfire_policy
concurrency_policy
next_run_at
last_run_at
version
```

## Acceptance

```text
CP05-G01 durable across restart
CP05-G02 duplicate occurrence does not duplicate WorkItem
CP05-G03 deterministic misfire
CP05-G04 WorkItem materialized in WC
CP05-G05 PA starts only after claim
CP05-G06 WA remains Work Asset
```

---

# 10. PLAT-CP06 — Security / Tenant / RuntimePolicy

## Final Decision

`tenant_id` is mandatory logical identity.

Initial single-tenant:

```text
configured fixed tenant_id
```

OA EAC v2.1:

```text
tenant_id
authenticated_principal
business_actor
agent_identity_ref
agent_type
role_binding
org_scope
project_scope
capability
risk/auth context
```

OA → NSL:

```text
RuntimePolicyPort adapter
```

## Acceptance

```text
CP06-G01 Tenant explicit
CP06-G02 Tenant != Org/Project
CP06-G03 PA authority project bounded
CP06-G04 resume current reauthorization
CP06-G05 OA PolicyDecision maps to NSL
```

---

# 11. PLAT-CP07 — Governance

## Canonical Extension

AG asset vocabulary represents:

```text
AGENT_PROFILE
TRUST_PROFILE
TRUST_EVALUATOR
SKILL
NSP_PACKAGE
PUBLISHER
SIGNING_KEY
MODEL
PROMPT
POLICY
```

AG governs:

```text
certify / suspend / revoke / kill-switch
```

but runtime PackageTrustEvidence is produced by Skill Artifact Gateway/Verifier and consumed by NSL.

## Acceptance

```text
CP07-G01 PA governable
CP07-G02 EA-Trust governable
CP07-G03 NSP exact package/hash governable
CP07-G04 publisher/key governance supported
CP07-G05 AG remains PAP, not trust evidence SoR
```

---

# 12. PLAT-CP08 — AE-WEB / IA / Notification

## Canonical Mapping

```text
AE-WEB = UI
IA = Agent Type
```

```text
AE-WEB user action
→ AE-API
→ IA PROMPT trigger
```

Human Gate UX:

```text
approval_domain:
AGENT_FORMAL | NSL_WRITE

approval_provider_type
approval_target_ref
```

Notification remains existing AE projection; no separate Notification Service required.

## Acceptance

```text
CP08-G01 AE-WEB != IA
CP08-G02 IA prompt flow explicit
CP08-G03 NSL approval UI supported
CP08-G04 approval provider agnostic
CP08-G05 PA project view supported
```

---

# 13. PLAT-CP09 — CX Context / Evidence

## Canonical Mapping

```text
CX AEContext / EvidenceBundle
→ Agent Context Builder input
→ AgentContext
```

Do not equate CX object with AgentContext.

Tenant binding:

```text
CX SecurityEnvelope / RetrievalRequest
must receive explicit tenant binding
```

Reuse existing project_scope for PA.

## Acceptance

```text
CP09-G01 no context object ownership confusion
CP09-G02 permission filtering OA-derived
CP09-G03 tenant binding explicit
CP09-G04 no PA-specific evidence SoR
```

---

# 14. Preserved Architecture

The following MUST NOT be unintentionally redesigned.

```text
PRESERVE-01 WC Pool / Claim / Lease
PRESERVE-02 EOS Business Transaction SoR
PRESERVE-03 EOS 3-state Commit / Reconciliation
PRESERVE-04 OA Principal != Business Actor / deterministic PDP
PRESERVE-05 CX Retrieval / Evidence Bundle
PRESERVE-06 MO Serving / Routing
PRESERVE-07 JobQueue / Worker / Recovery foundation
PRESERVE-08 WA = Work Asset
PRESERVE-09 AG PAP != OA PDP
```

---

# 15. Superseded / Re-baseline Status

Platform v2.1 documentation must mark:

```text
11 / 12 / 13
→ Historical Agent v2.0 baseline
→ Superseded by NeX Agent v2.1

16 / 17
→ Historical Platform-embedded NSL baseline
→ Superseded by NSL v0.2 Final Frozen

18
→ Human Gate v2.0
→ Re-baseline to CP04

29 / 29A / 30 / 31 / 37 / 38
→ direct v2.1 amendment required
```

Old docs may remain for migration history but not competing normative authority.

---

# 16. Controlled Amendment Order

Recommended sequence:

```text
Phase A — Authority / Core Runtime
1. update 00/03/04/05/06 authority/references
2. supersede 11/12/13 old Agent baseline
3. PLAT-CP01 AE Runtime

Phase B — Agent Identity / Work / Security
4. PLAT-CP02 AE Agent Registry + WC PA support
5. PLAT-CP06 OA Tenant/Authority

Phase C — NSL Runtime
6. supersede/rebaseline 16/17
7. PLAT-CP03 NSL Artifact/WRITE integration
8. EOS/OA adapter changes

Phase D — Approval
9. PLAT-CP04 WC ApprovalWorkItem + EOS adapter
10. 18 / 29 / 29A / 31 / 37 / 38 update

Phase E — Governance / UX / Context
11. PLAT-CP07 AG
12. PLAT-CP08 AE-WEB
13. PLAT-CP09 CX

Phase F — Schedule
14. PLAT-CP05 WC Recurring Work / Schedule
15. Golden recurring-work scenario

Phase G — Integrated Baseline
16. Master Architecture / SRS / ADR / API/Event Contract update
17. Cross-document consistency review
18. Platform-Agent-NSL E2E validation
```

---

# 17. Final Closure Gate

This Change Ledger becomes CLOSED only after document amendment and re-review.

```text
G-01 PLAT-CP01~09 applied
G-02 six ADR decisions reflected in all impacted docs/contracts
G-03 Frozen Agent v2.1 is sole Agent semantic authority
G-04 Frozen NSL v0.2 is sole NSL semantic authority
G-05 PA identity/routing/claim works
G-06 TenantId explicit end-to-end
G-07 Signed NSP / VerifiedSkillArtifact flow works
G-08 NSL approval suspend/resume works via WC workflow
G-09 EOS domain approval remains authoritative where required
G-10 Schedule→WC WorkItem→PA Claim works
G-11 WA remains Work Asset only
G-12 OA/AG/CX/MO responsibility boundaries preserved
G-13 old competing normative contracts removed/superseded
G-14 Cross-document consistency P0=0 / P1=0 / PCG=0
G-15 Integrated Golden/Fault scenarios PASS
```

---

# 18. Status

Current state:

> **NeX Platform v2.1 Architecture Consistency Closure & Unified Change Ledger v1.0 — FROZEN FOR CONTROLLED AMENDMENT**

Not yet:

> Platform v2.1 Document Set CLOSED / FROZEN

The latter is declared only after all affected Platform documents/contracts are amended and independently re-reviewed.
