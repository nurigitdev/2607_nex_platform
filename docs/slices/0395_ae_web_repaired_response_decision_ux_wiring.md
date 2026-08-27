# Slice 0395: AE Web Repaired Response Decision UX Wiring

## Scope

Wire AE Web repaired response review card buttons to the repaired response
decision submit adapter. This Slice covers browser state transitions and
mock/fetch client handoff, not a new server persistence contract.

## Changes

- Added `apps/nex-ae-web/src/repairedResponseDecisionState.js`.
- Added `apps/nex-ae-web/test/repairedResponseDecisionState.test.mjs`.
- Wired `apps/nex-ae-web/src/main.js` review-card button clicks to
  `buildRepairedResponseDecisionRequest` and
  `repairedResponseDecisionClient.submitRepairedResponseDecision`.
- Added `READY_FOR_DECISION -> SUBMITTING -> RECORDED/FAILED` UI state
  transitions for repaired response decisions.
- Updated `apps/nex-ae-web/src/repairedResponseReviewCard.js` to render
  recorded decision IDs and failure statuses.
- Extended AE Web static policy tests with repaired response decision UX wiring
  anchors.

## Notes

The accept/keep buttons now submit through the configured AE Web client
registry. In mock mode the transition completes locally; in authenticated fetch
mode it posts to the same-origin AE API decision route.

Decision state remains browser-safe. The UI state never renders raw prompts,
raw generation output, raw source text, service tokens, provider URLs, database
URLs, or storage paths.

## Evidence

Targeted AE Web regression:

```text
node --test test/repairedResponseDecisionState.test.mjs test/repairedResponseReviewCard.test.mjs test/repairedResponseDecisionClient.test.mjs
14 passed
```

AE Web regression:

```text
npm --prefix apps/nex-ae-web test
138 passed
```

AE Web static policy regression:

```text
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
16 passed
```

Syntax checks:

```text
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/repairedResponseDecisionState.js
node --check apps/nex-ae-web/src/repairedResponseReviewCard.js
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2854 passed, 1 warning
statement_coverage=98.68%
branch_coverage=96.13%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

No PostgreSQL smoke is required for this Slice because it wires browser UX over
the previously added decision adapter without changing server persistence.
