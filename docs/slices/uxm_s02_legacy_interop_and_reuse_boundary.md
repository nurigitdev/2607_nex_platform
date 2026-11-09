# UXM-S02 Legacy Interop and Reuse Boundary

## Outcome

PASS. React v2 can reuse the current runtime config, client registry, and
application shell through typed adapters without copying business behavior.

## Changes

- Added a typed runtime projection over the existing `runtimeConfig.js`.
- Added one client gateway over `createAeWebClients()` for both mock and fetch
  modes.
- Added an application-shell projection adapter without changing legacy shell
  rules.
- Added a production import audit that rejects known mock records, harnesses,
  and golden-journey fixtures under `src/app`.
- Preserved existing client implementations and public browser safety rules.

## Verification

```text
npm run typecheck:v2      = PASS
npm run test:react        = PASS, 7 tests
npm run audit:v2-imports  = PASS, 7 production files scanned
npm test                  = PASS, 404 tests
```

Covered branches include mock registry reuse, explicitly enabled fetch reuse,
fetch fail-closed behavior, anonymous shell projection, and forbidden import
absence.

## Decision

```text
UXM-S02 = PASS / CLOSED
UXM-S03 = AUTHORIZED
```
