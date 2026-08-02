# Slice 0019 AE Grounded Chat Retrieval Context

Status: Implemented.

Backlog candidate: `S2-009` AE grounded chat uses CX retrieval context.

Requirement coverage: `AE-RETRIEVAL-001`, `AE-CX-001`, `TRACE-PLAT-001`,
`CONTRACT-AE-001`, `GEN-BOUNDARY-001`.

## Scope

Slice 0019 connects AE chat interactions to CX retrieval packages:

- `POST /api/v1/chat/interactions` may include a `retrieval` object.
- When retrieval is enabled, AE calls CX retrieval before CX generation.
- AE injects the returned evidence into the CX generation request as a grounded
  user message.
- AE records a compact retrieval summary alongside the chat interaction record.
- If CX retrieval returns `NO_ANSWER`, AE stores a no-answer chat interaction and
  skips generation.
- Retrieval failures are surfaced as AE problem responses without storing partial
  generation records.

The generation request still preserves the existing AE-to-CX boundary: AE sends
only the grounded prompt package, hashes the original user message, and stores no
raw full user prompt in the public interaction record.

## Contract Artifacts

- `contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json`
- `contracts/examples/generation/ae_chat_interaction.mock_success.json`
- `contracts/examples/generation/ae_chat_interaction.grounded_success.json`
- `contracts/examples/generation/ae_chat_interaction.no_answer.json`
- `contracts/tests/negative/generation/ae_chat_interaction.raw_user_message_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover retrieval enable/disable selection, bad retrieval payload
shape, grounded prompt assembly, generation metadata enrichment, no-answer
short-circuiting, retrieval failure propagation, endpoint auth, storage readback,
and contract validation for non-retrieval, grounded, and no-answer chat records.
