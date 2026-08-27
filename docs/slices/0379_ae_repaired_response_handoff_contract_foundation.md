# Slice 0379: AE Repaired Response Handoff Contract Foundation

## Scope

Freeze the first AE-facing handoff shape for repaired generation responses
before adding storage or route implementation. The handoff consumes CX
remediation execution detail records only when their
`cx_repaired_generation_lineage.v1` block is `LINKED`, then exposes a safe
review package for AE chat surfaces.

## Changes

- Added `ae_repaired_response_handoff.v1` JSON Schema, positive example, and a
  negative raw-output fixture.
- Added `nex_ae_api.repaired_responses` with deterministic handoff id
  generation, lineage validation, presentation-mode selection, actor-scope
  fallback, and redaction guards.
- Added future AE OpenAPI paths for creating and reading repaired response
  handoffs under a chat interaction.
- Documented the contract in the AE API README and the slice index.

## Boundary

The handoff stores only IDs, actor refs, CX lineage refs, response hash, short
preview, usage metadata, quality summary, links, and redaction flags. It does
not store raw prompts, raw generation output, source text, evidence text,
provider endpoints, model paths, API keys, passwords, storage paths, or local
filesystem paths. The original CX generation is never mutated.

## Evidence

- Regression coverage validates the builder, schema example, invalid lineage
  states, redaction failures, nullable output refs, helper edge cases, and
  OpenAPI contract shape.
- No PostgreSQL smoke is required in this slice because the runtime route and
  persistence adapter remain deferred.
