# UXM-S21 Legacy Renderer and DOM Orchestration Retirement

## Outcome

PASS / CLOSED. React is the sole AE Web production UI. The static DOM
orchestrator, renderer-only modules, transitional Vite entry, and obsolete
source-string smoke contracts have been retired.

## Retired Production Surface

- `src/main.js` and `src/styles.css`
- `approvalUi.js`, `artifactCard.js`, and `voucherAttachmentUi.js`
- legacy static markup previously stored in `index.html`
- transitional `modern.html` and build-promotion script
- renderer exports identified by the UXM-S21 plan

Pure builders, normalizers, assertions, safe read models, client adapters, and
their business/security regression tests remain. Renderer-only tests were
removed only where React component and feature tests already provide parity.

## Canonical Runtime Boundary

- Source entry: `index.html` -> `/src/app/main.tsx`
- Build entry: Vite `index.html`
- Runtime artifact: `dist/` only
- Browser API boundary: same-origin `/ae-api`
- Runtime mode: explicit fetch; no implicit production mock fallback
- Historical `/modern.html`: compatibility redirect to `/`, not a second UI

`auditLegacyUiRetirement.mjs` now fails when retired files or renderer symbols
reappear, when the canonical React entry drifts, when direct service URLs are
introduced, or when production HTML enables mock mode. The repository quality
gate runs this audit and the browser security audit in place of the retired
static renderer smoke scripts.

## Evidence

```text
legacy Node regression                = PASS, 374 tests / 149 top-level entries
React regression                      = PASS, 127 tests / 28 files
TypeScript typecheck                   = PASS
legacy UI retirement audit            = PASS, 116 files
modern production import audit        = PASS, 51 files
modern browser security audit         = PASS, 52 files
production cutover acceptance         = PASS, 10 checks / 2 assets
focused deployment/static regression  = PASS, 22 tests
isolated static browser smoke          = PASS, 6 anchors
actual multi-stage OCI build           = PASS
OCI runtime non-root/dist-only probe   = PASS, node / 4 packaged files
PostgreSQL / remote providers          = NOT REQUIRED
```

The Vite bundle-size and third-party `use client` advisories remain
non-blocking and unchanged from UXM-S20.

## Decision

```text
UXM-S21 = PASS / CLOSED
React sole production UI = ENFORCED
legacy DOM orchestration = ABSENT
pure model compatibility layer = RETAINED
UXM-S22 final repository gate = AUTHORIZED
```
