# P5 LLM Prompt Template Registry & Governance Design v1.0

**Status:** P5 COMMON LLM CONTROL-PLANE DESIGN

**Scope:** Intent Resolution, Context Extraction, Plan Builder, Result Synthesis, Clarification/Repair/Evaluation prompts
**Owner:** NeX-AE logical ownership; model serving remains NeX-MO responsibility

---

## 1. Purpose

P5 and later phases increasingly depend on LLM calls.

Examples:

```text
User Prompt
→ Intent Candidate / WorkIntent assistance

Context
→ entity/parameter candidate extraction

WorkIntent + AgentContext
→ AgentPlan candidate

StepResults
→ result synthesis / report candidate
```

These LLM behaviors require controlled System Prompt Templates.

Prompt text SHALL NOT be treated as ordinary source-code constants.

The runtime architecture is:

```text
Prompt Template Registry (RDBMS)
        ↓
Binding Key
        ↓
Exact PromptTemplateVersion
        ↓
Prompt Render / Compile
        ↓
Prompt Package Snapshot + Hash
        ↓
MO Model Serving
        ↓
LLM Output
        ↓
deterministic validation / compiler / policy
```

---

## 2. Current As-Built Foundation

The current AE implementation already contains:

```text
ae_prompt_templates
ae_prompt_template_versions
ae_prompt_bindings
ae_prompt_render_events
```

and:

```text
SqlAlchemyAePromptRegistryStore
PromptRegistryStore
PromptSeed
```

The current source also seeds default system prompts from code.

Therefore P5 SHALL evolve the existing registry instead of introducing a second prompt-management system.

---

## 3. Ownership Boundary

### NeX-AE

Owns:

- prompt purpose / logical binding
- System Prompt Template
- exact prompt version
- input/output contract binding
- render policy
- prompt provenance
- prompt evaluation/activation state
- prompt execution snapshot

### NeX-MO

Owns:

- model/provider serving
- model profile/routing
- inference health
- runtime model capability
- model telemetry

### NeX-AG — future governance integration

May govern:

- who can approve/activate prompt versions
- security policy / kill-switch
- audit policy
- high-risk prompt change approval

AG SHALL NOT become the prompt-content runtime SoR.

---

## 4. Core Principle

```text
Source Code
= bootstrap / schema / renderer / safety logic

RDBMS Prompt Registry
= operational Prompt Template SoR

AgentExecution / Plan provenance
= exact version/hash snapshot
```

No runtime code SHALL depend on “whatever prompt text happens to be in the current source package”.

---

## 5. PromptTemplate vs PromptTemplateVersion vs Binding

### PromptTemplate

Logical identity:

```text
prompt_template_id
service_id
purpose
name
owner_domain
status
```

Example purpose:

```text
intent_resolution
context_candidate_extraction
plan_builder
clarification
result_synthesis
repair
evaluation
```

### PromptTemplateVersion

Immutable content version:

```text
prompt_template_version_id
prompt_template_id
version
role
segment_order
content
content_sha256
model_capability
metadata
created_at
```

### PromptBinding

Mutable deployment pointer:

```text
binding_key
→ exact prompt_template_version_id
```

Example internal binding keys:

```text
ae.intent_resolution.default
ae.context_extraction.default
ae.plan_builder.default
ae.result_synthesis.default
ae.clarification.default
```

These names are internal until separately frozen as public/stable contract vocabulary.

---

## 6. Mandatory Immutability Rule

A PromptTemplateVersion is immutable.

Forbidden:

```text
same template
+ same version "v1"
+ different content
→ UPDATE
```

Required:

```text
v1 content change
→ create v2
→ validate/evaluate
→ change binding from v1 to v2
```

Idempotent re-seed behavior:

```text
same template/version/content_sha256
→ NO-OP / return existing

same template/version/different content_sha256
→ deterministic VERSION_CONTENT_CONFLICT
```

The current `ON CONFLICT ... DO UPDATE content` behavior SHALL be removed for immutable version records.

---

## 7. Bootstrap Rule

Source-code PromptSeed remains permitted only as bootstrap/fallback data.

Normal startup SHALL NOT overwrite an operator-managed DB prompt version.

Recommended:

```text
DB empty
→ seed baseline version

DB version exists with same hash
→ no-op

DB version exists with different hash
→ fail bootstrap conflict / emit governance warning
```

Do not silently replace DB content from source.

---

## 8. Exact Version Resolution

Runtime SHALL NOT resolve:

```text
latest
current text
highest semantic version
```

implicitly.

Runtime resolution:

```text
binding_key
→ ACTIVE binding
→ exact prompt_template_version_id
→ exact content_sha256
```

At LLM admission, save exact prompt provenance.

---

## 9. Prompt Execution Snapshot

Every LLM-dependent Agent stage SHALL create or reference an immutable prompt snapshot.

Minimum:

```text
prompt_binding_id
binding_key
prompt_template_version_id
prompt_template_version
template_content_sha256

model_profile_ref
model_ref if resolved
render_policy_version

input_context_hash
user_prompt_hash or source_ref/hash
rendered_prompt_hash

agent_execution_id
work_intent_id / context_id / plan_id as applicable

correlation_id
created_at
```

Retry/resume MUST use the same exact prompt template version unless a new semantic execution/replan explicitly chooses another version.

---

## 10. Prompt Rendering

Prompt template content may use bounded variables.

Example:

```text
{{work_intent}}
{{agent_context_summary}}
{{capability_catalog}}
{{output_schema}}
```

The renderer SHALL:

1. validate allowed variables;
2. reject unknown variables;
3. reject missing required variables;
4. enforce value size limits;
5. preserve role/segment order;
6. render deterministically;
7. calculate rendered_prompt_hash;
8. avoid storing raw private context in audit metadata when refs/hashes are sufficient.

No arbitrary template code execution is permitted.

---

## 11. Input / Output Contract Binding

Prompt versions SHOULD bind to machine-readable contracts.

Recommended metadata:

```text
input_schema_ref
output_schema_ref
allowed_variables
required_variables
model_capability
recommended_model_profile
max_input_chars/tokens
max_output_tokens
temperature_policy
grounding_required
citation_required
```

For P5:

### Intent Resolver prompt

Output contract:

```text
IntentCandidate / WorkIntent candidate
```

### Context extraction prompt

Output contract:

```text
entity selectors / parameter candidates only
```

No authoritative entity IDs.

### Plan Builder prompt

Output contract:

```text
AgentPlan candidate
```

The candidate is never executable until the Plan Validator persists
`status=VALID` and the Deterministic Compiler succeeds.

---

## 12. Prompt and Deterministic Control Boundary

LLM prompt control does not make LLM output authoritative.

Canonical P5 rule:

```text
Prompt Template
→ LLM
→ Candidate Object
→ schema validation
→ deterministic business validation
→ deterministic compiler
→ execution
```

Examples:

```text
LLM IntentCandidate
!= authoritative entity resolution

LLM AgentPlan
!= ExecutablePlan

LLM-generated capability name
!= executable registered capability
```

---

## 13. Suggested P5 Prompt Purposes

P5 Registry-supported purposes (a purpose becomes runtime-mandatory only when
its LLM stage is enabled):

```text
INTENT_RESOLUTION
CONTEXT_CANDIDATE_EXTRACTION
PLAN_BUILD
CLARIFICATION
RESULT_SYNTHESIS
```

Optional later:

```text
PLAN_REPAIR
RESULT_REPAIR
EVALUATION
RISK_EXPLANATION
```

P5 deterministic/template planning can close without production LLM Intent or
Plan Builder, but the Registry MUST support their future purposes. Existing
LLM-dependent response generation remains governed by its current exact prompt
bindings.

---

## 14. Prompt Change Lifecycle

Recommended lifecycle:

```text
DRAFT
→ offline validation
→ test/evaluation
→ approval
→ binding activation
→ production observation
→ rollback or retire
```

Minimum P5 implementation can keep current status vocabulary if schema migration is undesirable, but activation MUST be explicit through binding.

A prompt edit never mutates an active version.

---

## 15. Binding History / Rollback

Current binding is a mutable pointer.

P5 SHOULD add binding-change history or equivalent audit record:

```text
binding_key
old_prompt_template_version_id
new_prompt_template_version_id
changed_by
reason
changed_at
correlation/change_ref
```

Rollback:

```text
binding v3
→ switch to previously approved v2
```

No application deployment required.

---

## 16. Prompt Evaluation

Before activation, a prompt version SHOULD be evaluated with fixed golden cases.

P5 baseline evaluation dimensions:

```text
schema conformance
intent/plan correctness
hallucinated authoritative IDs
unsupported capability generation
clarification correctness
prompt-injection resistance
token/latency bounds
regression against prior prompt version
```

The evaluation result SHALL be tied to prompt version hash.

---

## 17. Prompt Injection / Untrusted Context Boundary

System/developer prompt templates are trusted control text.

User prompt, retrieved evidence, document text and model-generated candidates are untrusted data.

Renderer MUST maintain clear separation:

```text
trusted system/developer instructions
+
typed/bounded context sections
+
untrusted user/evidence payload
```

Retrieved evidence MUST NOT be concatenated into the system instruction layer as trusted instructions.

---

## 18. Prompt Provenance in P5 Artifacts

P5 records SHALL include prompt provenance when LLM was involved.

### WorkIntent provenance

```text
prompt_template_version_id
prompt_hash
model_profile/ref
input_context_hash
output_hash
```

### AgentPlan provenance

Same pattern plus:

```text
capability_catalog_snapshot_ref/hash
```

### Result synthesis provenance

References input StepResult set hash.

This allows:

```text
same input
+ same prompt version
+ same model profile
```

to be audited even though LLM output itself may remain non-deterministic.

---

## 19. Database Evolution

Existing tables are retained.

Recommended P5 changes:

### Modify PromptTemplateVersion write semantics

Change from mutable UPSERT to immutable INSERT-or-verify.

### Optional new table

```text
ae_prompt_binding_history
```

### Optional new table

```text
ae_prompt_evaluations
```

or equivalent evaluation evidence registry.

### Existing render event

`ae_prompt_render_events` remains useful, but P5 SHOULD extend metadata/projection to include:

```text
agent_execution_id
stage/purpose
work_intent_id
agent_context_id
agent_plan_id
model_profile_ref
```

without storing sensitive raw context.

---

## 20. Runtime Failure Semantics

Prompt binding/version problems fail closed in `required` planning mode.

Examples:

```text
binding missing
template version missing
version retired/disabled
content hash mismatch
required variable missing
output schema invalid
```

In planning `shadow` mode, failure may be recorded without replacing valid P4 response behavior.

---

## 21. P5 Acceptance Criteria

P5 prompt-control foundation is accepted when:

1. every LLM-dependent stage enabled by the selected P5 runtime mode resolves
   prompt content from the RDBMS Registry;
2. code contains only bootstrap seeds/fallbacks, not runtime-authoritative prompt text;
3. PromptTemplateVersion cannot be silently mutated;
4. binding activation and rollback do not require code deployment;
5. AgentExecution planning provenance records exact prompt version/hash;
6. retry/resume uses exact prior version unless explicit replan creates new provenance;
7. schema-invalid LLM output cannot pass deterministic validation;
8. fixed prompt golden tests pass;
9. prompt/evidence/user-data trust boundaries are tested.

Deterministic Intent Resolution and deterministic/template Plan Builder do not
resolve unused prompt purposes. Optional LLM Intent Resolution and Dynamic Plan
Builder remain disabled by default and are not required for P5 closure.

P5-S1 owns the existing Registry hardening required by items 2 through 6:

- version insert-or-verify instead of mutable version UPSERT;
- explicit binding history;
- exact enabled-stage execution provenance;
- conflict rejection for content/hash drift.

---

## 22. P6+ Reuse

The same Registry SHALL later manage prompts for:

```text
Skill selection
approval explanation
reconciliation assistance
result synthesis
background Agent planning
```

but the deterministic authority boundaries remain unchanged.

> Prompt templates are governed configuration and execution provenance, not hidden source-code behavior.
