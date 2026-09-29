# Slice 1090: AE Web Grounded Generation Playwright PostgreSQL Smoke

## Goal

Prove one correlated grounded-generation request through the authenticated AE
Web browser surface, actual AE/CX test databases, the asynchronous CX worker,
and all three live DGX providers.

## Implementation

- Added safe browser bootstraps for the persisted document, workspace, and
  chat-document identities used by protected smoke execution.
- Replaced demo interaction identifiers with browser-generated UUIDs and made
  missing secure UUID support fail closed.
- Added a protected Playwright runner that signs in, submits one grounded
  request, observes progress, refreshes durable state, and reads the verified
  response and citation-quality workflow through same-origin AE API routes.
- Added an opt-in Python orchestrator that migrates the actual AE/CX test
  databases, prepares a real CX document and indexes, runs the asynchronous CX
  generation worker, records provider telemetry, verifies persistence, and
  removes probe data.
- Disabled model reasoning for this bounded generation path so the configured
  output budget is used for the owner-visible grounded answer.
- Hardened failed-smoke cleanup to remove retrieval packages by document
  lineage before deleting the underlying CX content object, and to remove stale
  S109-owned AE chat/runtime probes before a protected rerun.
- Fixed the AE citation-quality projection to accept the promoted top-level
  retrieval-package identity produced by the persisted CX read model. The
  protected smoke exposed this real lineage defect before the fix.

The smoke is skipped unless
`NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_POSTGRES_SMOKE=1` is explicitly
set. It requires the `nex_ae_test` and `nex_cx_test` targets, an installed
Chromium executable, and the protected live provider profile.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ae_citation_quality_workflow.py \
  tests/test_nex_ae_chat.py \
  tests/test_ae_async_chat_refresh.py \
  tests/test_ae_web_grounded_generation_playwright_postgres_smoke.py
node --test \
  apps/nex-ae-web/test/groundedGenerationWorkflow.test.mjs \
  apps/nex-ae-web/test/groundedGenerationPlaywrightSmoke.test.mjs \
  apps/nex-ae-web/test/documentBootstrap.test.mjs \
  apps/nex-ae-web/test/workspaceBootstrap.test.mjs \
  apps/nex-ae-web/test/runtimeIdentifiers.test.mjs
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_ae_web_grounded_generation_playwright_postgres_smoke.py \
  --coverage-target scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py \
  --smoke scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py
```

## Protected Evidence

- AE Web Node regression: `293 passed`.
- Slice Gate: `284 passed`; statement and branch coverage were both `100.00%`
  for the protected smoke runner; contract validation passed.
- Smoke result: `PASS`, checks `16/16`, evidence mode
  `single_correlated_browser_request`.
- PostgreSQL identities: `nex_ae_user@nex_ae_test` and
  `nex_cx_user@nex_cx_test`; both migration plans were already current.
- Live provider calls: embedding `2`, reranking `1`, generation `1`, all with
  zero failures. The observed models were `Qwen3-Embedding-4B`,
  `Qwen3-Reranker-4B`, and `Qwen3.5-4B`.
- Worker result: claimed `1`, succeeded `1`, retry scheduled `0`, dead-lettered
  `0`.
- Persisted state: AE interaction `COMPLETED`, vector index `READY`, retrieval
  package `READY`, CX generation `COMPLETED`, and CX job `SUCCEEDED`.
- Browser result: `VERIFIED_RESPONSE`, citation next action
  `PRESENT_RESPONSE`, six lifecycle events, and no server secret header.
- Post-cleanup owner-scoped readback: AE workspace/chat/render event and CX
  content/generation/admission/job residue were all `0`.
- Evidence database URLs and all protected values were redacted.

## Boundary Status

- S109 planned gaps: `8`; resolved: `8`; open: `0`.
- Next Slice: `1091` S109 closure and Full Gate.
