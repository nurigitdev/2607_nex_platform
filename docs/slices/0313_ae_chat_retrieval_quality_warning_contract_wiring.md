# Slice 0313: AE Chat Retrieval-Quality Warning Contract Wiring

## Scope

Wire CX retrieval-quality warning metadata into AE chat records and the AE-to-CX
generation handoff.

This slice does not change database schema, remote provider configuration, or
the CX retrieval/generation APIs. It adds a user-facing AE contract layer on top
of retrieval package warnings and evidence quality flags.

## Implemented

- Added `ae_chat_retrieval_quality_warning.v1`.
- Added `retrieval_quality_warning_contract` in `nex_ae_api.chat`.
- Added `retrieval.quality_warnings` to `ae_chat_interaction.v1`.
- Sanitized AE chat `retrieval.warnings` to warning kinds instead of raw warning
  detail strings such as `tokenizer_fallback_used:<document_id>`.
- Added generation handoff metadata:
  - `retrieval_warning_count`;
  - `retrieval_warning_kinds`;
  - `retrieval_quality_flag_kinds`;
  - `retrieval_quality_recommended_action`.
- Mapped quality actions:
  - `proceed`;
  - `proceed_with_caveat`;
  - `ask_confirmation`;
  - `show_no_answer`;
  - `show_error`.
- Updated grounded and no-answer AE chat contract examples.

## Runtime Behavior

AE chat now keeps backward-compatible `retrieval.warnings`, but the values are
safe warning kinds. The detailed structured contract lives under
`retrieval.quality_warnings`.

The same normalized warning contract is used when AE attaches a retrieval
package to a CX generation request, so the chat response and generation metadata
agree on caveat handling.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ae_chat.py -q`
- Contract validation:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted result:

```text
30 passed, 1 warning
```

Observed contract validation result:

```text
21 passed
```

Observed full quality gate:

```text
2157 passed, 1 warning
statement_coverage=98.50% threshold=95.00%
branch_coverage=95.30% threshold=85.00%
contract_validation=pass schemas=50 examples=81 negative_examples=56 openapi=7
```
