# P8-S42 AE-WEB / IA Approval UI

**Status:** PASS
**Date:** 2026-10-22

## Scope

P8-S42 adds a unified IA approval workbench while preserving the three
canonical approval domains as separate visual and semantic categories:

```text
NSL_WRITE
AGENT_FORMAL
BUSINESS_FORMAL
```

The browser renders only display-safe WC projections. It does not receive an
AE service token, tenant override header, protected approval request, source
reference, semantic hash, resume target, or storage path.

The AE facade applies exact response-field allowlists to inbox, detail, and
decision payloads. Unexpected nested or top-level fields fail closed with a
typed `502` before any response reaches the browser.

## Runtime Boundary

AE Web uses same-origin browser routes:

```text
GET  /api/v1/approval-gates
GET  /api/v1/approval-gates/{approval_work_item_id}
POST /api/v1/approval-gates/{approval_work_item_id}/decisions
```

The AE API derives tenant and subject identity from the authenticated browser
session. Its WC client then uses the `nex-ae-api` service credential plus the
derived subject context. WC remains the approval decision system of record and
continues to perform fresh OA authorization for reads and decisions.

No database table or migration was added. The existing WC approval aggregate
from P8-S32 through P8-S41 is reused without mutation from the browser.

## User Experience

The workbench provides:

- bounded pending inbox and safe detail view;
- distinct domain markers for NSL, Agent formal, and business formal approval;
- approve and reject actions with an optional review comment;
- explicit unauthorized, expired, conflicting, failed, and terminal states;
- in-flight submission suppression and exact replay visibility;
- responsive two-column desktop and single-column mobile layouts.

The production-shaped fetch client and deterministic mock client expose the
same normalized browser contract. The mock profile covers all three domains,
an expired item, authorization denial, approve, reject, and duplicate replay.

## Contract

The AE OpenAPI now declares all three browser facade routes and points their
payloads to the canonical WC approval JSON Schemas. The existing WC decision
request remains exact and closed; AE rejects unsupported fields or actions
before calling WC.

## Verification

```text
approval facade focused tests: 25 passed
approval facade statement coverage: 100%
approval facade branch coverage: 100%

AE Web Node regression: 344 passed
Playwright Chromium approval smoke: PASS
browser checks: 12/12
gates rendered: 4
domains preserved: 3

AE Web Slice Gate: 309 passed
statement coverage: 100.00%
branch coverage: 100.00%

AE API Slice Gate: 4,601 passed, 17 protected skips
statement coverage: 98.30%
branch coverage: 96.16%

contract validation: PASS
schemas: 188
examples: 250
negative examples: 217
OpenAPI documents: 9
```

Desktop and mobile Chromium captures were inspected for overflow, overlap,
domain differentiation, selection state, and stable action controls.

## Deferred Protected Acceptance

P8-S42 intentionally does not claim actual WC/OA PostgreSQL acceptance. The
canonical P8-S43 gate owns authenticated browser-to-AE-to-WC-to-OA execution
against the actual test databases, including authorization, create/decision
scenarios, and protected IA UI evidence. Remote model providers are not part of
this approval UI slice.
