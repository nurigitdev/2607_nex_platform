# UXM-S19 Responsive / Accessibility / Playwright v2 Acceptance

## Outcome

PASS / CLOSED. The React v2 surface is accepted at the frozen desktop and
mobile viewports. UXM-S15 through UXM-S19 now form Full Web Acceptance #1.

## Runtime Acceptance

The `ae_web_ux_acceptance.v2` evaluator is applied in the real Chromium
journeys rather than only in DOM unit fixtures. The admitted command is:

```text
cd apps/nex-ae-web
npm run acceptance:v2-full-web
```

It executes these six fail-closed journeys in order:

```text
security boundary / login / workspace
workspace request / approval wait / resume / result
approval inbox / evidence / approve / reject
document upload / detail / retrieval
artifact detail / preview / export / download / lifecycle
operator-only operations / diagnostics
```

The metadata-only receipt is written to
`reports/uiux/full-web-acceptance-v2/receipt.json`. It contains status and
counts only; DOM text, request bodies, credentials, and protected URLs are not
retained.

## Accessibility And Responsive Closure

- Wrapped checkbox/radio labels are measured as their actual activation
  target. Visually clipped native file inputs are not misclassified as 1 px
  visible controls.
- Every accepted screen has one visible `main` and `h1`, named controls,
  24 px minimum visible targets, visible keyboard focus, and required stable
  regions.
- Approval dialogs retain focus while open. Drawer primitives now accept an
  optional Radix trigger and return focus to that trigger when closed.
- Decision feedback is exposed through a live status region. Statuses retain
  visible text and icons instead of relying on color alone.
- Light and dark semantic token combinations retain WCAG AA 4.5:1 text
  contrast.
- Desktop `1440 x 900` and mobile `390 x 844` receipts reject horizontal
  overflow and primary-region overlap.
- Browser requests remain same-origin under `/ae-api`; direct `810x` service
  access and browser-held service credentials remain forbidden.

## Evidence

```text
Full Web Acceptance v2                = PASS, 6 journeys / 71 checks
responsive screenshots               = PASS, 16 files
desktop / mobile visual inspection   = PASS
legacy Node regression               = PASS, 414 tests / 159 top-level entries
React regression                     = PASS, 127 tests / 28 files
contract schema regression           = PASS, 31 tests
TypeScript typecheck                  = PASS
modern production import audit       = PASS, 51 files
modern browser security audit        = PASS, 52 files
design token consistency             = PASS, 146 variables / 15 components
React v2 production build            = PASS
existing auth-first Playwright       = PASS, 18 checks / 5 views
PostgreSQL / remote providers        = NOT REQUIRED
```

The protected Korean Golden Journey runner was also probed. It returned its
expected `required_env_missing` admission result because
`NEX_AE_WEB_GOLDEN_JOURNEY_WEB_URL` was not supplied and did not launch a
browser. It is not part of this deterministic Full Web gate; the selected
existing auth-first Playwright journey passed.

The existing Vite bundle-size and third-party `use client` advisories remain
non-blocking and unchanged.

## Decision

```text
UXM-S19 = PASS / CLOSED
Full Web Acceptance #1 = PASS
React UI v2 functional acceptance = COMPLETE
Legacy retirement preparation = AUTHORIZED
UXM-S20 = AUTHORIZED
```
