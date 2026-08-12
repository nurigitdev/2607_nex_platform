# Slice 0231: AE Web Authenticated Runtime Boundary Audit

## Scope

Slice 0231 starts the authenticated AE Web runtime track with a browser-side
boundary audit. It does not enable live login yet; it freezes the conditions
that must be true before fetch-mode browser clients may call AE API routes.

Implemented:

- Added `apps/nex-ae-web/src/authBoundary.js`.
- Added `apps/nex-ae-web/test/authBoundary.test.mjs`.
- Added static guards so the authenticated boundary remains visible in the
  Python regression suite.
- Updated the AE Web README and working-doc slice index.

## Boundary

The browser remains mock-first by default. Fetch mode is allowed only when:

- the browser session is authenticated;
- fetch clients are explicitly enabled;
- browser credentials are same-origin user credentials;
- owner scope is derived from session claims;
- the browser calls only `nex-ae-api`, never CX/MO/database directly.

The boundary rejects runtime config fields that could carry service tokens,
provider endpoints, database URLs, storage paths, raw prompts, or raw source
material.

## Evidence

Targeted Node regression:

```bash
npm --prefix apps/nex-ae-web test
```

Targeted Python regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
npm --prefix apps/nex-ae-web test: 47 passed
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q: 9 passed in 0.03s
```

Observed full quality gate:

```text
1667 passed, 1 warning in 54.14s
statement_coverage=98.04% threshold=95.00%
branch_coverage=93.88% threshold=85.00%
contract_validation=pass schemas=48 examples=77 negative_examples=53 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
