# UXM-S06 Authentication and Session UX

## Outcome

PASS / CLOSED. The React v2 entry now presents an authentication-first user
experience while preserving the existing OA credential and browser-session
contracts.

## Implementation

- Reused `credentialLoginSurface.js`, `sessionClient.js`, and
  `sessionIdentityPresentation.js` through a typed adapter.
- Added session bootstrap, login, logout, expiration, and fail-closed local
  logout behavior to the React session provider.
- Added the Korean employee-ID login screen with field validation, keyboard
  submit, loading state, password visibility control, and Caps Lock notice.
- Added user-facing error mapping for invalid credentials, denied accounts,
  unavailable service, and unknown login failures.
- Added authenticated account presentation and logout to the shell header.

## Security Decisions

- Tenant resolution remains deployment-owned and is not rendered in the login
  form.
- Password state is cleared before awaiting a login response and is never
  included in session state, summaries, logs, or visible errors.
- Anonymous, expired, and logged-out sessions cannot render application routes.
- Session expiry returns immediately to the login screen.
- Technical state names, route counts, session schemas, and internal service
  information are not rendered.

## Verification

```text
npm run test:react       = PASS, 39 tests
npm run typecheck:v2     = PASS
npm run audit:v2-imports = PASS, 16 production files
npm run build:v2         = PASS
npm test                 = PASS, 404 tests
```

React tests cover validation, Enter-key submit, canonical login request shape,
error mapping, password clearing, visibility control, Caps Lock, requested-route
activation, logout, expiration, and hidden tenant/technical metadata.

The protected browser acceptance is intentionally executed at the S07 Security
Boundary Checkpoint after production runtime config and same-origin fetch wiring
are active.

## Decision

```text
UXM-S06 = PASS / CLOSED
UXM-S07 = AUTHORIZED
```
