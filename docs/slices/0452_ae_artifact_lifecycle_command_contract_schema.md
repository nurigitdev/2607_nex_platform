# Slice 0452: AE Artifact Lifecycle Command Contract Schema

## Scope

Define the AE artifact lifecycle command/result contract before repository and
API mutation wiring.

## Changes

- Added lifecycle action/result constants and transition helpers in
  `services/nex-ae-api/nex_ae_api/artifacts.py`.
- Added `ae_artifact_lifecycle_action.v1` and
  `ae_artifact_lifecycle_action_result.v1` JSON Schemas.
- Added positive contract examples for archiving a ready artifact.
- Added a negative contract example that rejects raw lifecycle comments.
- Extended AE artifact regression tests for action normalization, restore
  target handling, invalid transitions, idempotency, and redaction guards.

## Decisions

- The first lifecycle action set remains `ARCHIVE`, `RESTORE`, and
  `MARK_DELETED`.
- `RENDERING` artifacts cannot be archived or marked deleted by the lifecycle
  contract. In-flight render work should finish or fail before lifecycle
  actions hide the artifact.
- `RESTORE` may target `DRAFT`, `READY`, or `FAILED`; when no restore target is
  supplied, the contract defaults to `READY`.
- Lifecycle comments are represented by hash and length only. Raw comment text
  is not part of the persisted or browser/operator contract.
- Lifecycle result metadata explicitly records that rendered payloads, storage
  locations, and physical deletion are not included or executed.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
