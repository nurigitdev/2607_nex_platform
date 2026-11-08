# P8-DEMO-S11B: IA Surface Identity and Timeline Polish

## Scope

This focused presentation Slice keeps the installed P8 runtime, API contracts,
and database layout unchanged while simplifying the Chairman demo workspace.

- The legacy `Slice 0227 / NeX-Platform 작업면` heading is replaced by
  `NeX-Platform`.
- The authenticated top bar shows the current login account immediately before
  the logout action. The just-submitted employee ID is preferred; after a page
  reload the authoritative OA subject ID is used as a safe fallback.
- The progress timeline is a single horizontal step row with contained
  horizontal scrolling on narrow viewports.
- Every compact timeline item preserves its complete stage, event type, and
  status through its accessible label and hover title.

## Boundaries

- No backend, authentication, API, or database contract changes.
- No personal display name is inferred. The current session contract exposes
  an account/subject identity, so the UI renders only that authoritative value.
- Upload, RAG, approval, controlled WRITE, and result publication behavior are
  unchanged.

## Verification

The focused browser acceptance checks both 1440 x 900 desktop and 390 x 844
mobile viewports. It requires the product title, current account, one-row
timeline geometry, contained overflow, authentication-first shell, protected
view routing, and logout cleanup to remain valid together.

```text
AE Web Node tests                 = 403 passed
focused Python static tests       = 27 passed
focused Node tests                = 5 passed
Playwright authentication smoke   = PASS (18 checks)
desktop timeline                  = one row
mobile timeline                   = one row / 54 px
mobile document overflow          = false
```

Visual evidence is stored under the ignored runtime-report directory:

```text
reports/deployment/p8-demo-s11b-screens/
  p8-demo-s11b-desktop.png
  p8-demo-s11b-mobile.png
```
