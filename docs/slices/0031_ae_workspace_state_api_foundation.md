# Slice 0031 AE Workspace State API Foundation

Status: Implemented.

Backlog candidate: `S4-001` AE workspace state API foundation.

Requirement coverage: `AEAPI-FR-001`, `AEWEB-FR-001`, `TRACE-AE-001`.

## Scope

Slice 0031 adds the first AE-owned workspace state surface:

- Workspace create/read API with tenant and owner scope.
- Korean-default runtime controls for the AE web shell.
- Stable chat document identity per workspace.
- Workspace activity readback with safe summary metadata.
- `ae_workspace_state.v1` contract and a negative raw prompt leak fixture.

The workspace record intentionally stores default controls and activity
summaries, not raw chat prompts or source document contents.

## Files

- `services/nex-ae-api/nex_ae_api/workspace.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `contracts/schemas/service/nex_ae_api/workspace_state.v1.schema.json`
- `tests/test_nex_ae_workspace.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover workspace creation, default runtime controls, owner
validation, invalid runtime payloads, activity readback, endpoint auth, missing
workspace responses, and contract validation.
