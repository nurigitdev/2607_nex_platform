# P6.5-S4 Live Plan Candidate Generation

**Status:** IMPLEMENTED
**Date:** 2026-10-16
**Predecessor:** P6.5-S3 Live Context Candidate Extraction

## Scope

P6.5-S4 activates only the PLAN semantic stage:

```text
WorkIntent + AgentContext + CapabilitySnapshot summary
-> exact ae.plan_builder.default/v1 binding snapshot
-> thin AE-to-MO generation client
-> closed PlanCandidate JSON
-> schema, authority, privacy, injection, and dependency validation
-> model-revision calibration
-> exact deterministic capability binding
-> canonical AgentPlan in required mode only
```

This Slice does not persist candidates, add a database migration, wire the
stage into the chat route, resume interrupted stages, run PlanValidation or
compilation, or create RuntimeJobs. P6.5-S5 owns persistence, route
orchestration, resume, validation/compile integration, and full three-stage
composition.

## Structure

- `plan_candidate_generation.py` owns the closed request projection, prompt
  snapshot, generation, strict parser, dependency checks, calibration
  decision, model-lineage check, exact capability binder, and AgentPlan handoff.
- `agent_plans.py` remains the canonical AgentPlan contract and semantic-hash
  authority; S4 does not introduce a competing plan representation.
- `planning_capabilities.py` remains the trusted exact-version source for P5
  capabilities and P6 LOCAL_SKILL descriptors.
- `semantic_candidates.py` remains the shared INTENT/CONTEXT/PLAN calibration
  registry and fail-closed stage error boundary.
- `prompts.py` seeds the immutable PLAN binding through existing Prompt
  Registry insert-or-verify behavior.

No database migration is required.

## Prompt And Input Boundary

S4 adds this exact immutable prompt identity:

```text
binding_key = ae.plan_builder.default
purpose = plan_builder
version = v1
role = system
candidate_schema = p65.plan_candidate.v1
```

The stage captures binding ID, template version ID/version, content SHA-256,
rendered prompt hash, and input-context hash before provider execution. An
in-flight stage is isolated from a later binding pointer change.

The generation input contains only:

```text
bounded WorkIntent planning projection
AgentContext semantic summary and context hash
capability IDs, admitted logical step types, and operation semantics
```

It excludes tenant/principal identity, project or resource authority, exact
capability and Skill versions, executor kinds, package trust, provider
configuration, API keys, endpoints, model paths, raw private context, and
hidden reasoning.

## Candidate Contract

The strict parser accepts only:

```text
schema_version
suggested_plan_kind
goal
logical_steps[]
completion_mapping[]
confidence
```

It enforces the frozen JSON Schema bounds plus unique IDs, a serial acyclic
topological graph, existing dependencies, terminal REPORT steps, terminal-only
completion mappings, exact WorkIntent goal and criterion coverage, canonical
JSON, and prompt-injection rejection. Unknown fields, malformed JSON,
authority-bearing fields, private configuration fields, `DELEGATE_WORK`, and
model-authored `LOCAL_SKILL` fail closed.

## Trusted Binding Boundary

PlanCandidate is suggestion data only. The model may propose a logical
`LOCAL_CAPABILITY` capability ID, but it cannot choose:

```text
exact capability or Skill version
executor kind or backend profile
package or trust admission
tenant, principal, project, role, or permission authority
WRITE, approval, or delegation authority
```

AE resolves each hint against the captured CapabilitySnapshot. Exactly one
admitted version must exist. A P6 LOCAL_SKILL descriptor is selected by its
capability ID but remains a canonical `LOCAL_CAPABILITY` logical step; AE adds
its exact version and output contract. REPORT binds to the exact deterministic
report capability and source-step refs.

The AgentPlan records the PlanCandidate semantic hash as a non-authoritative
route decision reference while keeping the raw candidate payload outside the
canonical plan. AgentPlan source references point to the exact WorkIntent,
AgentContext, and CapabilitySnapshot versions and hashes.

## Current Capability Truth

The frozen candidate schema recognizes `AGGREGATE`, but the current P5
PlanValidation profile has no admitted deterministic aggregate capability.
S4 therefore parses the value as schema-known and rejects it during trusted
binding with `CANDIDATE_CAPABILITY_UNKNOWN`. `DYNAMIC` is likewise schema-known
but unavailable in the current P5 runtime. Neither case is silently converted
or guessed.

Currently active S4 paths are:

```text
DIRECT: exactly one LOCAL_CAPABILITY step
KNOWN_TEMPLATE: serial LOCAL_CAPABILITY and optional terminal REPORT steps
```

## Admission And Failure Semantics

Required mode selects calibration by the exact tuple:

```text
PLAN + model_profile + model_ref
```

Missing calibration fails closed. Candidate confidence below the selected
threshold returns `REPLAN_REQUIRED` with no AgentPlan. Shadow mode returns
`SHADOW_ONLY` with no AgentPlan. Required mode returns `CONTINUE` only after
strict candidate validation, exact capability binding, source-lineage
validation, and canonical AgentPlan hash validation.

Readiness and generation must retain the same model profile, model revision,
deployment, and route.

## Protected Live Smoke

The opt-in smoke runs through the actual MO generation path:

```bash
NEX_AE_P65_S4_LIVE_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_p65_s4_live_plan_candidate_smoke.py \
  --summary --output /tmp/p65-s4-live-plan-evidence.json
```

The first protected attempts correctly failed closed when the model returned
`completion_mapping` as an object map and then copied WorkIntent criterion
objects into step `completion_criteria`. The v1 prompt was clarified, without
weakening the frozen schema, to require an item array for completion mapping
and plain-string arrays for step-local completion criteria.

Observed accepted result:

```text
provider model revision = Qwen3.5-4B
candidate confidence = 0.95
selected provisional threshold = 0.50
plan kind = DIRECT
canonical AgentPlan steps = 1
directive = CONTINUE
checks = 13/13 PASS
```

The threshold is smoke-only and does not claim production calibration.

The evidence excludes endpoint, API key, service token, raw prompt, raw
provider output, raw candidate, hidden reasoning, tenant ID, and owner subject
ID. Sanitized evidence belongs under:

```text
reports/live/p65-s4-live-plan-evidence.json
```

## Verification

```text
Focused S4 module/smoke tests: 46 passed
Focused S4/Prompt persistence suite: 67 passed
Affected P4/P5/P6/P6.5 regression: 764 passed, 5 protected-smoke skips
AE Slice Gate: PASS (4,220 passed, 10 protected-smoke skips)
AE Slice Gate statement coverage: 98.61%
AE Slice Gate branch coverage: 96.82%
PLAN module statement coverage: 98.36%
PLAN module branch coverage: 96.43%
Protected smoke script statement/branch coverage: 100.00% / 100.00%
Contract validation: PASS (174 schemas, 236 examples, 204 negative examples,
7 OpenAPI documents)
Protected live provider smoke: PASS (13/13 checks)
```

The ten Slice Gate skips are existing opt-in PostgreSQL/live smoke tests. The
S4 provider smoke was executed separately against the protected live path.

## Exit

P6.5-S4 is closed when a real LLM can propose a bounded logical plan while only
AE may bind exact versions, assign executable semantics, preserve source
lineage, and create canonical AgentPlan. P6.5-S5 may then compose deterministic
admission, persistence, PlanValidation, and compilation without widening model
authority.
