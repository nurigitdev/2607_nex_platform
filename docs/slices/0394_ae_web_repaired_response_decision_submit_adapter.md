# Slice 0394: AE Web Repaired Response Decision Submit Adapter

## Scope

Add the AE Web client adapter for submitting repaired response accept/keep
decisions to the existing AE API decision route. Browser click handling remains
deferred to the next UX wiring Slice.

## Changes

- Added `apps/nex-ae-web/src/repairedResponseDecisionClient.js`.
- Added safe request construction from
  `ae_web_repaired_response_review_surface.v1`.
- Added mock and fetch decision submit clients for
  `POST /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{handoff_id}/decisions`.
- Registered `repairedResponseDecisionClient` in `src/clientRegistry.js`.
- Added `apps/nex-ae-web/test/repairedResponseDecisionClient.test.mjs`.
- Extended client registry tests to cover mock/fetch decision submit wiring.
- Exposed `workspaceState.repairedResponseDecisionClient` for the following UX
  wiring Slice.

## Notes

The adapter carries tenant/workspace/owner/chat/handoff scope from the review
surface and builds a `chat_review` actor claim by default. Decision comments are
client-side limited to the AE API contract maximum of 240 characters.

The adapter rejects sensitive payload keys before submit and normalizes AE API
decision records into safe browser result summaries. It does not render or
persist raw prompts, raw generation output, raw source text, service tokens,
provider URLs, database URLs, or storage paths.

## Evidence

Targeted AE Web regression:

```text
node --test test/repairedResponseDecisionClient.test.mjs test/clientRegistry.test.mjs
8 passed
```

AE Web regression:

```text
npm --prefix apps/nex-ae-web test
134 passed
```

AE Web static policy regression:

```text
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
15 passed
```

Syntax checks:

```text
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/repairedResponseDecisionClient.js
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2853 passed, 1 warning
statement_coverage=98.68%
branch_coverage=96.13%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

No PostgreSQL smoke is required for this Slice because it adds the browser
client adapter over the already-smoked AE decision API route without changing
server persistence.
