# Slice 0034 Generation Compatibility Rule Contract

Status: Implemented.

Backlog candidate: `S4-004` generation compatibility rule contract.

Requirement coverage: `AEAPI-FR-002`, `CX-FR-007`, `TRACE-GEN-001`.

## Scope

Slice 0034 adds the cross-service compatibility rule foundation:

- Versioned `generation_compatibility_rule.v1` JSON Schema.
- Active mock rules for grounded answer, general answer, document summary, and
  report generation.
- Shared rule selection helper in `nex_runtime.compatibility`.
- AE and CX read-only debug endpoints:
  `/api/v1/compatibility/generation-rules`.
- Negative fixture for an unsupported provider capability.

This slice does not yet enforce compatibility in CX generation execution. That
runtime guard is intentionally left for Slice 0035.

## Files

- `services/_shared/nex_runtime/compatibility.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `services/nex-cx/nex_cx/main.py`
- `contracts/schemas/generation/generation_compatibility_rule.v1.schema.json`
- `tests/test_generation_compatibility.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover default rule selection, nested request key extraction,
inactive rule skipping, mismatch errors, invalid key errors, endpoint auth, and
contract validation.
