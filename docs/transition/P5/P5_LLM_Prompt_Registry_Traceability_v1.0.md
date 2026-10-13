# P5 LLM Prompt Registry Traceability v1.0

**Status:** P5-CA01 REVIEWED TRACEABILITY BASELINE

Only LLM stages enabled by the selected P5 runtime mode require an active
runtime binding. Optional LLM intent and dynamic planning remain disabled by
default; deterministic stages do not resolve unused prompt purposes.

| LLM Stage | Registry Purpose | Output | Deterministic Gate |
|---|---|---|---|
| Intent Resolution | `intent_resolution` | IntentCandidate / WorkIntent candidate | schema + intent/entity policy |
| Context Candidate Extraction | `context_candidate_extraction` | selectors / parameter candidates | trusted resolver / context builder |
| Plan Builder | `plan_builder` | AgentPlan candidate | Plan Validator + Deterministic Compiler |
| Clarification | `clarification` | user-safe questions | wait reason / unresolved selector validation |
| Result Synthesis | `result_synthesis` | final response candidate | completion criteria / StepResult evidence |

## Required Provenance Chain

```text
binding_key
→ prompt_template_version_id
→ content_sha256
→ rendered_prompt_hash
→ model_profile/ref
→ output_hash
→ WorkIntent / AgentPlan / AgentResult provenance
```

## Main P5 Controls

```text
Prompt version immutable
No implicit latest
Binding is explicit mutable deployment pointer
Retry uses exact captured version
Binding rollback requires no source deployment
LLM output remains candidate, never execution authority
```

## Current Source Reuse

Existing:

```text
ae_prompt_templates
ae_prompt_template_versions
ae_prompt_bindings
ae_prompt_render_events
SqlAlchemyAePromptRegistryStore
PromptSeed
```

P5 hardening:

```text
mutable version UPSERT → immutable insert/verify
source seed authority → bootstrap only
add execution-stage provenance
add binding-history/evaluation evidence
```

## Slice Ownership

| Control | Owning Slice |
|---|---|
| immutable version insert-or-verify | P5-S1 |
| explicit binding history | P5-S1 |
| WorkIntent enabled-LLM provenance | P5-S1 |
| AgentPlan enabled-LLM provenance | P5-S3 when optional dynamic planning is enabled |
| result synthesis provenance | P5-S8 when an LLM synthesis path is enabled |

No optional LLM stage may be enabled before the P5-S1 immutability and exact
binding controls pass.
