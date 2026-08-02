# Slice 0007 CX Generation Facade To MO

Status: Implemented.

Backlog candidate: `S1-007` CX generation facade to MO mock.

Requirement coverage: `CX-FR-007`, `MO-FR-002`.

## Scope

Slice 0007 adds the first CX-mediated generation path:

- `services/nex-cx/nex_cx/generation.py`.
- `POST /api/v1/generations` on `nex-cx`.
- `GET /api/v1/generations/{cx_generation_id}` on `nex-cx`.
- `HttpMoGenerationClient` for MO calls by alias.
- In-memory generation execution records for local mock development.
- `contracts/schemas/generation/cx_generation_execution_record.v1.schema.json`.
- Positive and negative CX generation execution record fixtures.

The CX record stores safe request/response metadata: hashes, route metadata,
usage, output hash, and short output preview. It does not store raw provider
URLs, model paths, provider endpoints, API keys, or raw prompt text.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation with CX generation fixtures
```

## Follow-Up

Slice 0008 should add an AE API chat interaction stub that calls the CX
generation facade instead of calling MO directly.
