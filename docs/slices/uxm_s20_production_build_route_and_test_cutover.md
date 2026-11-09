# UXM-S20 Production Build, Route, and Test Cutover

## Outcome

PASS / CLOSED. The React v2 application is now the production AE Web artifact.
The legacy UI source remains present for the dedicated UXM-S21 retirement
slice, but it is not copied into or served by the production image.

## Production Boundary

- `npm run build:v2` creates the canonical `dist/` artifact and promotes the
  transitional Vite entry to `dist/index.html`.
- `npm start` serves only `dist/`, supports SPA navigation fallback, redirects
  `/modern.html` to `/`, and applies immutable caching only to hashed assets.
- Browser requests remain same-origin under `/ae-api`. Missing or invalid AE
  API proxy configuration fails closed instead of falling back to mock data.
- The AE Web Containerfile uses a pinned Node base in separate build and
  runtime stages. The runtime stage contains `dist/` and `serve.mjs` only and
  runs as the non-root `node` user.
- OCI context admission now covers the React entry, Vite/TypeScript config,
  lockfile, source tree, and deterministic build promotion script.

## Regression Hardening

The static browser smoke now terminates the complete npm/Node process group.
This closes a discovered test-harness defect where a child server could remain
bound to the smoke port and make a later run inspect stale HTML.

## Evidence

```text
focused Python regression             = PASS, 41 tests
legacy Node regression                = PASS, 417 tests / 160 top-level entries
React regression                      = PASS, 127 tests / 28 files
TypeScript typecheck                   = PASS
modern production import audit        = PASS, 51 files
modern browser security audit         = PASS, 52 files
production cutover acceptance         = PASS, 10 checks / 2 assets
isolated static browser smoke          = PASS, 6 anchors
smoke process-group cleanup            = PASS, no residual listener
actual multi-stage OCI build           = PASS
OCI runtime non-root/dist-only probe   = PASS
PostgreSQL / remote providers          = NOT REQUIRED
```

The existing Vite bundle-size and third-party `use client` advisories remain
non-blocking. Bundle splitting is deferred because it does not affect the
production route, trust, or packaging cutover.

## Decision

```text
UXM-S20 = PASS / CLOSED
React production route = ACTIVE
legacy production route = INACTIVE
UXM-S21 legacy retirement = AUTHORIZED
```
