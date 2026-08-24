# Slice 0335: AG Generation Quality Operator Disposition Foundation

## Scope

Create the AG-side foundation for recording how an operator disposes of a
generation quality issue after AE user feedback and AG quality projections flag
attention.

## Implemented

- Added `generation_quality_disposition` domain helpers for:
  - operator action validation;
  - disposition status derivation;
  - reason-code normalization;
  - quality issue reference validation;
  - deterministic disposition ids;
  - in-memory persistence for route-level regression wiring.
- Preserved operator privacy by accepting `operator_note` only as:
  - `operator_note_hash`;
  - bounded `operator_note_preview`.
- Added a redaction guard for raw prompts, raw output, raw text, tokens, API
  keys, and raw operator notes.
- Added contract schema, positive example, and negative example:
  - `ag_generation_quality_operator_disposition.v1`;
  - `ag_generation_quality_operator_disposition.needs_cx_repair`;
  - `ag_generation_quality_operator_disposition.raw_note_field`.
- Registered the new examples in the contract validation indexes.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_quality_disposition.py -q
27 passed in 0.07s
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=54 examples=86 negative_examples=63 openapi=7
```

No PostgreSQL smoke is attached to this slice because this is the contract and
domain foundation. Persistence smoke follows in a later slice.
