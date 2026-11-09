# UXM-S17 Operations / Diagnostics Isolation

## Outcome

PASS / CLOSED. Runtime and service diagnostics now live exclusively under the
role-gated React v2 `/operations` route. Normal employee business views no
longer expose the operations menu or runtime details.

## Source-Backed Decision

The Slice selected the planned Option A boundary:

```text
Browser
  -> same-origin /ae-api
  -> GET /api/v1/web/operations/summary
  -> AE safe read-only projection
```

The legacy `Browser -> 127.0.0.1:810x` health probing path is not reused by
the React v2 surface. The new AE projection exposes bounded service IDs,
health/readiness codes, versions, runtime availability flags, and its own safe
facade route. It omits service addresses, ports, database URLs, provider
endpoints, credentials, storage references, and private content.

## Authorization

The application shell continues to hide `/operations` from normal employees,
but UI hiding is not the security boundary. The AE route independently:

```text
authenticated admin/operator browser user = ALLOW
authenticated employee                    = 403
service-token caller                       = 403
missing/invalid browser session            = 401
projection failure                         = bounded 503
```

Role matching is case-insensitive. Backend error details are never reflected
to the browser.

## User Surface

The operations page provides a dense, work-focused view of:

```text
platform status
service health/readiness/version
database / Agent Runtime / model-route availability
safe facade route inventory
```

Unavailable data is shown as `미확인` or bounded retry guidance rather than
invented readiness.

## Verification

```text
focused backend/auth tests                 = PASS, 10 tests
OpenAPI/contract hygiene regression         = PASS, 46 tests
focused React/client tests                  = PASS, 18 tests / 3 files
browser unit regression                     = PASS, 413 tests
React component regression                  = PASS, 119 tests / 27 files
TypeScript typecheck                        = PASS
modern production import audit              = PASS, 50 files
modern browser security audit               = PASS, 51 files
design token consistency                    = PASS, 146 variables / 15 components
React v2 production build                   = PASS
operations isolation Playwright smoke       = PASS, 8 requests / 2 screenshots / 10 checks
PostgreSQL / remote providers               = NOT REQUIRED
```

Visual evidence:

```text
reports/uiux/operations-isolation/01-operations-desktop.png
reports/uiux/operations-isolation/02-operations-mobile.png
```

The existing Vite bundle-size advisory remains non-blocking and unchanged.

## Decision

```text
UXM-S17 = PASS / CLOSED
Business UI diagnostic isolation = PASS
Backend role authorization = PASS
UXM-S18 = AUTHORIZED
```
