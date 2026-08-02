# Slice 0046 Generation Recovery Policy Contract

Status: Implemented.

Backlog candidate: `S5-006` Generation recovery policy contract.

Requirement coverage: `AEAPI-FR-005`, `AG-FR-002`, `AG-FR-003`,
`AG-FR-005`, `CX-FR-008`, `MO-FR-003`, `TRACE-GEN-001`, `PLAT-FR-007`.

## Scope

Slice 0046 freezes the first shared recovery policy contract:

- `generation_recovery_policy.v1` JSON Schema.
- Positive fixture for AE render retry policy.
- Negative fixture preventing raw prompt metadata leakage.
- Shared `nex_runtime.recovery` catalog and selector helpers.
- AE and CX read APIs:
  `/api/v1/recovery/generation-policies` and
  `/api/v1/recovery/generation-policies/{failure_code}`.
- Recovery policies for provider timeout retry, citation validation repair,
  artifact render retry, and low-confidence fresh retrieval regeneration.

The catalog is read-only and mock-first. It records owner service, failure code,
default action, allowed actions, retryability, lineage type, retrieval/source
hash preservation rules, progress event types, and redaction-safe metadata.

## Files

- `services/_shared/nex_runtime/recovery.py`
- `services/_shared/nex_runtime/__init__.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `services/nex-cx/nex_cx/main.py`
- `contracts/schemas/generation/generation_recovery_policy.v1.schema.json`
- `contracts/examples/generation/generation_recovery_policy.render_retry.json`
- `contracts/tests/negative/generation/generation_recovery_policy.raw_prompt_leak.json`
- `contracts/openapi/nex-ae-api.openapi.yaml`
- `contracts/openapi/nex-cx.openapi.yaml`
- `tests/test_generation_recovery_policy.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover policy selection, inactive policy skip, invalid failure
code validation, policy hash stability, allowed action checks, AE/CX route
authentication, expected audience enforcement, missing policy errors, and
redaction of prompt/provider/path fields.
