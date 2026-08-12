# Slice 0234: AE Web Session Client and Login State Model

## Scope

Slice 0234 adds the AE Web session client and browser login state model needed
before authenticated fetch-mode wiring is connected to visible runtime controls.

Implemented:

- Added `apps/nex-ae-web/src/sessionClient.js`.
- Added `apps/nex-ae-web/test/sessionClient.test.mjs`.
- Normalized `oa_browser_session.v1` snapshots into
  `ae_web_session_state.v1`.
- Added mock and fetch session clients for current session, login, and logout.
- Added Python static guards so the session client remains browser-safe in the
  full regression suite.
- Updated the AE Web README and working-doc slice index.

## Boundary

The browser session state is a safe projection, not a credential store. The
session client accepts only user-session browser snapshots for `nex-ae-api`,
requires tenant/user owner refs from OA claims, and rejects credential-shaped
fields recursively.

The fetch adapter uses same-origin browser credentials and AE API auth facade
routes:

- `GET /api/v1/auth/session`
- `POST /api/v1/auth/session/login`
- `POST /api/v1/auth/session/logout`

Raw user tokens, service credentials, passwords, provider endpoints, database
URLs, and storage paths remain outside the browser runtime boundary.

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
npm --prefix apps/nex-ae-web test: 55 passed
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q: 9 passed in 0.09s
```

Observed full quality gate:

```text
1688 passed, 1 warning in 59.75s
statement_coverage=98.05% threshold=95.00%
branch_coverage=93.93% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
