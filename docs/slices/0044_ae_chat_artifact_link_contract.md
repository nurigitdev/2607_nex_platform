# Slice 0044 AE Chat Artifact Link Contract

Status: Implemented.

Backlog candidate: `S5-004` AE chat artifact link contract.

Requirement coverage: `AEAPI-FR-004`, `AEAPI-FR-005`, `AEAPI-FR-006`,
`AEWEB-FR-004`, `AG-FR-002`, `AG-FR-003`, `TRACE-AE-001`, `TRACE-GEN-001`.

## Scope

Slice 0044 makes generated artifacts attachable to chat interactions:

- `artifact_refs` becomes a first-class array in `ae_chat_interaction.v1`.
- Artifact ref objects include artifact/version IDs, display title, status,
  primary and available formats, preview/download AE routes, source generation
  ID, source content hash, quality summary, and allowed actions.
- `POST /api/v1/chat/interactions/{interaction_id}/artifact-links` attaches a
  rendered artifact snapshot to the matching chat interaction.
- `GET /api/v1/chat/interactions/{interaction_id}/artifact-links` lists the
  attached artifact refs.
- Contract fixtures cover empty refs, linked refs, and path-leak rejection.

This slice does not call the artifact store directly. It defines the stable chat
link contract and validates that the supplied artifact snapshot belongs to the
same chat document and interaction before attaching it.

## Files

- `services/nex-ae-api/nex_ae_api/chat.py`
- `services/nex-ae-api/README.md`
- `contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json`
- `contracts/examples/generation/ae_chat_interaction.artifact_linked.json`
- `contracts/tests/negative/generation/ae_chat_interaction.artifact_route_path_leak.json`
- `contracts/openapi/nex-ae-api.openapi.yaml`
- `tests/test_nex_ae_chat.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover default empty artifact refs, ref building from artifact
metadata, preview/download/action derivation, no raw path leakage, attach/list
route behavior, idempotent duplicate attachment, authentication, missing
interaction, chat document mismatch, interaction mismatch, missing current
version, and invalid artifact payloads.
