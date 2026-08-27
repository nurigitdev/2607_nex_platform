# Slice 0393: AE Web Repaired Response Review Card Rendering

## Scope

Render browser-safe repaired response review surfaces inside the AE Web chat
interaction detail. Decision submission remains deferred to the next adapter
and UX wiring slices.

## Changes

- Added `apps/nex-ae-web/src/repairedResponseReviewCard.js`.
- Added card view-model, summary, and HTML rendering helpers for
  `ae_web_repaired_response_review_surface.v1`.
- Wired `apps/nex-ae-web/src/main.js` to render repaired response review cards
  on assistant messages.
- Added a safe mock repaired response review projection for the local browser
  shell.
- Added `apps/nex-ae-web/test/repairedResponseReviewCard.test.mjs`.
- Updated AE Web styling for review card layout, actions, secondary links, and
  mobile wrapping.

## Notes

Primary decision buttons are rendered as disabled in this Slice because the
decision submit client and click UX are intentionally deferred. The renderer
already carries stable `data-repaired-response-decision-action`,
`data-interaction-id`, `data-handoff-id`, and `data-decision-route` attributes
for the next Slice to wire.

The card renderer rejects unsafe payload fields and only renders safe summary
preview data. It does not render raw prompts, raw generation output, raw source
text, service tokens, provider URLs, database URLs, or storage paths.

## Evidence

Targeted AE Web regression:

```text
node --test test/repairedResponseReviewCard.test.mjs test/repairedResponseReviewClient.test.mjs
10 passed
```

AE Web regression:

```text
npm --prefix apps/nex-ae-web test
129 passed
```

AE Web static policy regression:

```text
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
15 passed
```

Syntax checks:

```text
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/repairedResponseReviewCard.js
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2853 passed, 1 warning
statement_coverage=98.68%
branch_coverage=96.13%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

No PostgreSQL smoke is required for this Slice because it adds browser-only
rendering over the previously exposed review projection surface.
