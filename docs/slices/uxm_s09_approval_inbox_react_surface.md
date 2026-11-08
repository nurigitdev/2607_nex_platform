# UXM-S09 Approval Inbox React Surface

## Outcome

PASS / CLOSED. The authenticated `/approvals` route now renders a React
Approval Inbox backed by the existing `approvalClient.js` contract and the
S08 user-facing projection. The legacy `approvalUi.js` HTML renderer is not
imported or reused.

## Surface

The route provides:

```text
ApprovalPage
├─ pending / completed / rejected tabs
├─ refresh toolbar
├─ selectable approval list
└─ source-backed approval detail
   ├─ business summary
   ├─ requester / Project / amount / date / risk facts
   ├─ BUSINESS_FORMAL progress
   ├─ attachment evidence summary
   └─ collapsed technical details
```

The current WC inbox contract returns pending gates only. `완료` and `반려`
tabs are therefore visible but disabled, and the surface states that terminal
history is not currently available. No local history, mock terminal item, or
inferred backend capability is presented.

## State Boundary

Approval source outcomes are projected through the existing canonical
`src/ux/workState.ts` module:

| Approval source | Work lifecycle | User outcome |
| --- | --- | --- |
| `PENDING` | `waiting_approval` | 승인 대기 |
| `APPROVED` | `completed` | 승인됨 |
| `REJECTED` | `completed` | 반려됨 |
| `EXPIRED` | `cancelled` | 만료됨 |
| `CANCELLED` | `cancelled` | 취소됨 |

A rejected approval is a completed approval workflow with a rejected outcome;
it is not mislabeled as a failed runtime. Unknown values retain the S08A
fail-closed presentation and never echo the raw input.

## Data and Privacy Decisions

- The list reuses the authorized WC inbox projection.
- The selected detail loads both the WC detail and the S08 AE user projection.
- `OPEN` requester, amount, date, and risk fields render as `정보 미제공`.
- BUSINESS_FORMAL Project identity and approval stage are shown only when the
  authoritative contract provides them.
- Attachment names and aggregate size come from the locked safe manifest.
- Provider, target reference, business operation ID, and gate ID appear only
  inside a closed `기술 상세` disclosure.
- Tenant, subject, source contract, service token, database, and protected
  request metadata are absent from the rendered surface.

## Runtime Integration

The legacy gateway now exposes a typed `ApprovalClientPort`. The conversion
from inferred JavaScript client types occurs once at that gateway. React
features receive the typed port and do not access WC, OA, EOS, database, or
provider endpoints directly.

When an installed runtime is absent, the route shows an explicit unavailable
state. It does not silently create a mock client in the production component.

## Deferred to UXM-S10

```text
Approve / Reject mutations
required rejection reason
confirmation dialog
decision result and next-item behavior
attachment open / download controls
authoritative risk StatusPill
protected React v2 Playwright acceptance
```

## Verification

```text
focused Approval + state tests       = PASS, 14 tests
AE Web Node regression               = PASS, 407 tests
React regression                     = PASS, 69 tests / 15 files
TypeScript typecheck                 = PASS
modern production import audit       = PASS, 21 files
modern browser security audit        = PASS, 22 files
design token consistency             = PASS, 146 variables / 15 components
React v2 production build            = PASS
PostgreSQL / remote providers         = NOT REQUIRED
```

The production build retains the previously recorded third-party `use client`
directive warnings and completes successfully.

## Decision

```text
UXM-S09 = PASS / CLOSED
UXM-S10 = AUTHORIZED
```
