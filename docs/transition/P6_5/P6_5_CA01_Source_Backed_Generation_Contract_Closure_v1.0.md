# P6.5-CA01 Source-Backed Generation Contract Closure v1.0

**Status:** CLOSED
**Observed date:** 2026-10-16
**Scope:** IA semantic candidate generation before P7
**Predecessor:** P6 Final As-Built Baseline and P7 Handoff v1.0
**Reviewed Platform HEAD:** `7ccd6571a99dacb9e8c9e2bb766e96d78621d01f`

## 1. Closure Statement

P6.5-CA01 inspected the current AE planning, chat, Prompt Registry, Agent
Runtime, MO generation, provider, private-storage, and persistence sources. It
closes the implementation-facing contracts required before P6.5-S1.

The invariant is:

```text
LLM Candidate != Execution Authority
```

This closure adds machine-readable transition contracts and authorizes later
Slices. It does not call a live provider, add a database migration, activate a
new runtime path, or change the P4-P6 user-visible Chat/RAG behavior.

## 2. Source-Backed Current State

| Boundary | Current source truth | P6.5 consequence |
|---|---|---|
| IA public entry | `POST /api/v1/chat/interactions` in `chat.py` | Reuse; no P6.5 public route |
| Chat authority | Request path directly resolves policy and invokes CX | Shadow preserves it; required redirects authority through Agent Runtime |
| Agent Runtime | Attached after chat route registration; available through app state | P6.5 orchestration resolves it at request time |
| WorkIntent | `build_work_intent_from_decision()` and immutable repository | Candidate must first become deterministic IntentDecision |
| AgentContext | `TrustedContextResolver` receives no candidate hints today | S3 adds an optional bounded untrusted-hints input |
| AgentPlan | Deterministic compatibility builder plus strict canonical validator | S4 adds candidate binder; validator remains authoritative |
| Capability | Tenant snapshot binds exact version/executor | LLM supplies ID hint only, never exact version |
| Planning rollout | `NEX_AE_PLANNING_MODE=disabled|shadow|required` already exists | Reuse exactly; no P6.5 mode variable |
| Prompt Registry | Versioning, atomic binding history, rendering and PostgreSQL store exist | Add three exact bindings; no second registry |
| Prompt seeds | Current runtime seeds do not contain the three semantic stage bindings | S2-S4 add immutable v1 seeds |
| MO generation | Canonical request/response and live OpenAI-compatible adapter exist | Add thin AE-to-MO client only |
| MO structured output | `json_object`, non-streaming and reasoning control are supported | Reuse with reasoning disabled |
| Candidate evidence | Canonical semantic tables retain successful objects only | One bounded AE evidence SoR is required |
| Private payloads | AE filesystem/S3 private object-storage abstraction exists | Reuse for admitted normalized candidate payloads |

## 3. Decision 1 - Generated Payload and Platform Envelope

The model returns only a closed semantic payload:

```text
IntentCandidate payload
ContextCandidateSet payload
PlanCandidate payload
```

The model does not generate:

```text
candidate_id
execution_id
candidate_revision
tenant_id
owner_subject_id
candidate_hash
prompt/model/provider provenance
storage reference
validation outcome
```

AE allocates the candidate UUID and revision, binds the existing
AgentExecution, normalizes the validated payload, and computes the shared
`sha256:<hex>` semantic hash. The bare SHA-256 of the exact MO output text is
recorded separately as `provider_output_sha256`.

Technical MO retries retain the same execution/stage/revision identity. A
semantic retry or replan creates a new candidate UUID and revision.

The canonical machine contracts are:

```text
contracts/p65-intent-candidate-v1.schema.json
contracts/p65-context-candidate-set-v1.schema.json
contracts/p65-plan-candidate-v1.schema.json
contracts/p65-semantic-candidate-evidence-v1.schema.json
```

## 4. Decision 2 - IA Entry, Orchestration, and Recovery

P6.5 keeps the existing authenticated IA endpoint:

```text
POST /api/v1/chat/interactions
```

No `/p65`, planner-only, or provider-facing public route is added.

The semantic orchestrator is an AE application service invoked behind that
route after owner/workspace/conversation admission and before content
generation. It performs:

```text
AgentExecution admission
→ INTENT candidate/resolution/WorkIntent
→ CONTEXT candidate/trusted resolution/AgentContext
→ PLAN candidate/binding/AgentPlan
→ PlanValidation
→ deterministic compile
```

Mode behavior is exact:

| Planning mode | Agent Runtime mode | Authority |
|---|---|---|
| `disabled` | any valid mode | Existing Chat/RAG path only |
| `shadow` | `shadow` or `required` | Candidate pipeline observes; existing Chat/RAG executes |
| `required` | `required` only | Admitted plan/runtime path executes; no direct duplicate generation |

Any other combination is not ready. Required mode additionally needs AE
PostgreSQL, all three exact prompt bindings, MO generation readiness, and an
active model-revision calibration policy.

The first P6.5 implementation remains request-orchestrated rather than adding
a second pre-compile queue. Durability comes from insert-or-verify stage
evidence and the existing immutable WorkIntent, AgentContext, AgentPlan,
PlanValidation, and ExecutablePlan records. Retrying the same interaction
reloads completed stages and resumes at the first missing stage.

In required mode the endpoint reuses the existing asynchronous interaction
projection and returns accepted work without executing Chat/RAG in the API
request. The P6 compatibility RuntimeJob executes Chat/RAG exactly once. P7
may later move planning itself to background work without changing these
candidate contracts.

## 5. Decision 3 - Exact Prompt Bindings

The existing RDBMS Prompt Registry remains the sole prompt authority.

```text
ae.intent_resolution.default
  purpose = intent_resolution

ae.context_candidate_extraction.default
  purpose = context_candidate_extraction

ae.plan_builder.default
  purpose = plan_builder
```

Initial immutable template version is `v1` for each key. S2-S4 add the seeds
through the existing `AE_PROMPT_SEEDS` and PostgreSQL store behavior. No
Prompt Registry schema migration or second registry is authorized.

At stage start AE resolves and captures one exact binding ID, template version
ID/version, content digest, rendered digest, and input-context hash. A binding
pointer change cannot affect an in-flight stage or its technical retry.

## 6. Decision 4 - Context Candidate Boundary

ContextCandidateSet is untrusted suggestion data only. S3 extends
`ContextBuildRequest` with one optional bounded `candidate_hints` projection;
it does not place the raw model object into AgentContext.

The existing TrustedContextResolver continues to own canonical resolution.
Candidate hints may influence lookup terms and selectors but cannot set:

```text
tenant or principal
role or permission
project authority
data classification
owner visibility
resource admission
```

`project_ref` remains null unless an already trusted source resolves it. P6.5
does not introduce Enterprise OS, default Project, WC, or Project Agent.

## 7. Decision 5 - Candidate Evidence Persistence

Existing semantic tables cannot represent rejected candidates or resume the
three-stage pipeline without semantic loss. P6.5 therefore authorizes one
short AE-owned metadata table:

```text
ae_semantic_candidate
```

Required identity and uniqueness:

```text
PRIMARY KEY (tenant_id, candidate_id)
UNIQUE (tenant_id, agent_execution_id, semantic_stage, candidate_revision)
```

The row is immutable/insert-or-verify and stores only the bounded evidence
defined by `p65-semantic-candidate-evidence-v1`. The normalized admitted
candidate payload is content-addressed in AE owner-private storage:

```text
ae://semantic-candidates/{candidate_id}/{payload_sha256}.json
```

PostgreSQL retains its opaque reference, size, semantic hash, provider-output
digest, exact prompt/model lineage, outcome, directive, and error code.

Invalid JSON and schema-invalid outputs retain only bounded metadata and the
provider-output digest; their raw output is not persisted. Hidden reasoning,
raw provider envelopes, endpoint, API key, raw prompt, and secrets are never
stored in this table or operational logs.

The migration number is selected from the actual inventory in the Slice that
implements this table; CA01 does not pre-allocate one.

## 8. Decision 6 - Confidence and Calibration

Model self-reported confidence is an untrusted input signal, never sufficient
execution authority. Candidate admission requires schema, authority, bounds,
lineage, and deterministic semantic checks before confidence policy.

Thresholds are versioned runtime policy data selected by:

```text
semantic stage
+ model profile (MO alias)
+ model ref (MO model_revision)
+ admission policy version
```

There is no model-independent hard-coded threshold. Missing calibration makes
required mode not ready with `SEMANTIC_CALIBRATION_REQUIRED`. Shadow mode may
collect calibration evidence without execution authority.

Low-confidence directives are exact:

| Stage | Required-mode directive |
|---|---|
| INTENT | `CLARIFICATION_REQUIRED` |
| CONTEXT | `CONTEXT_REFRESH_REQUIRED` |
| PLAN | `REPLAN_REQUIRED` |

No low-confidence case creates an ExecutablePlan or RuntimeJob. S2-S4 must
record the selected threshold and golden/adversarial evidence for the live
model revision before S7 required-mode acceptance.

## 9. Decision 7 - AE-to-MO Wire Contract

The new component is a thin internal client, not a provider adapter:

```text
AeMoGenerationClient
→ POST {NEX_MO_BASE_URL}/api/v1/generations
→ service token audience nex-mo
```

Correlation uses existing HTTP headers:

```text
Authorization: Bearer <OA service token>
X-Request-ID
traceparent
X-Service-ID: nex-ae-api
```

P6.5 stage request policy is:

```text
provider_capability = generation
alias = configured MO generation alias
messages = trusted system/developer segments + untrusted data segments
response_format = {"type":"json_object"}
reasoning_mode = disabled
temperature = 0.0
stream = false
max_output_tokens = 768 / 1024 / 1024 for INTENT / CONTEXT / PLAN
```

P6.5-S1 source reconciliation fixed CONTEXT and PLAN at 1024 because the
active `general-llm-default` MO route contract admits at most 1024 output
tokens. Raising either bound requires a versioned MO catalog/alias lifecycle
change; AE must not silently exceed the admitted route contract.

AE never accepts caller-supplied provider URL, endpoint, model path, API key,
or exact provider model. Response provenance maps as follows:

```text
model_profile   <- alias
model_ref       <- model_revision
deployment_id  <- deployment_id
MO lineage      <- mo_generation_id
```

MO owns bounded transport retry and Retry-After. AE maps final provider
failures into the P6.5 taxonomy and owns semantic retry/replan. P6.5-S1 must
set its client timeout above the configured MO generation budget rather than
reintroducing the old five-second timeout.

## 10. Decision 8 - Plan Candidate Vocabulary

The model-facing logical vocabulary is limited to:

```text
LOCAL_CAPABILITY
AGGREGATE
REPORT
```

`LOCAL_SKILL` is an executor kind, not a model-authored logical step type.
For `LOCAL_CAPABILITY`, the model may provide only a capability ID hint. The
tenant CapabilitySnapshot resolves exact version, executor kind, contracts,
Skill version/hash, trust policy, and backend profile.

`REPORT` and `AGGREGATE` carry no model-authored capability version. P6.5
rejects `DELEGATE_WORK`, `CLAIMED_WORKITEM`, WRITE, Approval, unknown
capabilities, unavailable exact versions, cycles, invalid dependencies,
duplicate IDs, more than 12 steps, and parallel width greater than one.

PlanValidation and the deterministic compiler remain unchanged execution
authorities.

## 11. Error and Directive Closure

Canonical external classes are:

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
CANDIDATE_DEPENDENCY_INVALID
CANDIDATE_BOUNDS_EXCEEDED
CANDIDATE_LOW_CONFIDENCE
PROMPT_INJECTION_OR_POLICY_BLOCK
SEMANTIC_CALIBRATION_REQUIRED
```

MO technical retry does not allocate a new semantic candidate. Semantic retry
does. Required mode never converts one of these failures into the deterministic
fallback path.

## 12. Golden Acceptance Prompt

The canonical Korean acceptance intent is:

```text
내가 접근할 수 있는 프로젝트 예산 자료를 확인해서
총 예산, 집행액, 잔액을 한국어로 요약해줘.
```

The fixture supplies an already authorized resource context and exact P6 READ
capability snapshot. The model may suggest the project-budget capability but
cannot establish Project authority. Missing trusted context results in
clarification/context refresh, not invented authority.

Minimum live calls:

```text
INTENT -> CONTEXT -> PLAN = 3 MO generation calls
```

The accepted plan is then validated and compiled. Preferred S7 evidence
continues through the existing P6 LOCAL_SKILL READ path.

## 13. Slice Authorization

| Slice | Authorized implementation |
|---|---|
| S1 | Thin AE-to-MO client, readiness, exact wire/error mapping |
| S2 | Intent payload generation, deterministic IntentDecision, v1 prompt seed |
| S3 | Context payload generation, bounded hints, trusted resolution, v1 prompt seed |
| S4 | Plan payload generation, capability/dependency binder, v1 prompt seed |
| S5 | Existing IA route orchestration, candidate persistence/private storage, resume, compile |
| S6 | Provider/adversarial/privacy/failure matrix |
| S7 | Actual PostgreSQL + live provider E2E, zero residue, P7 entry closure |

Checkpoint Gate remains after S5. S7 and final Full Gate must run with an
actual live Remote Generation Provider; mock-only evidence cannot close P6.5.

## 14. CA01 Exit Evidence

P6.5-CA01 is closed when:

```text
1. all four transition schemas pass Draft 2020-12 validation;
2. all Golden examples validate;
3. authority/delegation/secret negative fixtures fail validation;
4. source guards confirm existing planning modes and MO wire support;
5. focused P5/P6/P6.5 contract regression passes; and
6. this closure remains additive to the P6 Final As-Built baseline.
```

## 15. Verification Evidence

Executed on 2026-10-16 against the reviewed Platform source:

```text
P6.5 CA01 schema/example/negative/source tests: 17 passed
P5/P6/P6.5 contract and quality-selection regression: 109 passed
Transition JSON parse inventory: 12 files passed
Whitespace/error check: passed
```

The focused regression includes the existing P5 planning contracts, P6 READ
contracts, central contract validation, tiered quality-gate selection, and AE
test-namespace rules. PostgreSQL and live provider evidence are intentionally
not part of CA01 because this Slice adds no migration and activates no runtime
path; they remain mandatory in the authorized implementation Slices.

## 16. Final Principle

```text
The model writes bounded semantic suggestions.
AE assigns identity and provenance.
Trusted deterministic code grants authority.
The compiler alone creates executable work.
```

> **P6.5-CA01 is closed. P6.5-S1 is authorized.**
