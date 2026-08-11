# Slice 0218: AE Web Document Scope Retrieval Propagation

## Scope

Slice 0218 connects the selected AE Web document surface to the mock
chat/retrieval workflow.

Implemented:

- Added `apps/nex-ae-web/src/documentScope.js`.
- Added a selected document scope model aligned to the AE retrieval interaction
  route `/api/v1/retrieval/contexts`.
- Added a retrieval scope panel and safe retrieval request preview.
- Updated chat submit handling so grounded prompts carry the selected document
  IDs into `retrieval.document_scope.document_ids`.
- Added assistant message scope metadata for grounded mock responses.
- Added Node built-in tests for scope deduplication, grounded request payload,
  ungrounded request payload, unknown document, invalid document list, and empty
  grounded scope branches.
- Updated static Python regression guards for DOM anchors, scope propagation
  strings, package metadata, responsive styles, and redaction-sensitive strings.

## Boundary

The workflow remains mock-first. The browser may carry selected document IDs,
safe filenames, retrieval route metadata, retrieval profile, `top_k`, and
whether source preview is disabled.

The retrieval scope preview must not display raw prompts, raw source text,
chunk text, source preview text, provider URLs, service tokens, storage
locations, or database details.

Future live integration should attach at the retrieval boundary:

```text
nex-ae-web documentScope selected IDs
  -> nex-ae-api POST /api/v1/retrieval/contexts
  -> nex-cx retrieval context package
```

## Evidence

Targeted Python static regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

Targeted Node Web regression:

```bash
npm --prefix apps/nex-ae-web test
```

JavaScript syntax check:

```bash
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/documentDetailClient.js
node --check apps/nex-ae-web/src/uploadSurface.js
node --check apps/nex-ae-web/src/documentScope.js
```

Static dev-server smoke:

```bash
PORT=5218 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5218/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 7 passed
npm --prefix apps/nex-ae-web test: 13 tests passed across 3 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0218 and retrieval-scope-panel
```

Observed full quality gate:

```text
1628 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
