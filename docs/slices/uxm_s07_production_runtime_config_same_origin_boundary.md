# UXM-S07 Production Runtime Config and Same-Origin Boundary

## Outcome

PASS / CLOSED. The React v2 installed entry now starts only with an explicit
fetch-mode runtime profile and routes browser business traffic through the
same-origin `/ae-api` facade.

## Implementation

- Added an installed-browser runtime composition that requires the canonical
  inline runtime config and a deployment-resolved tenant value.
- Required `client_mode=fetch`, `ae_base_url=/ae-api`, and
  `fetch_clients_enabled=true`; missing, malformed, mock, or direct-service
  configuration fails closed before application routes render.
- Added a guarded fetch adapter that rejects cross-origin requests and
  same-origin business routes outside `/ae-api`.
- Reused the existing session and client registry through typed adapters,
  while exposing the installed runtime through a React provider.
- Added a generic startup-failure surface that does not render rejected
  configuration, service topology, credentials, or raw error details.
- Added an optional Vite development proxy for `/ae-api` without changing the
  browser-visible same-origin contract.

## Corrective Finding

The new installed-runtime tests found that `loadRuntimeConfig()` already
returns a normalized value, while the first React adapter implementation tried
to normalize it a second time. The second pass rejected the normalized
metadata as an unsupported input field. The adapter now projects the loaded
normalized config directly through `buildRuntimeConfigSummary()` so the
validation boundary executes exactly once.

## Security Controls

- Production startup cannot silently fall back to mock clients.
- Direct localhost/internal service URLs and platform ports 8101-8105 are
  rejected by request guards and production-source audit.
- Runtime config rejects unsupported credential-bearing fields.
- Browser requests use `credentials=same-origin` through existing clients,
  but no service token, API key, provider URL, or database URL is admitted to
  the modern runtime config.
- Legacy direct-health behavior remains outside the React v2 production source
  and is deferred to its planned migration boundary.

## Verification

```text
npm run test:react                    = PASS, 55 tests
npm test                              = PASS, 405 tests
npm run typecheck:v2                  = PASS
npm run tokens:check                  = PASS
npm run audit:v2-imports              = PASS
npm run audit:v2-security             = PASS, 21 production files
npm run build:v2                      = PASS
npm run smoke:v2-security-playwright  = PASS, 4 business requests / 8 checks
```

The Playwright smoke verified the anonymous login-only surface, authenticated
workspace, logout return, desktop/mobile layout, absence of horizontal mobile
overflow, absence of protected-service requests, and same-origin `/ae-api`
routing for every business request.

Local screenshot evidence:

```text
reports/uiux/security-boundary/01-login-desktop.png
reports/uiux/security-boundary/02-workspace-desktop.png
reports/uiux/security-boundary/03-workspace-mobile.png
```

## Decision

```text
UXM-S07 = PASS / CLOSED
Security Boundary Checkpoint = AUTHORIZED
```
