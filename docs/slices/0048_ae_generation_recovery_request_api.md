# Slice 0048 AE Generation Recovery Request API

Status: Implemented.

Backlog candidate: `S5-008` AE generation recovery request API.

Requirement coverage: `AEAPI-FR-005`, `CX-FR-008`, `AG-FR-003`,
`TRACE-GEN-001`, `PLAT-FR-007`.

## Scope

Slice 0048 adds an AE-owned recovery request envelope for failed generation
records:

- `ae_generation_recovery_request.v1` JSON Schema and fixtures.
- `POST /api/v1/recovery/generation-requests`.
- `GET /api/v1/recovery/generation-requests/{recovery_request_id}`.
- CX failed generation lookup through AE-to-CX service auth.
- Requested action validation against the shared recovery policy catalog.
- Safe dispatch metadata for retry, repair, regenerate, manual warning
  acceptance, and cancel actions.
- Policy hash status reporting as `MATCHED`, `STALE`, or `UNAVAILABLE`.

This slice does not execute the retry or repair. It stores the user/operator
intent as a separate immutable record so the failed generation and chat record
remain inspectable.

## Files

- `services/nex-ae-api/nex_ae_api/recovery_requests.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `contracts/schemas/service/nex_ae_api/generation_recovery_request.v1.schema.json`
- `contracts/examples/generation/ae_generation_recovery_request.retry_accepted.json`
- `contracts/tests/negative/generation/ae_generation_recovery_request.raw_prompt_field.json`
- `contracts/openapi/nex-ae-api.openapi.yaml`
- `tests/test_nex_ae_recovery_requests.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_ae_recovery_requests.py tests/test_contract_validation.py
scripts/quality/run_quality_gate.sh
```

Regression tests cover accepted retry requests, readback, auth, invalid/non
failed sources, disallowed actions, unknown-policy cancel fallback, stale policy
hash detection, safe changed field filtering, and CX lookup error mapping.
