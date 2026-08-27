# Slice 0398: AE Web Repaired Response Read-Model Runtime Diagnostics

## Scope

Wire the repaired response review read-model into AE Web runtime diagnostics so
operators can see repaired-response review counts from the browser shell without
opening raw review payloads.

## Changes

- Updated `apps/nex-ae-web/src/runtimeDiagnostics.js` to accept a repaired
  response review read-model summary.
- Updated `apps/nex-ae-web/src/main.js` to build the read-model from current
  chat message review surfaces.
- Extended runtime diagnostics tests and AE Web static policy tests.

## Notes

The visible runtime diagnostics show only total, actionable, and failed repaired
response review counts. The JSON diagnostics preview receives the safe
read-model summary, not raw prompts, raw generation output, source text, service
tokens, provider endpoints, database endpoints, or storage paths.

## Evidence

- `node --check apps/nex-ae-web/src/main.js`
- `node --check apps/nex-ae-web/src/runtimeDiagnostics.js`
- `node --test apps/nex-ae-web/test/runtimeDiagnostics.test.mjs apps/nex-ae-web/test/repairedResponseReviewReadModel.test.mjs`
  - `7` tests passed.
- `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
  - `17` tests passed.
- `npm --prefix apps/nex-ae-web test`
  - `142` tests passed.
- `scripts/quality/run_quality_gate.sh`
  - `2869` tests passed, `1` warning.
  - `statement_coverage=98.69%`
  - `branch_coverage=96.14%`
  - `contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7`

No PostgreSQL smoke was required for this slice because the new diagnostics are
derived from existing browser state and do not introduce a new persistence or
service API write path.
