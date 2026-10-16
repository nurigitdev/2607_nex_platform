# P6.5 Remote Generation Provider Integration Acceptance
# Implementation Slice Plan v1.0

**Status:** IMPLEMENTATION PLAN
**Phase:** P6.5
**Entry:** P6 Final As-Built Baseline CLOSED
**Exit:** P7 Entry Authorized
**Date:** 2026-10-16

---

## 1. Execution Principle

P6.5 SHALL follow:

```text
Source Audit
→ Contract Closure
→ Minimal Refactoring
→ Slice Implementation
→ Unit/Regression
→ Protected Live Acceptance
→ Full Gate
→ Commit
```

General principles:

```text
Refactoring First
Read Before Write
No Hidden Migration
Test as Contract
Frozen Preservation
No direct vendor provider access from AE
```

No P6.5 feature Slice starts before P6.5-CA01 closes.

---

## 2. Canonical Slice Sequence

```text
P6.5-CA01
Current Generation Path Source Audit
+ Semantic Candidate Contract Closure

→ P6.5-S1
MO Live Generation Client / Readiness

→ P6.5-S2
Live Intent Candidate Generation

→ P6.5-S3
Live Context Candidate Extraction

→ P6.5-S4
Live Plan Candidate Generation

→ P6.5-S5
Deterministic Candidate Admission / Compile Integration

→ Checkpoint Gate

→ P6.5-S6
Provider Failure / Adversarial Hardening

→ P6.5-S7
Actual PostgreSQL + Remote Provider E2E / P7 Entry Closure

→ Repository Full Gate
```

---

## 3. P6.5-CA01 — Source-Backed Closure

### Goal

현재 generation path를 source-backed로 확정하고 중복 framework 생성을 막는다.

### Required Audit

#### AE

확인:

```text
Prompt Registry
Prompt rendering/provenance
IntentDecision
WorkIntent
TrustedContextResolver
AgentContext
AgentPlan
PlanValidation
Compiler
existing service-auth patterns
```

#### CX

확인:

```text
CX → MO HttpMoGenerationClient
grounded generation ownership
generation lineage
owner-private content handling
```

#### MO

확인:

```text
/api/v1/generations
NEX_MO_PROVIDER_MODE
remote generation config
preflight
provider route/profile
retry
telemetry
json_object support
response normalization
```

### Decisions to Close

1. AE→MO service client reuse/addition.
2. Exact candidate schema.
3. Prompt binding keys and versions.
4. Candidate evidence persistence.
5. model/profile provenance.
6. error taxonomy.
7. rollout mode.
8. Golden Prompt.
9. actual provider acceptance configuration.

### Deliverables

```text
P6_5_CA01_Source_Backed_Generation_Contract_Closure_v1.0.md
contracts/intent-candidate-v1.schema.json
contracts/context-candidate-set-v1.schema.json
contracts/plan-candidate-v1.schema.json
contracts/examples/*
```

### Exit

CA01 focused contract tests PASS.

---

## 4. P6.5-S1 — MO Live Generation Client / Readiness

### Goal

AE semantic stage가 vendor endpoint를 직접 보지 않고 MO generation contract만 사용하도록 한다.

### Implementation

Prefer:

```text
AeMoGenerationClient
→ POST nex-mo /api/v1/generations
```

Reuse existing service-auth / request-id / trace-id pattern.

Request must support:

```text
alias
provider_capability=generation
messages
response_format=json_object
max_output_tokens
reasoning_mode
stream=false
```

Readiness must verify MO live provider before required mode.

### Tests

- client serialization;
- service auth;
- timeout mapping;
- 429/5xx mapping;
- forbidden provider-private fields;
- json_object request propagation;
- actual MO live preflight protected smoke.

### Exit

Real MO live provider response observed through internal contract.

---

## 5. P6.5-S2 — Live Intent Candidate Generation

### Goal

실제 LLM이 IA prompt에서 IntentCandidate를 생성하되 WorkIntent authority를 갖지 않도록 한다.

### Flow

```text
User Prompt
→ exact intent_resolution Prompt Registry binding
→ render
→ MO generation
→ IntentCandidate JSON
→ schema validation
→ deterministic IntentDecision
→ WorkIntent
```

### Guards

Reject:

```text
forbidden authority field
unsupported execution mode
malformed confidence
unbounded selectors
unknown schema
```

### Rollout

First support:

```text
shadow
required
```

Existing deterministic path remains for disabled/shadow.

### Tests

- valid candidate;
- low confidence;
- invented tenant/principal/project;
- malformed JSON;
- prompt injection;
- exact prompt provenance;
- in-flight binding switch isolation.

### Exit

Live provider candidate produces WorkIntent only through deterministic resolver.

---

## 6. P6.5-S3 — Live Context Candidate Extraction

### Goal

LLM을 context suggestion에 사용하되 canonical AgentContext는 trusted resolver가 계속 소유한다.

### Flow

```text
WorkIntent
+ Base Context
→ context_candidate_extraction prompt
→ MO generation
→ ContextCandidateSet
→ schema/authority validation
→ TrustedContextResolver
→ AgentContext
```

### Guard

LLM may suggest:

```text
entities
resource selectors
retrieval hints
query terms
parameters
```

LLM may not assert:

```text
Principal
RoleBinding
Tenant
permission
classification authority
```

### Tests

- valid entity candidates;
- unauthorized project suggestion;
- cross-tenant suggestion;
- excessive candidate count;
- candidate injection;
- deterministic trusted resolution.

### Exit

AgentContext remains authoritative trusted snapshot.

---

## 7. P6.5-S4 — Live Plan Candidate Generation

### Goal

실제 LLM이 logical PlanCandidate를 생성하되 실행 가능한 plan을 직접 생성하지 못하도록 한다.

### Flow

```text
WorkIntent
+ AgentContext
+ CapabilitySnapshot summary
→ plan_builder prompt
→ MO generation
→ PlanCandidate
→ schema validation
→ capability/dependency binding
→ AgentPlan
```

### Allowed P6.5 Plan Scope

Allowed:

```text
existing P5/P6 local capabilities
LOCAL_SKILL where exact deterministic binding is available
REPORT
AGGREGATE where already supported
```

Not activated:

```text
DELEGATE_WORK
WC
CLAIMED_WORKITEM
WRITE
Approval
```

### Tests

- valid multi-step candidate;
- unknown capability;
- hallucinated Skill;
- >12 steps;
- dependency cycle;
- invalid terminal mapping;
- DELEGATE_WORK rejection;
- exact capability version binding.

### Exit

Canonical AgentPlan is immutable and provenance-complete.

---

## 8. P6.5-S5 — Deterministic Candidate Admission / Compile Integration

### Goal

세 LLM stage를 기존 deterministic P5 pipeline에 연결한다.

### Canonical Flow

```text
Prompt
→ IntentCandidate
→ WorkIntent
→ ContextCandidateSet
→ AgentContext
→ PlanCandidate
→ AgentPlan
→ PlanValidation
→ ExecutablePlan
```

### Key Rules

- LLM never bypasses PlanValidation.
- Compiler remains LLM/provider-free.
- same admitted canonical Plan semantics preserve deterministic hash behavior.
- technical provider retry does not create semantic replan.
- required mode never silently falls back.

### Persistence

Candidate evidence persistence is implemented only as authorized by CA01.

### Tests

- complete deterministic integration;
- restart/replay;
- exact prompt/model/candidate provenance;
- immutable candidate/evidence;
- no runtime work before VALID;
- no duplicate AgentExecution.

### Checkpoint Gate

After S5:

```text
P6.5 focused regression
P4/P5/P6 regression
AE Slice Gate
contract validation
actual PostgreSQL smoke
actual provider protected smoke
```

If FAIL, do not proceed to S6.

---

## 9. P6.5-S6 — Provider Failure / Adversarial Hardening

### Goal

실제 LLM/provider failure가 deterministic runtime authority를 침범하지 않음을 증명한다.

### Failure Matrix

#### Transport / Provider

```text
endpoint unavailable
timeout
429
retry-after
5xx
invalid upstream JSON
model unavailable
```

#### Candidate

```text
non-JSON output
schema violation
extra forbidden fields
low confidence
unknown capability
unknown Skill/version
invalid dependency
dependency cycle
plan bounds exceeded
```

#### Security

```text
invented Tenant
invented Principal
invented RoleBinding
invented Project authority
prompt injection
retrieved-data injection
hidden reasoning leakage attempt
provider-private field leakage
```

### Required Result

No case may create executable work unless:

```text
candidate schema PASS
authority validation PASS
AgentPlan validation VALID
compiler PASS
```

### Tests

Boundary, robustness, worst-case, retry/restart and privacy scan.

---

## 10. P6.5-S7 — Actual PostgreSQL + Remote Provider E2E / P7 Entry Closure

### Minimum Golden Journey

```text
Real IA Prompt
→ AgentExecution
→ exact Prompt Registry
→ actual MO live provider
→ IntentCandidate
→ WorkIntent
→ actual MO live provider
→ ContextCandidateSet
→ AgentContext
→ actual MO live provider
→ PlanCandidate
→ AgentPlan
→ PlanValidation VALID
→ deterministic Compiler
→ ExecutablePlan
```

### Preferred Extended Golden Journey

Continue:

```text
→ LOCAL_SKILL
→ RuntimeJob
→ Dispatcher
→ AE Runtime Worker
→ NSL_V01_IN_PROCESS
→ NSL READ
→ StepResult v1.2
→ AgentResult
→ ResultDelivery(PENDING)
```

### Acceptance Evidence

Record:

```text
Platform revision
NSL revision/wheel
PostgreSQL database/role
MO provider mode
provider profile/model ref
Prompt Registry versions
candidate hashes
WorkIntent/AgentContext/AgentPlan IDs
ExecutablePlan ID/hash
RuntimeJob/StepResult/AgentResult identities if extended
provider call counts
zero residue
```

Do not record:

```text
provider endpoint
API key
raw secret
hidden reasoning
```

### Closure

P6.5-S7 must run actual Remote Provider. Mock-only evidence is invalid.

---

## 11. Quality Gates

### Per Slice

Every source change:

```text
unit
regression
boundary
robustness
worst-case where applicable
```

PostgreSQL-related change:

```text
isolated/reset test data
actual PostgreSQL protected smoke
zero residue
```

### Checkpoint

After S5.

### Final Full Gate

After S7:

```text
repository-wide pytest
coverage threshold
contract validation
service smoke chain
P6.5 live acceptance
```

P6.5 closure requires Full Gate PASS.

---

## 12. Naming / Test Ownership

Document phase name:

```text
P6.5
```

Recommended filesystem-safe test namespace:

```text
tests/test_ae_p65_*.py
```

Platform-wide integration tests:

```text
tests/test_platform_p65_*.py
```

CA01 SHALL confirm one stable naming convention and add a guard if needed.

---

## 13. Expected New/Modified Areas

Likely AE source areas:

```text
semantic_generation_client.py
semantic_candidates.py
intent_candidate_generation.py
context_candidate_generation.py
plan_candidate_generation.py
semantic_generation_runtime.py
```

Names are non-normative until CA01 source audit.

Likely reuse:

```text
work_intent.py
agent_context.py
agent_plans.py
plan_validation.py
executable_plans.py
Prompt Registry
MO provider contracts
```

No second provider registry.

---

## 14. Migration Policy

Default:

```text
No migration until CA01 proves persistence gap.
```

If one candidate/evidence table is necessary:

- bounded;
- immutable;
- tenant-scoped;
- no raw prompt/provider secret;
- not a competing semantic SoR;
- exact provenance/hash required.

Migration number SHALL be selected from actual current migration inventory at implementation time.

---

## 15. Commit Strategy

Recommended commits:

```text
docs(p65): close source-backed generation contracts
feat(p65): add MO semantic generation client
feat(p65): add live intent candidate
feat(p65): add live context candidate
feat(p65): add live plan candidate
feat(p65): integrate deterministic candidate admission
test(p65): harden provider and adversarial failures
test(p65): close live provider e2e and P7 entry
```

Each functional commit SHALL follow regression PASS.

---

## 16. P7 Entry Decision

P7 becomes authorized only when:

```text
P6.5 CA01 CLOSED
S1-S7 COMPLETE
actual Remote Provider PASS
actual PostgreSQL PASS
P4-P6 regression PASS
Full Gate PASS
```

Then freeze:

```text
P6_5_Final_AsBuilt_Baseline_and_P7_Entry_v1.0.md
```

---

## 17. Final Principle

```text
LLM generates candidates.
Deterministic code grants authority.
Deterministic compiler creates executable work.
Runtime executes only admitted artifacts.
```

> **P6.5 exists to prove this principle with a real Remote Generation Provider before P7 introduces multi-agent and background-work complexity.**
