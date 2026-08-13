# Slice 0268: AE Web Same-Origin Runtime Boundary

## Scope

Add the AE Web same-origin runtime boundary needed before Playwright browser
smoke execution. This slice does not open PostgreSQL connections; it ensures
the browser can target `/ae-api` while the actual AE API target remains a
server-side dev-server setting.

## Implemented

- Added an optional `/ae-api` proxy to `apps/nex-ae-web/scripts/serve.mjs`.
- The proxy is disabled by default and enabled only when `AE_API_PROXY_TARGET`
  is configured.
- The dev server now exports `createAeWebServer`, `AE_API_PROXY_PREFIX`, and
  `isProxyPath` for regression tests.
- Added `apps/nex-ae-web/test/serveProxy.test.mjs` for static serving, proxy
  request forwarding, cookie forwarding, and unsupported target handling.
- Added `scripts/smoke/run_ae_web_same_origin_runtime_boundary.py`.
- The boundary checker emits `ae_web_same_origin_runtime_boundary.v1` evidence
  and verifies:
  - `/ae-api` proxy source wiring exists.
  - browser runtime config accepts same-origin base paths.
  - session fetch clients use same-origin browser credentials.
  - the dev server proxy remains disabled by default.
  - evidence redacts the configured proxy target.
- Added the checker to the default quality gate after the operator profile.
- Updated the AE Web runbook and README with the same-origin proxy profile.

## Evidence

- Same-origin boundary summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_same_origin_runtime_boundary.py --summary`
  - Expected:
    `ae_web_same_origin_runtime_boundary=pass proxy=/ae-api files=5/5 browser_config=safe`
- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
  - Covers the same-origin proxy without PostgreSQL or live backend
    dependencies.
- Python regression:
  `./.venv/bin/pytest tests/test_ae_web_same_origin_runtime_boundary.py -q`
  - Covers default pass, configured proxy redaction, missing files/tokens,
    output writing, CLI paths, and docs/quality wiring.

## Next

Slice 0269 should add the Playwright dependency/readiness foundation. Slice 0270
can then execute a protected Playwright smoke against AE/OA PostgreSQL test
databases through the same-origin `/ae-api` browser path.
