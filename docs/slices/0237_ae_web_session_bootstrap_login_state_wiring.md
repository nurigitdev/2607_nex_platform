# Slice 0237: AE Web Session Bootstrap and Login-State Wiring

## Scope

Slice 0237 wires the AE Web session client into browser runtime bootstrap. The
static shell remains mock-first, but runtime composition now attempts to read
the current browser session and recomposes the authenticated runtime from that
session state.

Implemented:

- Added `apps/nex-ae-web/src/sessionBootstrap.js`.
- Added `apps/nex-ae-web/test/sessionBootstrap.test.mjs`.
- Updated `apps/nex-ae-web/src/main.js` to initialize through session bootstrap
  and refresh the runtime from `GET /api/v1/auth/session`.
- Updated `apps/nex-ae-web/src/sessionClient.js` so current-session `401`
  maps to anonymous browser state instead of a fatal error.
- Extended runtime diagnostics with session bootstrap phase and bootstrap
  summary.
- Updated AE Web static guards, README, and working-doc slice index.

## Boundary

Fetch mode now has a browser-safe startup path:

- authenticated current session: compose fetch clients;
- missing/anonymous/expired session: fall back to mock clients and preserve
  blocked reasons;
- network/session-read failure: keep the shell available and report a failed
  bootstrap phase.

The bootstrap summary never includes raw user tokens, service credentials,
passwords, provider endpoints, database URLs, storage locations, raw prompts, or
source text.

This Slice does not require PostgreSQL smoke evidence because it is browser
runtime composition over the AE API session facade. Protected fetch-mode
PostgreSQL smoke remains a later Slice.

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
npm --prefix apps/nex-ae-web test: 64 passed
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q: 9 passed in 0.11s
```

Observed full quality gate:

```text
1696 passed, 1 warning in 58.56s
statement_coverage=98.04% threshold=95.00%
branch_coverage=93.93% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
