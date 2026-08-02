# Slice 0008 AE API Chat Interaction Stub

Status: Implemented.

Backlog candidate: `S1-008` AE API chat interaction stub.

Requirement coverage: `AEAPI-FR-001`, `AEAPI-FR-003`.

## Scope

Slice 0008 adds the first AE API chat-to-CX path:

- `services/nex-ae-api/nex_ae_api/chat.py`.
- `POST /api/v1/chat/interactions`.
- `GET /api/v1/chat/interactions/{interaction_id}`.
- `HttpCxGenerationClient` for calling CX instead of MO.
- In-memory chat interaction records for local mock development.
- `contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json`.
- Positive and negative AE chat interaction fixtures.

The AE interaction record stores a user message hash, short preview, CX
generation reference, output preview, and usage summary. It does not include a
raw full user message field.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation with AE chat fixtures
```

## Follow-Up

Slice 0009 should add the AG readiness projection over service APIs.
