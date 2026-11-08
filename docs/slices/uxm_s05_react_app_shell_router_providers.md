# UXM-S05 React App Shell / Router / Providers

## Outcome

PASS / CLOSED. The React v2 entry now has a route-safe and role-safe application
shell without changing the legacy default entry or backend contracts.

## Implementation

- Added React Router and TanStack Query as admitted frontend dependencies.
- Added query, Korean-default i18n, token-theme, and session providers.
- Added `/login`, `/workspace`, `/approvals`, `/upload`, `/documents`,
  `/retrieval`, `/artifacts`, and `/operations` routes.
- Reused `applicationShell.js` through the typed adapter for authentication and
  operations-role decisions.
- Kept upload and retrieval as compatibility routes without primary navigation
  placement.
- Added a compact mobile navigation layout and keyboard skip link.

## Security and Compatibility

- Anonymous protected-route access redirects to `/login`.
- Unknown authenticated routes return to `/workspace`.
- `/operations` is visible and accessible only to `admin` or `operator` roles.
- No direct service URL, provider URL, credential, database migration, or API
  contract was introduced.
- Legacy hash routing remains unchanged and isolated to the legacy entry.

## Verification

```text
npm run test:react       = PASS, 33 tests
npm run typecheck:v2     = PASS
npm run tokens:check     = PASS, 146 variables / 15 components
npm run audit:v2-imports = PASS, 14 production files
npm run build:v2         = PASS
npm test                 = PASS, 404 tests
```

## Decision

```text
UXM-S05 = PASS / CLOSED
UXM-S06 = AUTHORIZED
```
