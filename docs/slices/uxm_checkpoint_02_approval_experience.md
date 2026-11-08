# UXM Checkpoint #2: Approval Experience

## Outcome

PASS / CLOSED. The cumulative UXM-S05 through UXM-S10 application shell,
authentication, same-origin runtime, canonical work-state, Approval Inbox,
decision, evidence, and risk experience is admitted for Workspace and Result UX
implementation.

## Commit Boundary

```text
UXM-S05   7c0c0f0a  React application shell, router, and providers
UXM-S06   abf619d1  authentication-first session UX
UXM-S07   20aac93a  production runtime config and same-origin boundary
UXM-S08   944bf02a  approval user-facing projection contract
UXM-S08A  8a572cf3  canonical user-facing work-state mapper
UXM-S09   c78d1387  Approval Inbox React surface
UXM-S10   1966f6ac  approval decision, evidence, and risk UX
```

## Standard Checkpoint Gate

The repository checkpoint gate completed all five commands with exit code zero
in 1,317.05 seconds.

| Check | Result |
|---|---|
| Repository regression and contract validation | PASS |
| Statement coverage | PASS, 98.67% |
| Branch coverage | PASS, 97.34% |
| Golden journey transition audit | PASS |
| Demo-to-product dependency audit | PASS |

Evidence is generated locally at:

```text
reports/quality/checkpoint-latest.json
reports/quality/uxm-checkpoint-02.coverage.json
reports/quality/golden-journey-transition-audit.json
reports/quality/demo-product-dependency-audit.json
```

## Baseline Reconciliation

The first checkpoint run found three stale deployment-lock assertions that
expected the pre-React Node lock to contain exactly four packages. The admitted
UIUX dependency lock now contains 213 exact packages with 213 SHA-512 integrity
records. The smoke decision and tests now derive the expected package inventory
from the canonical lock and continue to fail closed when any package is
unversioned, uses a non-HTTPS source, or lacks integrity evidence.

Focused reconciliation verification passed 21 tests, and the standard
checkpoint gate passed on the subsequent clean rerun.

## Cumulative Frontend Gate

| Check | Result |
|---|---|
| Legacy Node regression | PASS, 408 tests |
| React regression | PASS, 75 tests in 15 files |
| TypeScript no-emit check | PASS |
| Production fixture-import audit | PASS, 21 files |
| Modern browser security audit | PASS, 22 files |
| Token schema, contrast, and CSS drift | PASS, 146 variables / 15 components |
| npm high-severity dependency audit | PASS, 0 vulnerabilities |
| Vite production build | PASS |
| Protected security Playwright smoke | PASS, 4 requests / 8 checks |
| Protected Approval Playwright smoke | PASS, 14 requests / 2 decisions / 9 checks |
| Desktop/mobile screenshot inspection | PASS |
| Git whitespace check | PASS |

Build output:

```text
modern.html               0.63 kB
modern CSS               28.91 kB
modern JavaScript       529.35 kB
```

The JavaScript bundle exceeds Vite's 500 kB advisory threshold. This is not a
functional or security failure; route-level code splitting remains a measured
optimization for a later Slice rather than an untracked checkpoint exception.

## Approval Invariants Preserved

- Authentication is required before the Approval Inbox or detail is rendered.
- Browser requests remain same-origin under the admitted `/ae-api` facade.
- The three approval domains remain distinct and are not collapsed into one
  user-facing state.
- Approve and reject require explicit confirmation; rejection requires a
  non-empty reason.
- Conflict, expiration, denial, retryable server failure, and exact replay are
  represented without exposing service topology or protected fields.
- Evidence metadata is bounded to display-safe facts, attachments, open, and
  download actions.
- Risk labels use the authoritative LOW/MEDIUM/HIGH semantic mapping and do not
  expose raw provider values as the primary user-facing language.
- Successful decisions move focus to the status result and provide a bounded
  next action.

## Protected Browser Evidence

The protected Approval smoke ran the production fetch-mode client against
deterministic same-origin HTTP route doubles. This validates browser routing,
credentials, mutation semantics, and responsive behavior without claiming a
PostgreSQL or remote-provider integration test.

```text
reports/uiux/approval-checkpoint/01-approval-inbox-desktop.png
reports/uiux/approval-checkpoint/02-approved-result-desktop.png
reports/uiux/approval-checkpoint/03-rejected-result-mobile.png
```

The screenshots were inspected for text clipping, incoherent overlap,
horizontal overflow, attachment actions, decision results, and mobile bottom
navigation stability.

## Scope Note

No database migration, PostgreSQL connection, or remote model provider is
required by Checkpoint #2. Backend contract expansion is outside this UI Slice;
the React client consumes the already admitted Approval projection and facade
routes.

## Decision

```text
APPROVAL_UX_CHECKPOINT_2 = PASS / CLOSED
UXM-S11                 = AUTHORIZED
```
