# Slice 0222: AE Web Safe Runtime Config Loader

## Scope

Slice 0222 adds a browser-safe runtime config loader so AE Web can eventually
switch between mock and fetch clients without editing `main.js`.

Implemented:

- Added `apps/nex-ae-web/src/runtimeConfig.js`.
- Added inline JSON config anchor `ae-web-runtime-config`.
- Connected `main.js` so `loadRuntimeConfig()` feeds `createAeWebClients()`.
- Added safe config summary metadata to upload and retrieval previews.
- Added guarded fetch mode: `client_mode = fetch` requires
  `features.fetch_clients_enabled = true`.
- Added Node built-in tests for default config, inline config, global override,
  same-origin base path normalization, malformed JSON, unsupported fields,
  unsupported client mode, invalid feature values, disabled fetch mode, and
  unsafe AE base URLs.
- Updated static Python regression guards for runtime config wiring, package
  metadata, and redaction-sensitive strings.

## Boundary

Browser runtime config is intentionally narrow:

```json
{
  "runtime_config_schema_version": "ae_web_runtime_config.v1",
  "client_mode": "mock",
  "ae_base_url": "",
  "features": {
    "document_detail_enabled": true,
    "upload_submit_enabled": true,
    "retrieval_submit_enabled": true,
    "fetch_clients_enabled": false
  }
}
```

Allowed values are limited to mock/fetch mode, AE facade base URL, and boolean
feature flags.

Runtime config must not include credentials, provider endpoints, database
endpoints, storage locations, raw source content, local filesystem paths, or
service-only material.

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
node --check apps/nex-ae-web/src/runtimeConfig.js
node --check apps/nex-ae-web/src/clientRegistry.js
node --check apps/nex-ae-web/src/documentDetailClient.js
node --check apps/nex-ae-web/src/uploadSurface.js
node --check apps/nex-ae-web/src/uploadClient.js
node --check apps/nex-ae-web/src/documentScope.js
node --check apps/nex-ae-web/src/retrievalClient.js
```

Static dev-server smoke:

```bash
PORT=5222 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5222/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_nex_ae_web_static.py: 8 passed
npm --prefix apps/nex-ae-web test: 30 tests passed across 7 suites
JavaScript syntax check: pass
dev-server smoke: http_status=200 with Slice 0222 and ae-web-runtime-config
```

Observed full quality gate:

```text
1629 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
```
