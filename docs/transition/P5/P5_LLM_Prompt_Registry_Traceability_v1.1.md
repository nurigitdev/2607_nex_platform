# P5 LLM Prompt Registry Traceability v1.1

**Status:** P5-CA01A TRACEABILITY BASELINE

| LLM Stage | Registry purpose | Candidate output | Deterministic gate |
|---|---|---|---|
| Intent Resolution | `intent_resolution` | WorkIntent candidate | schema + intent/entity policy |
| Context Candidate Extraction | `context_candidate_extraction` | selectors / parameter candidates | trusted resolver / context builder |
| Plan Builder | `plan_builder` | AgentPlan candidate | Plan Validator + Compiler |
| Clarification | `clarification` | user-safe questions | WAITING_INPUT rules |
| Result Synthesis | `result_synthesis` | response candidate | completion criteria / StepResult evidence |

## Provenance

```text
binding_key
→ exact version ID
→ bare content_sha256
→ bare rendered prompt digest
→ model profile/ref
→ output digest
→ semantic object provenance
```

## P5-S1 ownership

| Control | Slice |
|---|---|
| PromptTemplateVersion immutable insert-or-verify | S1 |
| shared bare/prefixed SHA utility | S1 |
| binding-history table/repository | S1 |
| history + pointer atomic transaction | S1 |
| lock/CAS concurrent activation | S1 |
| WorkIntent enabled-LLM provenance | S1 |

## Runtime isolation

Binding changes affect new resolutions only.

A previously created WorkIntent/AgentPlan does not change its prompt provenance when an operator moves a binding pointer.
