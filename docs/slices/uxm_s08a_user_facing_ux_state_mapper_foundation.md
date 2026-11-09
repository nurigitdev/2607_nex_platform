# UXM-S08A User-Facing UX State Mapper Foundation

## Outcome

PASS / CLOSED. AE Web now has one typed, locale-aware source for the minimum
Approval UX work-state vocabulary. React surfaces can consume a stable label,
tone, semantic icon role, terminal meaning, and default-action presentation
without translating raw runtime states locally.

## Canonical Scope

The initial mapper admits exactly these states:

```text
requested
in_progress
waiting_approval
completed
failed
cancelled
```

Input matching is case-insensitive for presentation. The `isWorkState()` type
guard remains strict to the canonical lowercase values so TypeScript never
narrows an uppercase runtime value to a value it is not.

## Presentation Contract

| State | Korean label | Tone | Icon role | Terminal | Default action presentation |
| --- | --- | --- | --- | --- | --- |
| `requested` | 요청됨 | neutral | request | no | 요청 확인 |
| `in_progress` | 처리 중 | info | progress | no | 진행 확인 |
| `waiting_approval` | 승인 대기 | warning | approval | no | 승인 검토 |
| `completed` | 완료 | success | success | yes | 결과 확인 |
| `failed` | 처리 실패 | danger | error | yes | 재시도 |
| `cancelled` | 취소됨 | neutral | cancelled | yes | none |

Default actions are presentation hints only. They do not grant authorization,
enable a mutation, or replace the Approval decision contract.

## Unknown-State Boundary

Unknown values fail closed to a neutral presentation:

```text
label                = 상태 확인 필요
tone                 = neutral
icon_role            = unknown
terminal             = null
default_action       = null
technical_detail_ref = UX_STATE_UNRECOGNIZED
```

The original enum, provider identifier, runtime job identifier, and other raw
input are not included in the returned presentation. This keeps technical
detail available through a stable support reference without disclosing an
internal identifier in the user surface.

## Internationalization

The existing AE Web message catalog remains the only localization source.
Korean and English keys were added for every work-state label and default
action. Existing catalog parity validation covers the new keys; no parallel
i18n catalog was introduced.

## Extension Boundary

- UXM-S09 maps the authoritative Approval projection into this vocabulary and
  consumes this module from the React Approval surface.
- UXM-S10 may add Approval decision presentation without changing the canonical
  state meanings.
- UXM-S11 extends this same `src/ux/workState.ts` module for Workspace, Result,
  progress, and document terminology.
- Component-local business-state dictionaries remain prohibited in the modern
  React application.
- Legacy `statusLabel()` functions are not migrated in this foundation Slice;
  their removal follows the planned React surface cutover.

## Persistence and Runtime Impact

```text
backend contract change = NONE
database migration      = NONE
PostgreSQL smoke        = NOT APPLICABLE
remote provider         = NOT REQUIRED
browser route change    = NONE
```

## Verification

```text
focused work-state tests          = PASS, 6 tests
AE Web Node regression            = PASS, 407 tests
React regression                  = PASS, 61 tests / 14 files
TypeScript typecheck              = PASS
modern production import audit    = PASS, 20 files
modern browser security audit     = PASS, 21 files
design token consistency          = PASS, 146 variables / 15 components
React v2 production build         = PASS
```

The production build emits the existing third-party `use client` directive
warnings from React Query, React Router, Radix, and Lucide packages. The build
completes successfully and this Slice introduces no new warning category.

## Decision

```text
UXM-S08A = PASS / CLOSED
UXM-S09  = AUTHORIZED
```
