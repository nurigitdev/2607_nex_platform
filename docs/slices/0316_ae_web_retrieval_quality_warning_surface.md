# Slice 0316: AE Web Retrieval-Quality Warning Surface

## Scope

Add an AE Web client adapter and browser surface for the safe
`retrieval.quality_warnings` contract introduced in AE chat.

This slice does not change database schema, provider configuration, or live
smoke execution. It prepares the AE Web surface to show retrieval caveats
without rendering raw prompt text, source text, provider endpoints, or service
secrets.

## Implemented

- Added `ae_web_retrieval_quality_warning_surface.v1`.
- Added `buildRetrievalQualityWarningSurface`,
  `buildRetrievalQualityWarningSummary`, and
  `extractRetrievalQualityWarnings`.
- Mapped AE chat quality actions to deterministic browser state:
  - `proceed`;
  - `proceed_with_caveat`;
  - `ask_confirmation`;
  - `show_no_answer`;
  - `show_error`.
- Sanitized legacy warning arrays by keeping only warning kinds.
- Added a retrieval warning panel and assistant-message warning chip.
- Added safe preview summary wiring for retrieval quality warnings.

## Runtime Behavior

AE Web now accepts structured `quality_warnings` from future AE chat responses
or compatible retrieval results. During the transition period it also builds a
safe fallback from legacy `warnings`, `NO_ANSWER`, and unavailable retrieval
states.

The UI renders action, message, warning kind count, and quality flag kind count
only. It does not render raw warning detail suffixes, source text, prompt text,
provider endpoints, database endpoints, or local storage locations.

## Evidence

- AE Web targeted regression:
  `npm --prefix apps/nex-ae-web test`
- AE Web static regression:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
