# UXM Security Boundary Checkpoint

## Outcome

PASS / CLOSED. The cumulative UXM-S05 through UXM-S07 shell, authentication,
installed-runtime, and browser-network boundaries are admitted for approval UX
implementation.

## Commit Boundary

```text
UXM-S05  7c0c0f0a  React application shell, router, and providers
UXM-S06  abf619d1  authentication-first session UX
UXM-S07  20aac93a  production runtime config and same-origin boundary
```

## Cumulative Gate

| Check | Result |
|---|---|
| Legacy Node regression | PASS, 405 tests |
| React shell/auth/runtime tests | PASS, 55 tests in 13 files |
| TypeScript no-emit check | PASS |
| Vite production build | PASS |
| Token schema, contrast, and CSS drift | PASS, 146 variables / 15 components |
| Production fixture-import audit | PASS, 20 files |
| Modern browser security audit | PASS, 21 files |
| npm high-severity dependency audit | PASS, 0 vulnerabilities |
| Protected Playwright browser smoke | PASS, 4 business requests / 8 checks |
| Desktop/mobile screenshot inspection | PASS |
| Git whitespace check | PASS |

Build output:

```text
modern.html               0.63 kB
modern CSS               21.97 kB
modern JavaScript       436.86 kB
```

## Security Invariants Preserved

- Anonymous users can render only the authentication surface.
- Authenticated application routes remain role guarded; operations are hidden
  from ordinary employees.
- Logout and local session expiry remove route access immediately.
- Installed runtime requires explicit fetch mode, the `/ae-api` facade, an
  enabled fetch feature, and deployment-resolved tenant configuration.
- Missing or rejected production config cannot silently activate mock clients.
- Every observed browser business request used the same browser origin and an
  `/ae-api/*` path.
- No browser request targeted platform ports 8101-8105 or a provider origin.
- No service token, API key, database URL, or provider credential was admitted
  into modern runtime config or observed request material.
- Startup rejection renders a generic user-safe message without topology or
  configuration details.

## Visual Evidence

The following local, ignored evidence was generated and inspected at the
checkpoint:

```text
reports/uiux/security-boundary/01-login-desktop.png
reports/uiux/security-boundary/02-workspace-desktop.png
reports/uiux/security-boundary/03-workspace-mobile.png
```

The desktop and mobile surfaces showed no incoherent overlap or horizontal
overflow. The mobile shell retained stable bottom navigation and account/logout
controls without exposing internal diagnostics.

## Scope Note

This checkpoint used a protected same-origin browser harness and did not
require PostgreSQL, remote model providers, backend migrations, or API contract
changes. Legacy direct-health behavior remains isolated outside the React v2
production source until its planned retirement boundary.

## Decision

```text
SECURITY_BOUNDARY_CHECKPOINT = PASS / CLOSED
UXM-S08                     = AUTHORIZED
```
