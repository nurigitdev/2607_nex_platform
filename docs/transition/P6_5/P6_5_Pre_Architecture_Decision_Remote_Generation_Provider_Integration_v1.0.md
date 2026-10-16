# P6.5 Remote Generation Provider Integration Acceptance
# Pre-Architecture Decision v1.0

**Status:** PRE-IMPLEMENTATION ARCHITECTURE BASELINE
**Phase:** P6.5 — Remote Generation Provider Integration Acceptance
**Predecessor:** P6 Final As-Built Baseline and P7 Handoff v1.0
**Successor:** P7 — WC + CA/PA/EA Background Work
**Date:** 2026-10-16

## 1. Purpose

P4~P6는 다음 deterministic skeleton을 실제 코드, PostgreSQL, regression 및 Full Gate로 안정화하였다.

```text
PROMPT
→ AgentExecution
→ WorkIntent
→ AgentContext
→ AgentPlan
→ PlanValidation
→ Deterministic Compiler
→ ExecutablePlan
→ RuntimeJob
→ AE Runtime Worker
→ LOCAL_SKILL
→ NSL READ
→ StepResult
→ AgentResult
```

그러나 P5의 Intent/Context/Plan 생성은 closure에서 의도적으로 deterministic path를 사용했다.

```text
Intent
= deterministic IntentDecision / fallback policy

AgentContext
= trusted deterministic resolver

AgentPlan
= DIRECT / KNOWN_TEMPLATE deterministic builder

Optional LLM Intent / Dynamic Planner
= disabled by default
= P5 closure requirement 아님
```

P6 acceptance 역시 Remote Model Provider를 요구하지 않았다.

P6.5의 목적은 P7 이전에 실제 Remote Generation Provider를 사용하여:

```text
Prompt
→ Intent Candidate
→ Context Candidate
→ Plan Candidate
```

를 생성하고, 비결정적 LLM 결과가 deterministic control plane을 절대 우회하지 않음을 증명하는 것이다.

---

## 2. Source-Backed Current State

### 2.1 P4

P4는 기존 Chat/RAG compatibility path를 canonical Agent Runtime에서 정확히 한 번 호출하도록 했다.

P4 invariant:

```text
no new direct provider access in AE
```

P4 observability는 기존 generation lineage를 추적한다.

```text
InteractionId
→ AgentExecutionId
→ RuntimeJobId
→ ExecutableStepId
→ RetrievalPackageId
→ CX GenerationId
→ CX JobId
→ GeneratedResponseId
→ AgentResultId
```

즉 content generation 경로는 존재하지만, P4는 LLM 기반 Intent/Plan generation을 검증한 단계가 아니다.

### 2.2 P5

P5 Prompt Registry는 이미 다음 purpose를 정의한다.

```text
intent_resolution
context_candidate_extraction
plan_builder
clarification
result_synthesis
```

P5의 LLM authority principle:

```text
Prompt Template
→ LLM candidate
→ schema validation
→ deterministic policy / validation
→ deterministic compiler
→ execution
```

하지만 Optional LLM Intent / Dynamic Planner는 기본 비활성이고 P5 closure requirement가 아니었다.

### 2.3 P6

P6는 NSL READ와 Agent Runtime의 deterministic execution integration을 닫았고, Remote Provider는 closure requirement가 아니었다.

P6.5는 P6 identity/runtime/persistence semantics를 변경하지 않는다.

### 2.4 MO Remote Generation

현재 MO에는 실제 Remote Generation Provider boundary가 존재한다.

```text
NEX_MO_PROVIDER_MODE=live
```

일 때:

```text
POST /api/v1/generations
→ execute_remote_generation_request()
→ OpenAI-compatible /v1/chat/completions
```

를 사용한다.

현재 MO는 이미 다음 기능을 소유한다.

```text
Provider Route / Alias
Model Profile
Remote Provider Preflight
Timeout
Bounded Retry
Retry-After handling
Provider Telemetry
Provider response normalization
response_format = json_object
non-streaming generation
```

### 2.5 CX → MO

CX에는 이미 다음 내부 service boundary가 있다.

```text
CX
→ HttpMoGenerationClient
→ nex-mo /api/v1/generations
→ Remote Provider
```

다만 CX generation은 grounded content generation 의미가 강하므로,
P6.5 semantic planning을 CX grounded-generation semantics에 억지로 결합하지 않는다.

---

## 3. Core Problem

현재 P4~P6는:

```text
Natural Language
→ Deterministic Intent/Plan skeleton
→ Deterministic Runtime
```

까지 검증했다.

최종 NeX Agent architecture는:

```text
Natural Language
→ LLM semantic interpretation / candidate generation
→ Deterministic validation
→ Deterministic execution
```

이다.

따라서 P6.5의 핵심 질문은 다음이다.

> **LLM을 실제로 연결하되, LLM이 authority가 되지 않는가?**

---

## 4. Core Architecture Decision

```text
                     NON-DETERMINISTIC
                           │
IA User Prompt             │
    ↓                      │
Exact Prompt Registry      │
    ↓                      │
MO Generation Boundary     │
    ↓                      │
Remote Generation Provider │
    ↓                      │
Intent Candidate           │
Context Candidate          │
Plan Candidate             │
                           │
───────────────────────────┼────────────────────────
                           ↓
                      DETERMINISTIC
                           │
                  Schema Validation
                           ↓
                  Authority Validation
                           ↓
                      WorkIntent
                           ↓
                      AgentContext
                           ↓
                    Plan Validation
                           ↓
                Deterministic Compiler
                           ↓
                    ExecutablePlan
```

Canonical invariant:

```text
LLM Candidate != Execution Authority
```

---

## 5. Architecture Decisions

### AD-01 — Preserve P4/P5/P6 Baseline

P6.5 SHALL NOT rename or replace:

```text
AgentExecution
WorkIntent
AgentContext
AgentPlan
PlanValidation
ExecutablePlan
ExecutableStep
RuntimeJob
StepResult
AgentResult
```

P6.5 is additive.

### AD-02 — No Direct Vendor Provider Access from AE

AE SHALL NOT call provider/vLLM endpoint or use provider API key directly.

Canonical route:

```text
AE semantic generation stage
→ internal MO Generation Client
→ nex-mo /api/v1/generations
→ MO route/readiness/retry/telemetry
→ Remote Provider
```

P4의 “no direct provider access in AE” 원칙을 유지한다.

### AD-03 — CX Grounded Generation Is Not the Semantic Planner

Intent/Context/Plan candidate generation은 Agent semantic control-plane 기능이다.

P6.5-CA01에서 generic reusable CX path가 증명되지 않는 한 기본 semantic planning route는:

```text
AE → MO
```

로 한다.

CX는 Retrieval/Evidence/Content Intelligence ownership을 유지한다.

### AD-04 — Provider Output Is Candidate Only

Remote provider output SHALL NOT directly create:

```text
WorkIntent
AgentContext
AgentPlan
ExecutablePlan
RuntimeJob
```

Provider output은 strict stage-specific candidate다.

```text
IntentCandidate
ContextCandidateSet
PlanCandidate
```

### AD-05 — Preserve Authority Boundary

LLM은 다음 authority를 생성/변경할 수 없다.

```text
TenantId
Principal
RoleBinding
OrgScope
ProjectScope
DataClassification
Capability exact version
Skill exact version
PackageTrust
Approval authority
WRITE authority
```

### AD-06 — Preserve P5 Canonical Order

```text
Prompt
→ Base Context
→ Intent Candidate Generation
→ Deterministic Intent Resolution
→ WorkIntent
→ Context Candidate Extraction
→ Trusted Context Resolution
→ AgentContext
→ Plan Candidate Generation
→ Deterministic Candidate Validation
→ AgentPlan
→ PlanValidation
→ Deterministic Compiler
→ ExecutablePlan
```

### AD-07 — Prompt Registry Is the Only Prompt Authority

각 stage는 exact RDBMS Prompt Registry binding/version을 사용한다.

Required provenance:

```text
prompt_binding_key
prompt_template_version_id
prompt_content_sha256
rendered_prompt_hash
model_profile
model_ref
input_context_hash
provider output hash
```

No implicit latest.

### AD-08 — Reuse MO Generation Capability

P6.5 SHALL reuse:

```text
POST /api/v1/generations
provider_capability = generation
response_format = {"type":"json_object"}
stream = false
```

P6.5 SHALL NOT create a second provider registry.

### AD-09 — Structured Candidate Output

Intent/Context/Plan은 JSON object output만 허용한다.

Malformed JSON 또는 schema-invalid output은 candidate admission failure다.

Text parsing heuristic으로 authority object를 추론하지 않는다.

### AD-10 — Controlled Rollout

최소:

```text
disabled
shadow
required
```

를 지원한다.

`required`에서는 provider/candidate failure 시 silent deterministic fallback을 금지한다.

### AD-11 — Bounded Candidate Evidence

최소 다음 evidence를 보존한다.

```text
stage
AgentExecutionId
candidate ref/hash
input context hash
prompt version/hash
model profile/ref
MO generation id / safe provider lineage
validation outcome
created_at
```

Raw provider endpoint/API key/hidden reasoning은 저장하지 않는다.

신규 table은 CA01에서 persistence gap이 확인된 경우에만 추가한다.

### AD-12 — Context Candidate Is Suggestion Only

Context Candidate는 entity/retrieval/resource hint를 제안할 수 있지만 Principal/Role/Tenant/Project authority/permission을 확정할 수 없다.

Canonical AgentContext는 기존 TrustedContextResolver가 확정한다.

### AD-13 — Plan Candidate Cannot Execute

Plan Candidate는 logical suggestion이며 exact capability/version binding은 deterministic layer가 수행한다.

P6.5에서 다음은 활성화하지 않는다.

```text
DELEGATE_WORK
CLAIMED_WORKITEM
WC
CA/PA/EA execution
NSL WRITE
Approval
```

### AD-14 — Real Provider Acceptance Mandatory

P6.5 final acceptance는 mock-only로 완료할 수 없다.

최소 Golden Journey는:

```text
actual MO live provider
+ actual Remote Generation Provider
+ actual PostgreSQL
```

를 사용한다.

### AD-15 — P7 Entry Blocked Until P6.5 Closure

```text
P4 PASS
P5 PASS
P6 PASS
P6.5 LIVE PROVIDER PASS
→ P7 AUTHORIZED
```

---

## 6. Candidate Contract Direction

Exact JSON Schema는 P6.5-CA01에서 확정한다.

### IntentCandidate

```text
schema_version
candidate_id
execution_id
intent_label
suggested_execution_mode
entity_selectors[]
parameter_candidates[]
clarification
confidence
candidate_hash
```

Canonical WorkIntent가 아니다.

### ContextCandidateSet

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

Canonical AgentContext가 아니다.

### PlanCandidate

```text
schema_version
candidate_id
execution_id
work_intent_ref
agent_context_ref
suggested_plan_kind
logical_steps[]
dependencies[]
completion_mapping[]
candidate_hash
```

Canonical AgentPlan이 아니며 실행 불가이다.

---

## 7. Failure Semantics

최소 다음을 분리한다.

```text
PROVIDER_NOT_READY
PROVIDER_TIMEOUT
PROVIDER_RATE_LIMIT
PROVIDER_5XX
PROVIDER_RESPONSE_INVALID
CANDIDATE_JSON_INVALID
CANDIDATE_SCHEMA_INVALID
CANDIDATE_AUTHORITY_VIOLATION
CANDIDATE_CAPABILITY_UNKNOWN
CANDIDATE_DEPENDENCY_INVALID
CANDIDATE_BOUNDS_EXCEEDED
CANDIDATE_LOW_CONFIDENCE
PROMPT_INJECTION_OR_POLICY_BLOCK
```

MO는 technical provider retry를 소유한다.

AE는 semantic retry/replan을 소유한다.

---

## 8. Scope

In scope:

```text
MO live generation readiness
AE→MO semantic generation client
Intent Candidate
Context Candidate
Plan Candidate
Prompt Registry exact versioning
Candidate schema validation
Authority validation
Deterministic PlanValidation
Deterministic Compiler
Live provider failure/adversarial tests
Actual PostgreSQL + live provider E2E
```

Out of scope:

```text
WC
CLAIMED_WORKITEM
CA / PA / EA execution
DELEGATE_WORK activation
NSL WRITE
Approval
Enterprise OS WRITE
Schedule / Recurring Work
Publication ACK redesign
```

---

## 9. P6.5 Entry Gate

1. P6 Final As-Built baseline green.
2. P6.5-CA01 source-backed audit closed.
3. Existing MO live generation exercised independently.
4. Actual provider/model readiness confirmed through MO preflight.
5. Exact Prompt Registry stage bindings and persistence gaps identified.

No P6.5 feature Slice begins before CA01 closes.

---

## 10. P6.5 Exit Shape

```text
Real User Prompt
→ AgentExecution
→ exact Prompt Registry
→ actual MO live generation
→ Remote Provider
→ IntentCandidate
→ deterministic Intent Resolution
→ WorkIntent
→ ContextCandidateSet
→ TrustedContextResolver
→ AgentContext
→ actual MO live generation
→ PlanCandidate
→ deterministic candidate validation
→ AgentPlan
→ PlanValidation VALID
→ deterministic Compiler
→ ExecutablePlan
```

Preferred Golden E2E additionally continues:

```text
→ LOCAL_SKILL
→ RuntimeJob
→ AE Runtime Worker
→ NSL READ
→ StepResult
→ AgentResult
```

---

## 11. CA01 Must Close

1. AE→MO generation service client 재사용/신규 thin client 여부.
2. Candidate evidence persistence reuse 가능 여부.
3. 신규 candidate table 필요 여부.
4. Prompt Registry P6.5 binding inventory.
5. 실제 provider의 `json_object` 지원.
6. canonical model/profile/provider provenance.
7. low-confidence exact directive.
8. ContextCandidate ↔ TrustedContextResolver exact boundary.
9. PlanCandidate 허용 capability vocabulary.
10. Golden Prompt와 deterministic invariants.

---

## 12. Closure Statement

> **P6.5는 실제 LLM을 candidate generator로 연결한 상태에서도 NeX Platform의 최종 결정과 실행이 deterministic boundary를 통해서만 이루어짐을 증명하는 Acceptance Phase이다.**
