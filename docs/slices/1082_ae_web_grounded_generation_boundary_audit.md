# Slice 1082: AE Web Grounded Generation Boundary Audit

## Goal

Freeze the S109 browser, AE orchestration, CX grounded-generation, provider,
ownership, privacy, lifecycle, and quality boundaries before replacing the
current local demo response path with the durable asynchronous runtime.

## Findings

- AE Web already has authenticated same-origin runtime composition, retrieval,
  quality-warning, citation-quality, repaired-response, artifact, and
  Playwright foundations.
- AE API already exposes owner-scoped asynchronous chat admission, progress,
  refresh, cancellation, retry, recovery, generated-response, and
  citation-quality routes.
- The current submit flow in `main.js` still fabricates assistant text,
  citation quality, repair data, and progress events locally. It can also start
  artifact export before a verified generated response is available.
- AE Web has no dedicated grounded-generation client or reusable lifecycle
  state/read model, so fetch mode cannot yet drive the complete async flow.

## Frozen Decisions

- The browser calls only the same-origin AE API. It never calls CX or MO
  directly and never receives service tokens, provider URLs, or database URLs.
- AE API owns orchestration and owner authorization, CX owns grounded
  generation and evidence lineage, and MO owns provider execution.
- The browser admits a chat interaction, polls bounded progress/refresh routes,
  and reads verified response and citation-quality projections from AE.
- Cancellation, retry, recovery, terminal failure, no-answer, and repair states
  are explicit user-visible lifecycle states rather than synthetic success.
- Artifact handoff starts only after verified generated-response completion.
- Existing AE/CX persistence is reused; S109 plans no new database table.
- Slice 1090 must exercise the browser against actual AE/CX test PostgreSQL and
  the protected live generation route through DGX.

## Slice Plan

1. `1082`: boundary audit and refactoring checkpoint.
2. `1083`: grounded-generation browser client adapter.
3. `1084`: lifecycle state and read-model foundation.
4. `1085`: authenticated runtime/client-registry composition.
5. `1086`: submission and bounded progress wiring with Checkpoint Gate.
6. `1087`: cancellation, retry, refresh, and recovery UX.
7. `1088`: verified response, citation-quality, repair, and artifact handoff.
8. `1089`: diagnostics, accessibility, and browser contract hardening.
9. `1090`: protected PostgreSQL, Playwright, and live DGX smoke evidence.
10. `1091`: S109 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py
```

The `nex-ae-web` Slice Gate profile selects the Python browser-smoke regression
suite while focused JavaScript modules remain covered by their Node tests. The
audit performs no database mutation, browser launch, or provider call.

## Observed Evidence

- Slice Gate: `273 passed`.
- Focused audit coverage: statement `100.00%`, branch `100.00%`.
- Contract Gate: `108` schemas, `166` positive examples, `129` negative
  examples, and `7` OpenAPI documents passed.
- Audit: foundations `6`, gaps `8`, open `8`, reproduced drifts `3`, issues
  `0`, next `1083`.
