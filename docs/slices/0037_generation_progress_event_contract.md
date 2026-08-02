# Slice 0037 Generation Progress Event Contract

Status: Implemented.

Backlog candidate: `S4-007` Generation progress event contract and CX polling
timeline.

Requirement coverage: `CX-FR-008`, `PLAT-FR-005`, `AEAPI-FR-005`,
`AEWEB-FR-003`, `AG-FR-003`, `TRACE-GEN-001`.

## Scope

Slice 0037 adds the first polling-oriented generation progress event spine:

- `generation_progress_event.v1` JSON Schema with safe event envelope fields.
- Positive and negative contract fixtures for progress events.
- CX generation timeline construction for successful mock generation.
- Redacted event details with IDs, hashes, counts, statuses, and safe usage
  summaries only.
- CX polling endpoint:
  `/api/v1/generations/{cx_generation_id}/events`.

The current implementation records the CX-owned stages for request acceptance,
retrieval package validation, prompt packaging, MO completion, draft validation,
citation validation, and completion. Streaming and AE artifact render events are
left to later slices, but they use the same envelope.

## Files

- `services/nex-cx/nex_cx/progress.py`
- `services/nex-cx/nex_cx/generation.py`
- `contracts/schemas/generation/generation_progress_event.v1.schema.json`
- `tests/test_nex_cx_progress.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover deterministic event IDs, event enum validation, stage
validation, progress percent bounds, safe detail redaction, grounded timeline
readback, general-answer retrieval skipping, auth failure, missing generation
handling, and contract validation.
