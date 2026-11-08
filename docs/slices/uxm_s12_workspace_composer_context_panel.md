# UXM-S12 Workspace, Composer, and Context Panel

## Outcome

PASS / CLOSED. The authenticated `/workspace` route now renders the React v2
primary work surface instead of a placeholder. Desktop uses a focused Main and
Context layout; tablet and mobile collapse to one column while preserving the
fixed authenticated navigation.

## Workspace Surface

- Korean-default empty state with recommended work prompts.
- Source-backed recent work only; no synthetic history is rendered.
- Conversation region for user and IA messages.
- Auto-growing composer with Enter-to-send and Shift+Enter line breaks.
- Multiple attachment chips with deterministic duplicate removal.
- Evidence toggle, output format selector, submit, supported cancel, and retry.
- Context tabs for durable progress, attachments, and sources.
- Canonical S11 status labels and semantic tones.

Workspace identifiers, routes, provider names, operation names, and raw runtime
states are not rendered.

## Runtime Boundary

`WorkspacePage` receives a narrow `WorkspaceController`. It owns only transient
composer submission state and never fabricates durable execution progress. The
actual grounded generation, cancellation, result, and timeline integration is
reserved for UXM-S14, which can inject the existing installed runtime through
this boundary.

## Audit Scope Correction

The modern import and browser-security audits previously scanned only
`src/app`. Their root now covers all modern TypeScript under `src`, including
`features`, `ux`, and `design-system`, while legacy JavaScript remains outside
the React v2 audit set. This increased the admitted scan from 21/22 files to
36/37 files and found no violation.

## Visual Acceptance

The protected same-origin Playwright harness passed after the canonical S11
heading was adopted. Desktop and 390x844 mobile screenshots were inspected.
The mobile evidence now uses an actual viewport capture so the fixed bottom
navigation is represented at its real position rather than duplicated into a
full-page screenshot.

```text
reports/uiux/security-boundary/02-workspace-desktop.png
reports/uiux/security-boundary/03-workspace-mobile.png
```

No horizontal overflow, incoherent overlap, clipped recommendation, or exposed
internal runtime detail was observed.

## Verification

```text
focused Workspace + App tests           = PASS, 20 tests
AE Web Node regression                  = PASS, 408 tests
React regression                        = PASS, 86 tests / 17 files
TypeScript typecheck                     = PASS
modern production import audit           = PASS, 36 files
modern browser security audit            = PASS, 37 files
design token consistency                 = PASS, 146 variables / 15 components
React v2 production build                = PASS
protected Playwright                     = PASS, 4 requests / 8 checks
PostgreSQL / remote providers             = NOT REQUIRED
```

Build output:

```text
modern.html               0.63 kB
modern CSS               33.57 kB
modern JavaScript       541.24 kB
```

The existing chunk-size advisory remains open for a measured code-splitting
Slice; it does not block this workspace structure boundary.

## Decision

```text
UXM-S12 = PASS / CLOSED
UXM-S13 = AUTHORIZED
```
