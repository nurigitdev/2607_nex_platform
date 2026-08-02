# Slice 0047 CX Generation Failure Lineage Stub

Status: Implemented.

Backlog candidate: `S5-007` CX generation failure record and recovery lineage
stub.

Requirement coverage: `CX-FR-008`, `AEAPI-FR-005`, `AG-FR-003`,
`TRACE-GEN-001`, `PLAT-FR-007`.

## Scope

Slice 0047 records generation failures that occur after CX has packaged a safe
MO request:

- `cx_generation_execution_record.v1` now supports optional `failure` and
  `recovery_lineage` objects.
- MO timeout and request failure paths save a redacted `FAILED` CX execution
  record even when the POST response remains problem+json.
- Failure timelines are persisted with `generation.failed` progress events.
- Recovery policy ID/hash, default action, retryability, attempt number, and
  retrieval reuse intent are visible without raw prompt, output, provider URL,
  API key, or model path leakage.
- Unknown failure codes still produce safe fallback lineage with `cancel` as
  the default recovery action.

The slice remains mock-first. It does not execute retries, repairs, or
regeneration; it freezes the data shape needed by later slices.

## Files

- `services/nex-cx/nex_cx/generation.py`
- `services/nex-cx/nex_cx/progress.py`
- `contracts/schemas/generation/cx_generation_execution_record.v1.schema.json`
- `contracts/examples/generation/cx_generation_execution_record.failed_policy_stub.json`
- `contracts/tests/negative/generation/cx_generation_execution_record.failure_raw_prompt_leak.json`
- `contracts/openapi/nex-cx.openapi.yaml`
- `tests/test_nex_cx_generation.py`
- `tests/test_nex_cx_progress.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_cx_generation.py tests/test_nex_cx_progress.py tests/test_contract_validation.py
scripts/quality/run_quality_gate.sh
```

Regression tests cover MO timeout failure record persistence, recovery policy
lineage selection, unknown failure fallback lineage, failed progress timeline
redaction, and positive/negative contract validation.
