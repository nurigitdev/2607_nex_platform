# Slice 0029 Prompt Registry Seed Render Contract

Status: Implemented.

Backlog candidate: `S3-009` prompt registry seed and prompt render event
contract.

Requirement coverage: `CX-FR-003`, `AE-FR-002`, `TRACE-PLAT-001`.

## Scope

Slice 0029 adds prompt registry and render-event foundations:

- Shared in-memory prompt registry store for templates, versions, bindings, and
  render events.
- CX seed binding `cx.document_summary.default`.
- AE seed binding `ae.grounded_chat.default`.
- CX and AE read-only prompt debug endpoints:
  `/api/v1/prompts/bindings` and
  `/api/v1/prompts/render-events/{prompt_render_event_id}`.
- CX document summary jobs now render the bounded summary system prompt and
  attach prompt lineage/hash to summary metadata.
- DB seed migrations install the same default bindings into CX and AE schemas.
- Common `prompt_render_event.v1` contract captures prompt hashes, preview,
  variable keys, and lineage without storing raw user prompts.

## Files

- `services/_shared/nex_runtime/prompts.py`
- `services/nex-cx/nex_cx/prompts.py`
- `services/nex-ae-api/nex_ae_api/prompts.py`
- `database/nex-cx/migrations/0029_prompt_registry_seed.sql`
- `database/nex-ae-api/migrations/0029_prompt_registry_seed.sql`
- `contracts/schemas/common/prompt_render_event.v1.schema.json`
- `tests/test_prompt_registry.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover seed idempotency, CX/AE default bindings, prompt render
event hashing, missing binding/version/variable errors, prompt debug endpoints,
summary prompt lineage, DB seed migration checks, and contract validation.
