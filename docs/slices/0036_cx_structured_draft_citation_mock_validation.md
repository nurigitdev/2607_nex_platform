# Slice 0036 CX Structured Draft Citation Mock Validation

Status: Implemented.

Backlog candidate: `S4-006` CX structured draft and citation mock validation.

Requirement coverage: `CX-FR-008`, `AEAPI-FR-004`, `TRACE-GEN-001`.

## Scope

Slice 0036 adds CX structured draft foundations:

- Mock structured draft construction from MO generation output.
- Output hash and short preview storage instead of full raw output exposure.
- Citation label parsing for `[1]`-style claims.
- Citation validation against the referenced retrieval package evidence.
- Structured draft read endpoint:
  `/api/v1/generations/{cx_generation_id}/structured-draft`.
- `cx_structured_draft.v1` contract and raw output leak negative fixture.

Validation failures are recorded in the draft status for now. Recovery and
repair behavior is left for later slices.

## Files

- `services/nex-cx/nex_cx/drafts.py`
- `services/nex-cx/nex_cx/generation.py`
- `contracts/schemas/generation/cx_structured_draft.v1.schema.json`
- `tests/test_nex_cx_drafts.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover citation parsing, duplicate citation de-duplication,
valid citation mapping, missing required citations, missing retrieval package,
evidence mismatch, structured draft endpoint readback, and contract validation.
