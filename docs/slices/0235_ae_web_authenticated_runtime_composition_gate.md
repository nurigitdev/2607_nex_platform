# Slice 0235: AE Web Authenticated Runtime Composition Gate

## Scope

Slice 0235 wires the AE Web authenticated runtime boundary into the browser
runtime composition path. It keeps the existing static/mock-first UI, but makes
the runtime config, session state, session client, auth boundary, and client
registry share one gate before browser fetch clients are composed.

Implemented:

- Added `apps/nex-ae-web/src/authenticatedRuntime.js`.
- Added `apps/nex-ae-web/test/authenticatedRuntime.test.mjs`.
- Updated `apps/nex-ae-web/src/main.js` to create clients through the
  authenticated runtime envelope.
- Extended runtime diagnostics with session state, auth boundary summary, and
  fetch-mode allowed status.
- Added static guards so the authenticated runtime composition remains visible
  in Python regression tests.
- Updated the AE Web README and working-doc slice index.

## Boundary

Fetch-mode browser clients are now composed only when the runtime config asks
for fetch mode, the fetch feature flag is enabled, the browser session state is
authenticated, same-origin user credentials are used, and owner scope is
claim-derived.

The authenticated runtime summary is diagnostic evidence, not a credential
container. It reports redaction metadata and does not include raw user tokens,
service credentials, passwords, provider endpoints, database URLs, CX storage
paths, prompts, or source text.

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
npm --prefix apps/nex-ae-web test: 59 passed
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q: 9 passed in 0.10s
```

Observed full quality gate:

```text
1688 passed, 1 warning in 61.15s
statement_coverage=98.05% threshold=95.00%
branch_coverage=93.93% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
