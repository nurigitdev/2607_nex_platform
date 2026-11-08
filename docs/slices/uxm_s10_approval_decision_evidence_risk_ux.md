# UXM-S10 Approval Decision, Evidence, and Risk UX

## Outcome

PASS / CLOSED. The React v2 Approval Inbox now supports protected approve and
reject decisions, authoritative risk presentation, and same-origin evidence
access while preserving the UXM-S07 browser trust boundary.

## Decision Experience

- Approve and reject actions both use the design-system `ConfirmDialog`.
- Reject remains disabled until a non-blank reason is entered.
- Conflict, expiry, unauthorized, and retryable server failures map to concise
  user-safe guidance without rendering backend details.
- Expired gates expose no decision controls.
- A successful decision removes the action form, announces the terminal result,
  moves focus to the result status, and offers `다음 요청 검토`.
- Inbox refresh removes completed gates according to the authoritative pending
  inbox contract; the UI does not invent terminal history.

## Evidence and Risk

- Risk is rendered only when the AE user projection marks it `AVAILABLE`.
- `LOW`, `MEDIUM`, and `HIGH` use semantic status tones and Korean labels. No
  production fallback or mock risk is inferred when the field is `OPEN`.
- The locked attachment manifest supplies count, total size, display name, and
  per-item size.
- Open and download actions use manifest routes validated by
  `approvalClient.js`.
- Fetch runtime resource routes are resolved through the installed `/ae-api`
  base URL. Absolute or non-`/api/v1/` routes fail closed, preventing evidence
  links from bypassing the same-origin AE facade.

## Accessibility and Responsive Behavior

- Dialogs expose alert-dialog titles and descriptions.
- Attachment controls have file-specific accessible names.
- Reject validation is associated with the required textarea.
- Decision results use a live status region and receive focus after the dialog
  trigger is replaced by terminal content.
- Desktop and 390x844 mobile evidence was inspected. The mobile result keeps
  evidence actions, the terminal result, next-item action, and bottom navigation
  free of horizontal overflow or incoherent overlap.

## Protected Playwright Acceptance

`runModernApprovalPlaywrightSmoke.mjs` installs deterministic approval data
behind the same-origin HTTP facade while the browser remains in production
`fetch` mode. It verifies:

```text
authenticated route entry
approval inbox and authoritative risk
attachment open and download through /ae-api
approve confirmation and terminal result
reject reason and confirmation
pending-list removal after both decisions
browser credential boundary
mobile horizontal-overflow boundary
```

Evidence:

```text
reports/uiux/approval-checkpoint/01-approval-inbox-desktop.png
reports/uiux/approval-checkpoint/02-approved-result-desktop.png
reports/uiux/approval-checkpoint/03-rejected-result-mobile.png
```

The evidence directory is ignored local output. This protected harness exercises
real browser HTTP requests against controlled route doubles; it does not claim
actual PostgreSQL, WC, OA, or EOS connectivity.

## Verification

```text
focused Approval + state tests       = PASS, 20 tests
AE Web Node regression               = PASS, 408 tests
React regression                     = PASS, 75 tests / 15 files
TypeScript typecheck                 = PASS
modern production import audit       = PASS, 21 files
modern browser security audit        = PASS, 22 files
design token consistency             = PASS, 146 variables / 15 components
React v2 production build            = PASS
protected Playwright                 = PASS, 14 requests / 2 decisions / 9 checks
PostgreSQL / remote providers        = NOT REQUIRED
```

The production build completed with the existing third-party module-directive
warnings. Its main JavaScript chunk is 529.35 kB and retains the Vite chunk-size
warning; code splitting remains a later performance boundary rather than an
S10 correctness exception.

## Decision

```text
UXM-S10     = PASS / CLOSED
Checkpoint #2 = AUTHORIZED
```
