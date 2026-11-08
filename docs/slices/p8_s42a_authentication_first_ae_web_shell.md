# P8-S42A Authentication-first AE Web Shell and View Routing Hardening

**Status:** PASS
**Date:** 2026-10-22

## Scope

P8-S42A changes only the AE Web shell and browser acceptance boundary. It adds
no database migration and changes no AE, OA, WC, CX, MO, or AG backend API
contract.

The anonymous surface now contains only the employee credential form. A valid
session opens Chat / Workspace as the default view. Approval, upload, document,
retrieval, and artifact surfaces are available through authenticated menu
routing. Service status, runtime diagnostics, and audit information are grouped
under `operations`, which is available only to normalized `admin` or `operator`
roles.

## Session Boundary

- mock mode no longer restores an authenticated session during initial page
  load;
- fetch mode may restore a same-origin OA-backed browser session;
- the browser schedules a fail-closed transition from the session `expiresAt`;
- logout and expiry return immediately to the login shell;
- dynamic chat, approval, document, retrieval, artifact, audit, service, and
  diagnostic DOM surfaces are cleared on that transition;
- stale approval inbox responses are discarded after a session client change.

Internal service topology and runtime diagnostics are neither requested nor
rendered for anonymous users. Employee sessions do not receive the operations
menu and do not render the audit summary.

## View Contract

```text
workspace  -> chat, workspace summary, generation timeline
approvals  -> unified approval workbench
upload     -> owner-scoped upload surface
documents  -> document list and detail
retrieval  -> retrieval scope and quality surface
artifacts  -> artifact library, preview, download, and lifecycle
operations -> service status, runtime diagnostics, and AG audit
```

Unknown or unauthorized view requests fall back to `workspace`. The Korean
golden-journey viewport contract was reconciled with the routed single-view
layout while preserving one visible main landmark and one visible primary
heading.

## Verification

```text
AE Web Node regression: 353 passed
authentication shell unit branches: PASS
stale approval response regression: PASS

authentication-first Playwright smoke: PASS
browser checks: 14/14
routed authenticated views: 5
anonymous service probes: 0

approval Playwright smoke: PASS
Korean golden journey Playwright: PASS
viewports: desktop + mobile
journey stages: 9

AE Web Slice Gate: 309 passed
statement coverage: 100.00%
branch coverage: 100.00%
contract validation: PASS
schemas: 188
examples: 250
negative examples: 217
OpenAPI documents: 9
```

Desktop and mobile Chromium captures were inspected for overlap, horizontal
overflow, authentication-only anonymous rendering, and stable authenticated
navigation.

## Deferred Protected Acceptance

P8-S43 remains responsible for actual WC/OA PostgreSQL and authenticated IA UI
acceptance. P8-S42A does not require PostgreSQL or remote model providers.
