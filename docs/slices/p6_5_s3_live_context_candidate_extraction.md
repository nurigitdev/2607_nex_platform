# P6.5-S3 Live Context Candidate Extraction

**Status:** IMPLEMENTED
**Date:** 2026-10-16
**Predecessor:** P6.5-S2 Live Intent Candidate Generation

## Scope

P6.5-S3 activates only the CONTEXT semantic stage:

```text
WorkIntent + closed Base Context
-> exact ae.context_candidate_extraction.default/v1 binding snapshot
-> thin AE-to-MO generation client
-> closed ContextCandidateSet JSON
-> schema, authority, privacy, and injection validation
-> model-revision calibration
-> bounded ContextCandidateHints
-> existing TrustedContextResolver
-> canonical AgentContext in required mode only
```

This Slice does not add a candidate table, persist candidate payloads, wire the
stage into the chat route, resume the three-stage pipeline, or create an
AgentPlan. P6.5-S5 owns persistence, route orchestration, resume, and stage
composition.

## Structure

- `context_candidate_generation.py` owns the closed request projection,
  prompt snapshot, generation, strict candidate parser, admission decision,
  model-lineage check, and trusted-resolver handoff.
- `agent_context.py` accepts an optional normalized `ContextCandidateHints`
  projection in `ContextBuildRequest`; AgentContext serialization and hashing
  remain unchanged.
- `semantic_candidates.py` remains the shared INTENT/CONTEXT/PLAN calibration
  registry and fail-closed stage error boundary.
- `prompts.py` seeds the immutable CONTEXT binding through the existing Prompt
  Registry insert-or-verify behavior.

No database migration is required.

## Prompt And Input Boundary

S3 adds this exact immutable prompt identity:

```text
binding_key = ae.context_candidate_extraction.default
purpose = context_candidate_extraction
version = v1
role = system
candidate_schema = p65.context_candidate_set.v1
```

The stage captures binding ID, template version ID/version, content SHA-256,
rendered prompt hash, and input-context hash before provider execution. An
in-flight stage is therefore isolated from a later binding pointer change.

Only these Base Context fields are admitted:

```text
interaction_text
conversation_summary
resource_label_hints[]
```

The WorkIntent projection contains its semantic hash and bounded planning
fields. Provider configuration, API keys, endpoints, model paths, hidden
reasoning, and trusted authority objects are outside the generation input.

## Candidate Contract

The strict parser accepts only:

```text
schema_version
entity_candidates[]
retrieval_hints[]
resource_selectors[]
parameter_candidates[]
confidence
```

It enforces the frozen JSON Schema shape, field and collection bounds, unique
candidate identities, finite confidence and parameter scalars, enumerated
resource types and selector kinds, canonical JSON, and prompt-injection
rejection. Unknown fields, malformed JSON, authority-bearing fields, and
private configuration fields fail closed.

## Authority Boundary

ContextCandidateSet is suggestion data only. It cannot establish:

```text
tenant or principal identity
owner visibility
project authority
role or permission
data classification
resource admission
```

The validated candidate becomes a copied, bounded `ContextCandidateHints`
projection passed only to `TrustedContextResolver`. The resolver remains the
sole canonical source for identity scope, authority, project resolution,
retrieval/evidence references, conflicts, degradations, and context manifest.
Neither the raw candidate nor its hash is copied into AgentContext.

## Admission And Failure Semantics

Required mode selects calibration by the exact tuple:

```text
CONTEXT + model_profile + model_ref
```

Missing calibration fails closed. Candidate confidence below the selected
threshold returns `CONTEXT_REFRESH_REQUIRED` with no AgentContext. Shadow mode
returns `SHADOW_ONLY` with no AgentContext. Required mode returns `CONTINUE`
only after successful trusted resolution.

Readiness and generation must retain the same model profile, model revision,
deployment, and route. Expected AgentContext validation failures map to
`TRUSTED_CONTEXT_RESOLUTION_FAILED`; an unexpected resolver failure maps to a
retryable `TRUSTED_CONTEXT_RESOLVER_UNAVAILABLE` without exposing internals.

## Protected Live Smoke

The opt-in smoke runs through the actual MO generation path:

```bash
NEX_AE_P65_S3_LIVE_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_p65_s3_live_context_candidate_smoke.py \
  --summary --output /tmp/p65-s3-live-context-evidence.json
```

The first protected attempts correctly failed closed when live output violated
the frozen shape. The v1 prompt was clarified, without weakening the schema,
to require array collections, per-item confidence, enumerated resource types,
and distinct entity/resource selector kinds.

Observed accepted result:

```text
provider model revision = Qwen3.5-4B
candidate confidence = 0.90
selected provisional threshold = 0.50
directive = CONTINUE
checks = 11/11 PASS
```

The threshold is smoke-only and does not claim production calibration. The
evidence excludes endpoint, API key, service token, raw prompt, raw provider
output, raw candidate, hidden reasoning, tenant ID, and owner subject ID. The
sanitized evidence is stored at:

```text
reports/live/p65-s3-live-context-evidence.json
```

## Verification

```text
Focused smoke tests: 7 passed
Focused S3/AgentContext/Prompt suite: 159 passed
Affected P6.5/Intent/WorkIntent/Context/Prompt/Runtime regression: 395 passed
AE Slice Gate: PASS (4,174 passed, 10 protected-smoke skips)
AE Slice Gate statement coverage: 98.62%
AE Slice Gate branch coverage: 96.83%
CONTEXT module statement coverage: 99.37%
CONTEXT module branch coverage: 98.41%
AgentContext statement/branch coverage: 100.00% / 100.00%
Protected smoke script statement/branch coverage: 100.00% / 100.00%
Contract validation: PASS (174 schemas, 7 OpenAPI documents)
Protected live provider smoke: PASS (11/11 checks)
```

The ten Slice Gate skips are pre-existing opt-in PostgreSQL/live smoke tests;
the S3 provider smoke was executed separately against the protected live path.

## Exit

P6.5-S3 is closed. A real LLM can propose bounded CONTEXT hints, but only the
trusted resolver can produce AgentContext or assign any context authority.
P6.5-S4 may now add PLAN candidate generation without weakening this boundary.
