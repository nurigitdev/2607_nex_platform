# Slice 0221: AE Web Runtime Client Composition Registry

## Scope

Slice 0221 centralizes AE Web browser client creation so later runtime config
and fetch-mode integration can be controlled from one safe boundary.

Implemented:

- Added `apps/nex-ae-web/src/clientRegistry.js`.
- Added `createAeWebClients()` for mock/fetch composition across document
  detail, upload, and retrieval clients.
- Added `buildClientRegistrySummary()` for safe UI/debug previews.
- Updated `main.js` to use the registry instead of constructing individual mock
  clients directly.
- Added Node built-in tests for mock registry composition, fetch composition,
  shared fetch implementation, base URL normalization, unsupported mode, invalid
  base URL, and invalid registry summary branches.
- Updated static Python regression guards for registry wiring, package metadata,
  and redaction-sensitive strings.

## Boundary

The default browser runtime remains mock mode:

```text
main.js
  -> createAeWebClients({ mode: "mock" })
  -> documentDetailClient + uploadClient + retrievalClient
```

Fetch mode is intentionally available through the registry but not yet selected
by browser runtime config. Slice 0222 should add a safe runtime config loader
that can choose mock/fetch without exposing server-only secrets.

Registry summaries may include client mode, safe base URL, and adapter modes.
They must not include service tokens, API keys, provider URLs, database URLs,
raw source content, storage paths, or local filesystem locations.

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
node --check apps/nex-ae-web/src/clientRegistry.js
node --check apps/nex-ae-web/src/documentDetailClient.js
node --check apps/nex-ae-web/src/uploadSurface.js
node --check apps/nex-ae-web/src/uploadClient.js
node --check apps/nex-ae-web/src/documentScope.js
node --check apps/nex-ae-web/src/retrievalClient.js
```

Static dev-server smoke:

```bash
PORT=5221 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5221/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 8 passed
npm --prefix apps/nex-ae-web test: 25 tests passed across 6 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0221 and client summary anchors
```

Observed full quality gate:

```text
1629 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
