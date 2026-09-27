# Slice 1023: AE Intent and Execution-Mode Contract

## Goal

Make AE runtime intent resolution deterministic, explicit-mode-first, safe to
persist, and independent from post-execution prompt analytics.

## Implementation

- Add a pure `intent_policy` boundary with four canonical execution modes.
- Honor explicit execution mode before deterministic Korean/English fallback
  rules.
- Promote an otherwise general question to `GROUNDED_ANSWER` when retrieval is
  explicitly enabled.
- Record only intent labels, categories, confidence, reason, requirements, and
  a deterministic decision hash. Raw prompt text is excluded.
- Reject malformed generation/retrieval input and unsupported modes before any
  CX or provider call.

## Decisions

- Runtime intent selection and analytics classification remain separate
  responsibilities.
- `DOCUMENT_GENERATION` requires a template and retrieval. Summary and grounded
  answer require retrieval; general answer does not.
- Explicit mode wins even when prompt keywords or retrieval flags disagree.
- No database or remote provider is required for this contract Slice.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_intent_execution_mode_contract.py \
  --coverage-target scripts/smoke/run_ae_intent_execution_mode_contract.py \
  --smoke scripts/smoke/run_ae_intent_execution_mode_contract.py
```

## Observed Evidence

- Slice Gate: `2005 passed` with one known warning.
- Repository statement coverage: `97.76%`.
- Repository branch coverage: `95.58%`.
- Intent policy statement/branch coverage: `100%`/`100%`.
- Contract smoke: `10/10`; next Slice `1024`.
