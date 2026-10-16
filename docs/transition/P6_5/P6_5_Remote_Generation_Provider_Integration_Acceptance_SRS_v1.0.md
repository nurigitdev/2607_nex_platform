# P6.5 Remote Generation Provider Integration Acceptance
# Software Requirements Specification v1.0

**Document Status:** PRE-IMPLEMENTATION SRS
**Phase:** P6.5
**Predecessor:** P6 Final As-Built Baseline
**Successor:** P7 WC + CA/PA/EA Background Work
**Date:** 2026-10-16

---

## 1. Purpose

본 SRS는 실제 Remote Generation Provider를 NeX-AE semantic planning path에 연결하여:

```text
Prompt
→ Intent Candidate
→ Context Candidate
→ Plan Candidate
→ deterministic validation
→ deterministic compile
```

의 E2E 동작을 검증하기 위한 요구사항을 정의한다.

P6.5의 목적은 production-grade general LLM orchestration을 완성하는 것이 아니라,
P7 진입 전에 **Non-deterministic Generation과 Deterministic Execution 사이의 경계가 실제 provider 환경에서도 안전하게 유지됨을 증명**하는 것이다.

---

## 2. Normative Baseline

P6.5 SHALL inherit without rename/replacement:

```text
AgentExecution
WorkIntent
AgentContext
CapabilitySnapshot
AgentPlan
PlanValidationResult
ExecutablePlan
ExecutableStep
RuntimeJob
StepResult
AgentResult
```

P6.5 SHALL preserve:

```text
RuntimeJob as AE execution SoR
Timeline as projection, not SoR
ResultDelivery(PENDING) ACK barrier
NSL_V01_IN_PROCESS default
StepResult v1.2 READ semantics
```

---

## 3. System Boundary

Canonical generation access:

```text
NeX-AE
→ internal MO Generation Client
→ NeX-MO /api/v1/generations
→ MO Provider Route / Profile
→ Remote Generation Provider
```

AE SHALL NOT receive or persist remote provider URL or API key.

CX SHALL continue to own grounded retrieval/content-generation semantics.

P6.5 semantic planning SHALL NOT depend on CX grounded generation unless CA01 proves a generic semantically-correct reusable path.

---

## 4. Canonical Planning Flow

```text
IA User Prompt
→ Base Context
→ Intent Candidate Generation
→ Intent Candidate Validation
→ Deterministic Intent Resolution
→ WorkIntent
→ Context Candidate Generation
→ Context Candidate Validation
→ Trusted Context Resolution
→ AgentContext
→ Plan Candidate Generation
→ Plan Candidate Validation
→ AgentPlan
→ PlanValidationResult
→ Deterministic Compiler
→ ExecutablePlan
```

LLM-generated object is never executable.

---

# 5. Functional Requirements

## P65-FR-001 — Live Provider Readiness

System SHALL verify Remote Generation readiness through existing MO mechanisms before required-mode semantic generation.

Required observations:

```text
provider mode = live
generation endpoint configured
expected model available
provider route READY
generation preflight PASS
```

Provider URL/key SHALL NOT appear in AE diagnostics.

---

## P65-FR-002 — Internal MO Generation Client

AE SHALL invoke generation through an internal MO client.

The client SHALL propagate bounded:

```text
request_id
trace_id
provider capability = generation
provider alias
messages
response_format
max_output_tokens
reasoning_mode
```

The client SHALL NOT accept caller-supplied:

```text
provider_url
provider_endpoint
model_path
api_key
```

---

## P65-FR-003 — Exact Prompt Resolution

Every LLM stage SHALL resolve one exact RDBMS Prompt Registry binding/version.

Captured provenance SHALL include:

```text
binding_key
prompt_template_version_id
prompt_content_sha256
rendered_prompt_hash
model_profile
model_ref
input_context_hash
```

No implicit latest.

---

## P65-FR-004 — LLM Stage Purposes

P6.5 SHALL activate at minimum:

```text
intent_resolution
context_candidate_extraction
plan_builder
```

`clarification` and `result_synthesis` MAY remain deferred unless required by acceptance scenarios.

---

## P65-FR-005 — Structured Output

All three P6.5 semantic stages SHALL request structured JSON output.

Preferred MO request:

```json
{
  "provider_capability": "generation",
  "response_format": {"type": "json_object"},
  "stream": false
}
```

Malformed JSON SHALL fail candidate admission.

---

## P65-FR-006 — Intent Candidate

Remote provider SHALL produce an `IntentCandidate`, not canonical WorkIntent.

Candidate SHALL contain only bounded suggestion fields such as:

```text
intent_label
suggested_execution_mode
entity_selectors
parameter_candidates
clarification suggestion
confidence
```

Candidate SHALL NOT authoritatively set Tenant/Principal/Project/Role/Capability version.

---

## P65-FR-007 — Deterministic Intent Resolution

IntentCandidate SHALL pass:

```text
JSON validation
→ candidate schema validation
→ allowed-mode validation
→ authority-field rejection
→ deterministic intent policy
```

Only deterministic resolution SHALL produce canonical `IntentDecision` / `WorkIntent`.

Low confidence SHALL map to an explicit configured directive such as:

```text
CLARIFICATION_REQUIRED
BLOCKED
```

and SHALL NOT silently execute.

---

## P65-FR-008 — Context Candidate

Remote provider SHALL produce `ContextCandidateSet`.

Candidate MAY suggest:

```text
entity candidates
resource selectors
retrieval hints
query terms
parameter candidates
```

Candidate SHALL NOT assert:

```text
verified principal
effective role binding
tenant authority
project authority
data classification authority
permission
```

---

## P65-FR-009 — Trusted Context Resolution

Canonical AgentContext SHALL be created only through trusted deterministic resolution.

```text
ContextCandidateSet
+ authoritative OA/AG/CX sources
→ TrustedContextResolution
→ AgentContext
```

LLM-supplied authority fields SHALL be rejected or ignored according to closed schema rules.

---

## P65-FR-010 — Plan Candidate

Remote provider SHALL produce a `PlanCandidate`, not canonical AgentPlan.

PlanCandidate SHALL use bounded logical step vocabulary.

P6.5 SHALL NOT activate:

```text
DELEGATE_WORK
CLAIMED_WORKITEM
WC work
NSL WRITE
Approval
```

---

## P65-FR-011 — Capability Binding

LLM MAY suggest a capability identifier/alias.

Exact capability version and executable binding SHALL be resolved deterministically from tenant-scoped CapabilitySnapshot.

Unknown or unavailable capability SHALL not be invented or auto-created.

---

## P65-FR-012 — Plan Candidate Bounds

Candidate validation SHALL enforce existing P5 bounds:

```text
max_plan_steps = 12
max_delegation_depth = 0
max_parallel_steps = 1
```

Invalid dependencies, cycles, duplicate logical IDs, missing completion path or unsupported step type SHALL fail admission.

---

## P65-FR-013 — Canonical AgentPlan

Only a validated/bound candidate SHALL be transformed into immutable AgentPlan.

AgentPlan SHALL retain exact provenance to:

```text
WorkIntent
AgentContext
CapabilitySnapshot
Prompt Registry version
Model profile/ref
Candidate hash
```

---

## P65-FR-014 — Existing PlanValidation Reuse

Canonical AgentPlan SHALL pass existing deterministic PlanValidation.

P6.5 SHALL NOT replace PlanValidation with an LLM judge.

Existing statuses remain authoritative:

```text
VALID
REPLAN_REQUIRED
CONTEXT_REFRESH_REQUIRED
CLARIFICATION_REQUIRED
BLOCKED
INVALID_TERMINAL
RETRYABLE_VALIDATION_FAILURE
```

---

## P65-FR-015 — Existing Compiler Reuse

Only `VALID` AgentPlan SHALL reach deterministic Compiler.

Compiler SHALL remain provider/LLM-free.

Compiler SHALL bind exact runtime identities and capability versions.

---

## P65-FR-016 — Rollout Modes

P6.5 SHALL support controlled mode:

```text
disabled
shadow
required
```

### disabled

Existing P5 deterministic semantic path remains authoritative.

### shadow

Remote candidates are generated, validated and compared, but deterministic P5 path retains execution authority.

### required

Remote candidate stages are required. Failure does not silently fall back.

---

## P65-FR-017 — No Hidden Fallback

In `required` mode the following SHALL NOT silently select deterministic fallback:

```text
provider unavailable
timeout
429/5xx exhausted
invalid JSON
schema violation
authority violation
unsupported capability
invalid plan
```

System SHALL emit explicit failure/directive.

---

## P65-FR-018 — Candidate Evidence

System SHALL retain bounded evidence sufficient to reproduce semantic provenance.

At minimum:

```text
stage
execution_id
candidate_id/ref
candidate_hash
prompt version/hash
rendered prompt hash
input context hash
model profile/ref
MO generation id or safe lineage ref
validation outcome
created_at
```

Raw provider endpoint/key/hidden reasoning SHALL NOT be retained.

---

## P65-FR-019 — Candidate Immutability

Persisted candidate/evidence SHALL be immutable or insert-or-verify.

Same candidate identity with different semantic content SHALL fail deterministically.

---

## P65-FR-020 — Technical Retry Separation

MO SHALL own bounded technical provider retry.

AE SHALL own semantic retry/replan.

```text
Provider HTTP retry
!=
Intent re-resolution
!=
Plan replan
```

P6.5 SHALL not conflate these identities.

---

## P65-FR-021 — Idempotency

Technical retry SHALL preserve:

```text
AgentExecutionId
semantic stage identity
prompt version
input context hash
```

A semantic revision SHALL create a new candidate revision/identity.

---

## P65-FR-022 — Prompt Injection Boundary

System/developer prompt segments SHALL remain trusted control text.

User prompt, retrieved evidence and prior model output SHALL remain untrusted data.

Candidate output cannot invoke tool/runtime directly.

---

## P65-FR-023 — Provider Failure Mapping

System SHALL distinguish at least:

```text
PROVIDER_NOT_READY
PROVIDER_TIMEOUT
PROVIDER_RATE_LIMIT
PROVIDER_SERVER_ERROR
PROVIDER_RESPONSE_INVALID
CANDIDATE_JSON_INVALID
CANDIDATE_SCHEMA_INVALID
CANDIDATE_AUTHORITY_VIOLATION
CANDIDATE_CAPABILITY_UNKNOWN
CANDIDATE_PLAN_INVALID
CANDIDATE_LOW_CONFIDENCE
```

---

## P65-FR-024 — Observability

Safe trace SHALL correlate:

```text
InteractionId
AgentExecutionId
SemanticStage
PromptTemplateVersionId
CandidateId/Hash
MO GenerationId
Model Profile/Ref
WorkIntentId
AgentContextId
AgentPlanId
ExecutablePlanId
```

No raw prompt/provider secret in operational log.

---

## P65-FR-025 — Actual Provider Acceptance

P6.5 closure SHALL execute at least one real provider call through:

```text
NEX_MO_PROVIDER_MODE=live
```

A mock provider response SHALL NOT satisfy final acceptance.

---

## P65-FR-026 — Actual PostgreSQL Acceptance

Final Golden Journey SHALL run against actual PostgreSQL and leave zero test residue.

SQLite-only acceptance is insufficient.

---

## P65-FR-027 — P6 Continuity

Preferred final Golden Journey SHALL continue from generated ExecutablePlan into existing P6 path:

```text
ExecutablePlan
→ LOCAL_SKILL
→ RuntimeJob
→ AE Runtime Worker
→ NSL READ
→ StepResult v1.2
→ AgentResult
```

This extension SHALL not modify P6 semantics.

---

# 6. Candidate Contract Requirements

Exact JSON Schema is closed in P6.5-CA01.

## IntentCandidate v1

```text
schema_version
candidate_id
execution_id
candidate_revision
intent_label
suggested_execution_mode
entity_selectors[]
parameter_candidates[]
clarification
confidence
provider_provenance_ref
candidate_hash
```

Forbidden authority fields include:

```text
tenant_authority
principal_authority
role_bindings
permission_grants
exact_capability_version
approval_authority
```

## ContextCandidateSet v1

```text
schema_version
candidate_id
execution_id
work_intent_ref
entity_candidates[]
retrieval_hints[]
resource_selectors[]
parameter_candidates[]
candidate_hash
```

## PlanCandidate v1

```text
schema_version
candidate_id
execution_id
work_intent_ref
agent_context_ref
suggested_plan_kind
logical_steps[]
completion_mapping[]
candidate_hash
```

Candidate IDs are not ExecutableStepIds.

---

# 7. Non-Functional Requirements

## P65-NFR-001 — Security

Provider secrets SHALL remain MO-owned.

AE SHALL not store provider endpoint or credential.

## P65-NFR-002 — Reliability

No provider failure may create executable work without validated canonical plan.

## P65-NFR-003 — Deterministic Boundary

Same admitted canonical AgentPlan SHALL compile with existing deterministic compiler semantics.

## P65-NFR-004 — Boundedness

All candidate arrays/text lengths/token budgets SHALL be bounded.

## P65-NFR-005 — Auditability

Every executed plan originating from an LLM candidate SHALL be traceable to exact prompt/model/candidate hashes.

## P65-NFR-006 — Privacy

Raw user prompt and model response SHALL follow existing owner-private storage policy and SHALL NOT be duplicated into general operational tables/logs.

## P65-NFR-007 — Compatibility

P4/P5/P6 regression SHALL remain green.

---

# 8. Negative / Adversarial Acceptance

Required cases:

1. provider endpoint unavailable;
2. provider timeout;
3. 429 with retry exhaustion;
4. provider 5xx;
5. non-JSON response;
6. JSON with extra/forbidden fields;
7. invented TenantId;
8. invented Principal/RoleBinding;
9. invented Project authority;
10. hallucinated capability;
11. unknown Skill/version;
12. plan step count > 12;
13. invalid dependency;
14. dependency cycle;
15. DELEGATE_WORK attempt;
16. WRITE/Approval attempt;
17. low-confidence intent;
18. prompt injection embedded in user prompt;
19. prompt injection embedded in context candidate;
20. Prompt Registry binding change during in-flight execution.

No negative case may reach runtime execution without deterministic admission.

---

# 9. Persistence Requirements

P6.5 SHALL first reuse:

```text
Prompt Registry persistence
WorkIntent persistence
AgentContext persistence
AgentPlan persistence
PlanValidation persistence
ExecutablePlan persistence
existing MO provider telemetry
```

If bounded candidate evidence cannot be represented without semantic loss,
CA01 MAY authorize one AE-owned candidate/evidence persistence structure.

It SHALL NOT become a competing WorkIntent/AgentContext/AgentPlan SoR.

---

# 10. Test Requirements

Required layers:

```text
unit
contract/schema
boundary
robustness
worst-case
PostgreSQL smoke
MO live provider smoke
E2E
regression
Full Gate
```

Remote provider tests SHALL include both:

```text
controlled fake HTTP transport tests
actual live provider acceptance
```

The former proves deterministic error classification.
The latter proves real integration.

---

# 11. P6.5 Exit Gate

P6.5 is complete only when:

```text
1. CA01 source-backed closure PASS
2. MO live generation preflight PASS
3. live Intent Candidate PASS
4. live Context Candidate PASS
5. live Plan Candidate PASS
6. deterministic validation/compiler PASS
7. failure/adversarial matrix PASS
8. actual PostgreSQL E2E PASS
9. actual Remote Provider E2E PASS
10. P4/P5/P6 regression PASS
11. repository Full Gate PASS
12. zero test residue
```

---

# 12. Golden Journey

Minimum:

```text
Real User Prompt
→ exact Prompt Registry
→ MO live generation
→ IntentCandidate
→ deterministic WorkIntent
→ MO live generation
→ ContextCandidateSet
→ TrustedContextResolver
→ AgentContext
→ MO live generation
→ PlanCandidate
→ deterministic AgentPlan
→ PlanValidation VALID
→ deterministic Compiler
→ ExecutablePlan
```

Preferred:

```text
→ LOCAL_SKILL
→ RuntimeJob
→ AE Worker
→ In-Process NSL READ
→ StepResult v1.2
→ AgentResult
```

---

# 13. Out of Scope

```text
WC
CLAIMED_WORKITEM
CA/PA/EA execution
DELEGATE_WORK activation
NSL WRITE
Approval
CommitState
VerificationStatus
UNKNOWN_COMMIT_STATE
Enterprise OS WRITE
Schedule
Recurring Work
```

---

# 14. Definition of Done

> **P6.5 is done when an actual Remote Generation Provider can generate Intent/Context/Plan candidates from a real IA prompt, while every authoritative decision and executable artifact remains deterministically validated, bound and compiled, and the complete acceptance passes real PostgreSQL and Full Gate without weakening P4~P6 invariants.**
