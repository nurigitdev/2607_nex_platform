# NeX AE Web UI/UX Modernization
# Implementation Slice Plan v1.0

**Status:** PRE-IMPLEMENTATION / CODEX-READY SLICE PLAN  
**Program:** NeX Platform v2.1  
**Product:** NeX-AE Web / Assistant Workspace  
**Parent PAD:** `NeX_AE_Web_UI_UX_Modernization_Source_Audit_and_Pre_Architecture_Decision_v1.0.md`
**Mandatory Entry Closure:** `UXM_CA01_Source_Backed_Entry_Baseline_and_Design_Asset_Admission_Closure_v1.0.md`
**Repository:** `nurigitdev/2607_nex_platform`  
**Canonical Branch:** `master`  
**Observed Master HEAD:** `4dcecb6c4a682ef1e94ff3a701d5fffe4faa19d7`  
**Observed HEAD Message:** `Merge v2.1 transition baseline into master`  
**Plan Date:** 2026-11-08  

---

# 1. Purpose

본 문서는 확정된 `NeX AE Web UI/UX Modernization — Source Audit & PAD v1.0`
을 실제 Codex 구현 단위로 분해한다.

핵심 구현 순서는 다음과 같다.

```text
Vite / React Foundation
        ↓
Design System
        ↓
App Shell / Auth
        ↓
Approval Inbox
        ↓
Workspace
        ↓
Document / Artifact
        ↓
UX Acceptance v2
        ↓
Legacy Retirement
```

이번 Modernization의 목표는:

```text
Platform Validation UI
        ↓
Enterprise Work UX
```

로의 전환이다.

단순 CSS 개선이나 visual refresh가 아니다.

---

# 2. Entry Baseline

현재 `master`의 `apps/nex-ae-web`은 다음 상태이다.

```text
src/main.js       = 4,015 lines
src/styles.css    = 1,967 lines

src entries       = 67
Node/JS tests     = 94
Web scripts       = 26

runtime dependency
= none

dev dependency
= Playwright
```

현재 architecture는:

```text
index.html
   ↓
main.js
   ↓
DOM orchestration
   ↓
Client / State / ReadModel / Boundary modules
```

이다.

핵심 Source Audit 결과:

```text
Client / State / ReadModel / Boundary
→ 대부분 DOM independent
→ 재사용 가치 높음

main.js / static HTML / HTML renderer
→ DOM coupling 집중
→ 교체 대상
```

---

# 3. Frozen PAD Decisions

모든 Slice는 다음 결정을 준수한다.

```text
UX-INV-01
React + TypeScript + Vite를 새 View Layer 기반으로 사용한다.

UX-INV-02
기존 Client / State / ReadModel / Boundary logic을 최대한 재사용한다.

UX-INV-03
기능 migration과 전면 TypeScript conversion을 동시에 하지 않는다.

UX-INV-04
Browser는 same-origin /ae-api만 business API로 호출한다.

UX-INV-05
Browser가 OA/WC/EOS/WA/CX/MO를 직접 호출하지 않는다.

UX-INV-06
Browser가 127.0.0.1:810x service port를 호출하지 않는다.

UX-INV-07
normal business UI에서 runtime/provider/route/target/operation 같은
기술 세부정보를 기본 노출하지 않는다.

UX-INV-08
Platform internal state는 User-Facing UX State로 projection한다.

UX-INV-09
UI가 존재하지 않는 business data를 fabrication하지 않는다.

UX-INV-10
Approval / Result projection gap은 AE facade에서 server-side로 닫는다.

UX-INV-11
cross-service DB read를 UI 요구 때문에 추가하지 않는다.

UX-INV-12
production UI에서 implicit mock fallback을 금지한다.

UX-INV-13
기존 Golden Journey의 business/security/accessibility invariant를 보존한다.

UX-INV-14
새 UX는 `ae_web_*_v2` acceptance contract로 검증한다.

UX-INV-15
PWA는 Core Modernization closure 이후 별도 successor로 둔다.
```

---

# 4. Non-Goals

본 계획에서는 다음을 하지 않는다.

```text
NeX backend architecture 재설계
NSL semantics 변경
AgentExecution state 변경
WC approval authority 변경
EOS transaction semantics 변경
WA semantics 변경

전체 JS → TS 일괄 변환
Redux 도입
대형 enterprise component suite 도입
Tailwind 필수 도입
Storybook 필수 도입

PWA Service Worker
Web Push
Offline approval
Offline WRITE
```

---

# 5. Implementation Strategy

Modernization은 Big-Bang Rewrite로 하지 않는다.

```text
Legacy UI
───────────────
현재 index.html
현재 main.js
현재 styles.css
현재 Playwright

        │ parallel
        │
        ▼

React UI v2
───────────────
temporary parallel entry
React/TS/Vite
Design System
new UX tests
new Playwright

        │ parity complete
        ▼

Cutover
───────────────
React becomes canonical root
legacy source retired
```

---

# 6. Recommended Temporary Dual-Entry Strategy

Migration 동안:

```text
/
→ legacy UI

/modern.html
→ React UI v2
```

와 같은 parallel entry를 권고한다.

정확한 temporary filename은 S01에서 freeze할 수 있으나,
의미상 다음 조건이 중요하다.

```text
legacy tests continue to run

new React tests can run independently

production root is not switched until v2 acceptance passes
```

Final retirement 후:

```text
/
→ React UI

legacy entry
→ removed
```

---

# 7. Implementation Bands

```text
Band A — Vite / React Foundation
  S00 ~ S02

Band B — Design System
  S03 ~ S04

Band C — App Shell / Auth
  S05 ~ S07

Band D — Approval Inbox
  S08 ~ S10

Band E — Workspace
  S11 ~ S14

Band F — Document / Artifact / Operations
  S15 ~ S17

Band G — UX Acceptance v2
  S18 ~ S19

Band H — Legacy Retirement / Production Closure
  S20 ~ S22
```

---

# 8. Slice Overview

| Slice | Title |
|---|---|
| UXM-S00 | Pre-Implementation Entry Gate |
| UXM-S01 | Vite / React / TypeScript Parallel Foundation |
| UXM-S02 | Legacy Interop and Reuse Boundary |
| UXM-S03 | NeX Design Token v1 Import and Validation |
| UXM-S04 | Core Design System Components |
| UXM-S05 | React App Shell / Router / Providers |
| UXM-S06 | Authentication and Session UX |
| UXM-S07 | Production Runtime Config and Same-Origin Boundary |
| UXM-S08 | Approval User-Facing Projection Contract Closure |
| UXM-S08A | User-Facing UX State Mapper Foundation |
| UXM-S09 | Approval Inbox React Surface |
| UXM-S10 | Approval Decision / Evidence / Risk UX |
| UXM-S11 | UX State Mapper Completion and Business Terminology |
| UXM-S12 | Workspace / Composer / Context Panel |
| UXM-S13 | Business Result Projection Contract Closure |
| UXM-S14 | Workspace Progress / Result / Grounded Execution Integration |
| UXM-S15 | Document / Upload / Retrieval Modernization |
| UXM-S16 | Artifact / Result Output Modernization |
| UXM-S17 | Operations / Diagnostics Isolation |
| UXM-S18 | UX Acceptance v2 Contract |
| UXM-S19 | Responsive / Accessibility / Playwright v2 Acceptance |
| UXM-S20 | Production Build / Route / Test Cutover |
| UXM-S21 | Legacy Renderer and DOM Orchestration Retirement |
| UXM-S22 | Full Gate / Final As-Built / Handoff |

---

# 9. Branch Strategy

권고 implementation branch:

```text
transition/ae-web-uiux-modernization
```

이 branch는 S01-S22를 통합하는 transition integration branch이다. Slice별
별도 branch를 만들 필요는 없으며, 공개된 이후에는 force-push/rebase로
이력을 다시 쓰지 않는다.

원칙:

```text
branch from current master

Slice 단위 commit

major Checkpoint마다 master와 drift 확인

master 변경이 있으면 merge commit으로 동기화

Final Full Gate 전 최신 master descendant 확인
```

이 계획은 branch 이름 자체를 architecture contract로 보지 않는다.

---

# 10. Testing Policy

각 source Slice는 최소:

```text
npm --prefix apps/nex-ae-web test

targeted React test
targeted Playwright when UI changed

git diff --check
```

를 수행한다.

Backend projection 변경 시:

```text
owning Python service regression
contract validation
PostgreSQL protected test where persistence/transaction is claimed
```

를 추가한다.

---

# 11. Test Preservation Rule

현재 94개 Node/JS test는 migration asset이다.

원칙:

```text
기존 test를 disable해서 migration을 통과시키지 않는다.

Renderer test가 더 이상 유효하지 않으면
React component equivalent test를 먼저 만든 뒤 retire한다.

Business/security test는 유지한다.

Historical P8 tests는 compatibility evidence로 유지한다.
```

---

# 12. Quality Gate Cadence

권고 cadence:

```text
S00
docs/source freeze

S01-S04
Foundation + Design System
→ Checkpoint #1

S05-S07
Shell/Auth + Runtime/Same-Origin
→ Security Boundary Checkpoint

S08-S10 + S08A
Approval Projection + UX State Foundation + Approval UX
→ Checkpoint #2

S11-S14
UX State Completion + Workspace
→ Checkpoint #3

S15-S19
Document/Artifact + UX Acceptance v2
→ Full Web Acceptance #1

S20-S22
Cutover + Retirement + Closure
→ S21 Retirement Checkpoint
→ S22 Repository Full Gate
```

다음 변경은 즉시 escalation 가능:

```text
deployment/oci
serve.mjs
AE facade API
cross-service contract
authentication/session
approval
quality infrastructure
```

---

# 13. UXM-S00 — Pre-Implementation Entry Gate

Status: `SATISFIED BY UXM-CA01`

`UXM-CA01` records the source-backed branch point, current source inventory,
design asset admission, document identity, gate cadence, and Slice ordering.
Do not create a second entry-gate document or repeat S00 as an implementation
Slice.

## Goal

Implementation 전 current source와 PAD를 정확히 고정한다.

## Tasks

1. `master` HEAD 기록.
2. `git status` clean 확인.
3. PAD v1.0 읽기.
4. collaborator design baseline 확인.
5. source disposition ledger 확인.
6. current AE Web test inventory freeze.

## Create

권고:

```text
docs/transition/UIUX/
NeX_AE_Web_UIUX_Modernization_Entry_Gate_v1.0.md
```

## Freeze Facts

```text
main.js lines
styles.css lines
src file count
Node test count
Playwright/script count
package dependencies
master commit
```

## Verify

```text
docs-only checks
git diff --check
```

## Exit

```text
source baseline frozen
implementation branch ready
S01 authorized
```

---

# 14. UXM-S01 — Vite / React / TypeScript Parallel Foundation

## Goal

현재 legacy UI를 깨지 않고 React v2 실행 기반을 만든다.

## Add Dependencies

Exact version은 `package-lock.json`으로 pin한다.

Core:

```text
react
react-dom
typescript
vite
```

Test:

```text
vitest
jsdom
@testing-library/react
@testing-library/user-event
```

## Add Source

예:

```text
apps/nex-ae-web/
  modern.html                 [temporary]
  vite.config.ts
  tsconfig.json
  tsconfig.app.json
  src/app/main.tsx
  src/app/App.tsx
```

정확한 tsconfig split은 구현에 따라 단순화 가능.

## TypeScript Interop

초기 원칙:

```text
allowJs = true
```

기존 JS module을 React TS code에서 import 가능하게 한다.

금지:

```text
이 Slice에서 기존 60+ JS module을 TS로 변환
```

## Temporary UI

React entry는 최소:

```text
NeX AE
UI Modernization Foundation
```

정도만 렌더링한다.

Business function 구현 금지.

## Existing Legacy

다음은 변경 최소화:

```text
index.html
src/main.js
src/styles.css
```

## npm Scripts

개념:

```text
dev:legacy
dev:v2
build:v2
test:react
test
```

기존 `npm test` semantics를 깨지 않는다.

## Tests

```text
React mount test
Vite config test/build
legacy Node tests
```

## Exit

```text
legacy UI still runs
React v2 runs independently
Vite production build succeeds
existing tests PASS
```

---

# 15. UXM-S02 — Legacy Interop and Reuse Boundary

## Goal

기존 JS logic을 React에서 안전하게 재사용할 boundary를 만든다.

## Reuse Targets

대표:

```text
clientRegistry.js
runtimeConfig.js
applicationShell.js
sessionClient.js
sessionBootstrap.js
sessionRouteGuard.js
operationState.js
approvalClient.js
artifactClient.js
retrievalClient.js
groundedGenerationClient.js
```

## Create

예:

```text
src/app/legacyAdapters/
src/app/api/
src/app/domain/
```

실제 file move는 최소화한다.

가능하면 wrapper만 만든다.

## Rule

```text
React Component
→ adapter/hook
→ existing Client
```

Component가 legacy module internals를 직접 수정하지 않는다.

## Production Import Audit

React production source가 다음 test-only asset을 import하지 않도록 검사한다.

```text
artifactMockRecord.js
credentialLoginHarness.js
deterministicGoldenJourney.js
fetchModeHarness.js
goldenJourney*.js
```

## Tests

```text
JS module import from TS
mock client adapter
fetch client adapter
safe projection
no test-fixture dependency
```

## Exit

```text
React can reuse current logic without copy/paste
no business logic duplicated
```

---

# 16. UXM-S03 — NeX Design Token v1 Import and Validation

## Goal

collaborator가 제공한 `tokens.json`을 canonical design token source로 승격한다.

## Import

권고:

```text
src/design-system/tokens/tokens.json
src/design-system/tokens/tokens.css
```

Admitted 원본:

```text
docs/transition/UIUX/tokens.json
docs/transition/UIUX/tokens.css
```

`tokens.json`은 S03의 canonical candidate이고 `tokens.css`는 제공된
reference/generated candidate이다. S03은 JSON에서 CSS를 재생성하여
동일성을 검증한 뒤 application source로 승격한다.

## Source of Truth

```text
tokens.json
→ canonical

tokens.css
→ generated artifact
```

수동 이중수정 금지.

## Add Generator

예:

```text
scripts/generateDesignTokens.mjs
```

## Validate

```text
primitive refs resolve
semantic refs resolve
light/dark completeness
spacing/radius/type value validity
duplicate token detection
generated CSS drift detection
```

## Contrast Regression

collaborator baseline의 contrast 조합을 test로 옮긴다.

목표:

```text
WCAG 2.2 AA
```

## Existing CSS

현재 `styles.css`를 아직 제거하지 않는다.

## Tests

```text
token schema
CSS generation snapshot
contrast
dark/light semantic parity
```

## Exit

```text
tokens.json canonical
tokens.css reproducible
contrast PASS
```

---

# 17. UXM-S04 — Core Design System Components

## Goal

업무화면 구현 전 reusable primitive를 먼저 만든다.

## Core Components

1차:

```text
Button
IconButton
Input
Select
Textarea
Checkbox
Radio
Badge
StatusPill
Card
Tabs
NavItem
Table/List
Drawer
Modal
ConfirmDialog
Toast
Stepper
EmptyState
Avatar
Tooltip
```

모두 한 Slice에서 완성할 필요는 없지만
Approval 구현에 필요한 최소 set은 닫는다.

## Accessible Primitives

필요한 복합 interaction에는 선택적으로:

```text
@radix-ui/*
```

사용.

## Icons

```text
lucide-react
```

사용.

원칙:

```text
decorative → aria-hidden
icon-only button → aria-label required
status → icon + text
```

## Styling

```text
CSS Modules
+
Design Token
```

사용.

arbitrary color/spacing 금지.

## Tests

각 component:

```text
render
keyboard
disabled
focus
accessible name
variant
dark token
```

## Visual Contract

기본 component screenshot을 생성할 수 있으나
pixel-perfect snapshot을 sole gate로 삼지 않는다.

## Checkpoint #1

S01-S04 완료 후:

```text
legacy Node tests
React tests
Vite build
token tests
accessibility primitive tests
git diff --check
```

## Exit

```text
Design System foundation usable
Approval screen 구현 가능
```

---

# 18. UXM-S05 — React App Shell / Router / Providers

## Goal

새 UI의 navigation과 provider structure를 구현한다.

## Add

```text
React Router
TanStack Query
I18n bridge
Theme provider
Query provider
Session provider
```

## Routes

초기:

```text
/login
/workspace
/approvals
/upload
/documents
/retrieval
/artifacts
/operations
```

`upload`/`retrieval`은 migration compatibility route이다.

## Reuse

현재:

```text
applicationShell.js
  canAccessOperations()
  allowedApplicationViews()
```

를 route policy에 재사용한다.

## Retire Later

```text
viewFromLocationHash()
```

는 v2에서 사용하지 않는다.

## Sidebar

normal user:

```text
Workspace
Approvals
Documents
Artifacts
```

Operations:

```text
admin/operator only
```

Compatibility menu는 필요 시 hidden/secondary.

## Tests

```text
anonymous redirect
authenticated route
operations role guard
unknown route
mobile route navigation
```

## Exit

```text
React shell route-safe
role-safe
```

---

# 19. UXM-S06 — Authentication and Session UX

## Goal

현재 credential login contract를 유지하면서 실제 사용자용 Login 화면으로 전환한다.

## Reuse

```text
credentialLoginSurface.js
sessionClient.js
sessionBootstrap.js
sessionRouteGuard.js
sessionIdentityPresentation.js
authBoundary.js
```

## New UI

표시:

```text
NeX AE
사번
비밀번호
로그인
```

지원:

```text
password show/hide
Caps Lock indication
loading
invalid credentials
session expired
logout
```

## Tenant

기본 UI에서:

```text
tenant-local
```

을 노출하지 않는다.

하지만 request contract에 필요하면
runtime/deployment resolved value를 사용한다.

## Do Not Show

```text
READY_FOR_LOGIN
route guard count
session schema
technical auth state
```

## Tests

```text
field validation
keyboard submit
error mapping
password cleared
session route activation
logout
expiration
no credential summary leak
```

## Protected Playwright

기존:

```text
AuthenticationFirstShell
CredentialLogin
```

acceptance를 new React entry 대상으로 병행 추가한다.

## Exit

```text
auth parity PASS
technical metadata hidden
```

---

# 20. UXM-S07 — Production Runtime Config and Same-Origin Boundary

## Goal

새 React UI의 production runtime mode와 browser network boundary를 fail-closed로 고정한다.

## Current Problem

현재 default:

```text
client_mode = mock
fetch_clients_enabled = false
```

이다.

## Target

Test/demo:

```text
mock explicitly allowed
```

Installed/production:

```text
client_mode = fetch
ae_base_url = /ae-api
fetch_clients_enabled = true
```

명시적으로 필요.

## Failure Rule

production profile에서 runtime config 누락/invalid:

```text
startup FAIL
```

silent mock 금지.

## Same-Origin Audit

React UI에서:

```text
/ae-api/*
```

business fetch만 허용.

금지:

```text
http://127.0.0.1:810x
direct service URL
provider URL
```

## New Test

Browser request audit:

```text
localhost:810x detected → FAIL
non-AE business origin → FAIL
service token in bundle/config → FAIL
```

## Current Legacy

legacy `main.js` direct health call은 아직 존재 가능하다.

하지만 v2 React source에서는 없어야 한다.

최종 S21에서 legacy 제거와 함께 완전 폐기한다.

## Checkpoint

Auth/runtime boundary 변경이므로 early Checkpoint 권고.

## Exit

```text
v2 production cannot silently run mock
v2 browser same-origin only
```

---

# 21. UXM-S08 — Approval User-Facing Projection Contract Closure

## Goal

Approval 화면을 구현하기 전 필요한 business information의 authoritative source를 닫는다.

## Current Available

현재 frontend projection:

```text
domain
state
title
summary
expires_at
provider type
target ref
business operation id
formal stage
project_id
attachment manifest
```

## Target UX Fields

source audit:

```text
requester display
requested_at
project display name
amount
currency
business date
account
risk level
risk explanation
business line items
```

## Work

각 field에 대해:

```text
Existing?
Source owner?
AE facade path?
Privacy classification?
Required/optional?
```

matrix 작성.

## No Fabrication

source가 없으면:

```text
OPEN
```

으로 기록.

UI mock 값을 product contract에 넣지 않는다.

## Backend Change

필요할 경우:

```text
AE facade user-facing approval projection
```

을 additive하게 보강한다.

## Boundary

금지:

```text
Browser → WC
Browser → EOS
Browser → OA

Browser-side join

cross-service DB read
```

## Contract

예:

```text
ae_user_approval_projection.v1
```

정확한 이름은 Source Audit 결과로 확정.

## Tests

```text
schema
redaction
tenant isolation
missing optional value
requester resolution
Project display
amount/account when applicable
```

필요한 persistence claim은 actual PostgreSQL protected acceptance 추가.

## Exit

```text
Approval UI data contract source-backed
S08A authorized
```

---

# 21A. UXM-S08A — User-Facing UX State Mapper Foundation

## Goal

Approval 화면을 만들기 전에 internal state를 user-facing vocabulary로
변환하는 단일 foundation을 활성화한다.

## Add

```text
src/ux/workState.ts
src/ux/workState.test.ts
```

## Initial Scope

S08A는 Approval UX에 필요한 최소 mapping을 먼저 닫는다.

```text
requested
in_progress
waiting_approval
completed
failed
cancelled
```

각 상태는 다음 presentation을 source-backed mapping으로 제공한다.

```text
label
tone
icon role
terminal/non-terminal
allowed default action presentation
```

## Invariant

```text
same internal state
→ same user-facing meaning
→ Approval, Workspace, Result에서 재사용
```

React component가 raw state를 자체 번역하거나 별도 상태 vocabulary를
만들어서는 안 된다. Unknown state는 fail-closed neutral presentation과
안전한 technical detail reference를 사용한다.

## Tests

```text
known state mapping
unknown state fallback
terminal state semantics
tone/icon accessibility
internal identifier non-disclosure
ko/en message-key parity
```

## Follow-up

S11은 같은 module을 Workspace, progress, result, document terminology까지
확장하는 completion Slice이다. 별도의 mapper를 만들지 않는다.

## Exit

```text
Approval UX state vocabulary source-backed
S09 authorized
```

---

# 22. UXM-S09 — Approval Inbox React Surface

## Goal

Approval Inbox의 list/detail experience를 React로 구현한다.

## Component Tree

```text
ApprovalPage
├─ ApprovalTabs
├─ ApprovalToolbar
├─ ApprovalList
│  └─ ApprovalListItem
└─ ApprovalDetail
```

## Tabs

최소:

```text
대기
완료
반려
```

현재 API projection이 terminal history를 제공하지 않는다면
지원 가능한 범위만 구현하고 OPEN으로 남긴다.

## List Fields

예:

```text
요청 업무
요청자
Project
금액 [when applicable]
요청 시각
risk
status
```

## Detail

```text
business summary
Project
requester
evidence
attachment
approval progress
```

## Technical Detail

접힌:

```text
기술 상세
```

에서만:

```text
provider
target ref
business operation id
technical ID
```

노출.

## Reuse

```text
approvalClient.js
isApprovalGateExpired()
```

## Do Not Reuse

```text
approvalUi.js HTML renderer
```

## Tests

```text
list loading
empty
error
selection
expired
formal approval
attachment count
technical details collapsed
privacy
```

## Exit

```text
Approval read UX parity PASS
```

---

# 23. UXM-S10 — Approval Decision / Evidence / Risk UX

## Goal

실제 Human Gate 결정을 user-friendly하게 완성한다.

## Actions

```text
Approve
Reject
```

Reject:

```text
reason required
```

Approve/Reject:

```text
ConfirmDialog
```

## Risk

risk가 authoritative하게 제공되는 경우:

```text
low
medium
high
```

를 semantic `StatusPill`로 표시.

risk data가 없으면 production에서 mock risk를 만들지 않는다.

## Evidence

```text
attachment list
open
download
count
size
```

현재 safe manifest를 재사용.

## Decision Result

결정 후:

```text
action disabled/removed
decision status shown
next item affordance
```

## Tests

```text
approve
reject
reason required
409 conflict
expired
403
retryable server error
attachment access
keyboard
screen reader
```

## Protected Playwright

기존:

```text
approval UI
approval protected
business formal approval
voucher attachment
```

journey를 React v2에도 적용.

## Checkpoint #2

S05-S10 + S08A cumulative Checkpoint.

## Exit

```text
Approval Inbox end-to-end UX PASS
```

---

# 24. UXM-S11 — UX State Mapper Completion and Business Terminology

## Goal

S08A의 canonical mapper를 Workspace, progress, result, document language로
확장하고 전체 화면의 terminology를 formalize한다.

## Add

S08A에서 생성한 source를 확장한다.

```text
src/ux/workState.ts
src/ux/terminology.ts
```

## UX State

```text
IDLE
ACCEPTING
PLANNING
RUNNING
WAITING_APPROVAL
RESUMING
VERIFYING
SUCCEEDED
PARTIAL
FAILED
CANCELLED
```

## Map From

```text
AgentExecution
GenerationLifecycle
Approval
ResultDelivery
Artifact
OperationState
```

## Invariant

같은 internal state는 모든 화면에서 같은 user meaning을 가져야 한다.

## Terminology

예:

```text
SUCCEEDED → 완료
HUMAN GATE → 승인
Artifact → 결과물
READY_FOR_PROMPT → 입력 대기
```

## Technical State

필요 시:

```text
debug detail
```

에서만 original enum 표시.

## Tests

```text
all admitted states
unknown state
partial
approval waiting
failure
cancelled
no fake progress
```

## Exit

```text
single UX status vocabulary active
```

---

# 25. UXM-S12 — Workspace / Composer / Context Panel

## Goal

새 AE의 primary business workspace를 구축한다.

## Layout

Desktop:

```text
Sidebar
Main Workspace
Context Panel
```

## Main

```text
Conversation
Composer
Primary Result
```

## Context

Tabs:

```text
진행
첨부
출처
```

## Composer

```text
auto-grow textarea
attachment chips
optional evidence toggle
optional output format
send
cancel when supported
```

## Empty State

```text
인사말
추천 업무
최근 작업 [source-backed only]
```

## Do Not Show

```text
workspace UUID
route
provider
operation
raw internal status
```

## Reuse

```text
groundedGenerationWorkflow.js
groundedGenerationClient.js
operationState.js
documentScope.js
```

## Tests

```text
empty
typing
submit
running
cancel
retry
context tab
attachment chip
mobile
```

## Exit

```text
Workspace shell usable
```

---

# 26. UXM-S13 — Business Result Projection Contract Closure

## Goal

사용자에게 의미 있는 업무 결과를 안전하게 표시할 projection을 닫는다.

## Current Generic Result

현재:

```text
execution state
result status
business refs
external refs
artifact refs
warnings
delivery state
```

## Needed

Golden A 같은 업무 결과:

```text
voucher number
amount
account
Project
approval state
business object link
```

## Decision

Generic AgentResult raw parsing 금지.

필요할 경우:

```text
Typed Business Result Summary
```

를 AE facade에 추가한다.

예:

```text
result_type
summary_schema_version
summary
```

## Source Audit

각 result type별:

```text
SoR
owner service
privacy
projection
```

확정.

## No Cross-Service DB

server-side owner API/facade 사용.

## Tests

```text
Golden A result
generic result
unknown result type
missing optional data
redaction
tenant/project isolation
```

## Exit

```text
Workspace Result Card source-backed
```

---

# 27. UXM-S14 — Workspace Progress / Result / Grounded Execution Integration

## Goal

Workspace가 실제 NeX Agent work state를 자연스럽게 보여주도록 한다.

## Integrate

```text
UX State Mapper
Grounded Generation
Interaction Agent Result
Typed Business Result
Artifacts
Approval wait
```

## Stepper

actual durable state만 사용.

예:

```text
요청 접수
업무 계획
처리
승인 대기
결과 확인
완료
```

실제 flow에 없는 단계는 표시하지 않는다.

## Result Card

```text
business title
status
business summary
evidence
result artifact
warning
```

## Raw Result

기본 hidden.

## Error UX

```text
human-readable reason
retry possible?
next action
```

technical code는 secondary.

## Tests

```text
planning
running
approval wait
resume
success
partial
failure
artifact result
grounded citations
```

## Checkpoint #3

S11-S14 cumulative Checkpoint.

## Exit

```text
Golden A user journey readable
```

---

# 28. UXM-S15 — Document / Upload / Retrieval Modernization

## Goal

기술 기능을 실제 업무 흐름의 언어로 바꾼다.

## Reuse

```text
documentDetailClient.js
documentScope.js
uploadClient.js
uploadProgressClient.js
uploadSurface.js model
retrievalClient.js
retrievalQualityWarnings.js
```

## UI Language

```text
Upload
→ 파일 첨부

Retrieval
→ 문서/근거 선택

Retrieval Context
→ 사용한 출처
```

## Documents

```text
list
detail
processing
summary/confidence
owner scope
```

## Security

local storage path, provider URL 등 금지.

## Top-Level Routes

migration 동안:

```text
/upload
/retrieval
```

유지 가능.

최종 UX에서 Workspace 안으로 통합 여부는 구현 결과로 판단.

## Tests

```text
file selection
upload progress
duplicate
error/retry
document detail
wrong owner
retrieval no-answer
low confidence
source display
```

## Protected

existing upload/document Playwright v2 target.

## Exit

```text
Document flow parity
```

---

# 29. UXM-S16 — Artifact / Result Output Modernization

## Goal

현재 성숙한 Artifact 기능을 사용자 중심 결과물 UX로 전환한다.

## Reuse

```text
artifactClient.js
artifactCardReadModel.js
artifactLifecycleActionState.js
artifactDeliveryActionState.js
artifactDownloadSaveAdapter.js
artifactLibraryPanel model
artifactPreviewPanel model
artifactVersionPanel model
artifactExportResultReadModel model
```

## React Components

```text
ResultArtifactCard
ArtifactLibrary
ArtifactPreview
ArtifactVersions
ArtifactDownload
ArtifactLifecycleActions
```

## Default Terminology

일반:

```text
결과물
문서
파일
```

Technical/detail:

```text
Artifact
```

허용.

## Renderer Retirement Preparation

다음 legacy renderer와 parity 비교:

```text
artifactCard.js
artifactLibraryPanel render*
artifactPreviewPanel render*
artifactVersionPanel render*
artifactExportResultReadModel render*
```

## Tests

```text
preview
download
versions
restore
archive/delete as permitted
export
error
private/owner-safe
```

## Exit

```text
Artifact business UX parity PASS
```

---

# 30. UXM-S17 — Operations / Diagnostics Isolation

## Goal

일반 사용자 UI에서 Platform internals를 제거하면서
operator 기능은 보존한다.

## Route

```text
/operations
```

admin/operator only.

## Move Here

```text
Runtime diagnostics
Service health
technical IDs
routes
provider detail
safe execution detail
```

## Replace Direct Health

현재 legacy:

```text
Browser → 127.0.0.1:810x
```

기능을:

```text
Browser
→ /ae-api
→ AE/AG safe operations projection
```

으로 대체한다.

## New Backend Projection

필요한 경우:

```text
AE Operations Summary
```

또는 existing AG projection 재사용.

## Authorization

UI hide만으로 보안하지 않는다.

backend authorization 필요.

## Tests

```text
normal employee → 403/not visible
admin/operator → visible
safe technical data only
no secret
same-origin only
service unavailable
```

## Exit

```text
business UI clean
operations preserved
```

---

# 31. UXM-S18 — UX Acceptance v2 Contract

## Goal

새 UI가 old DOM contract에 묶이지 않도록 v2 acceptance를 먼저 freeze한다.

## Create

예:

```text
src/acceptance/uxAcceptanceV2.ts
```

또는 pure JS/TS module.

Schema concept:

```text
ae_web_ux_acceptance.v2
```

## Required Viewports

기존 유지:

```text
desktop = 1440×900
mobile  = 390×844
```

## Required Invariants

```text
html lang = ko

single visible main

single h1

required v2 regions

no horizontal overflow

all visible controls named

minimum target >= 24px

focus visible

primary regions non-overlap

normal user has no runtime debug leakage

no direct service request

no protected data
```

## Proposed Regions

```text
app_shell
sidebar
topbar
main_content
workspace
context_panel
composer
primary_result
```

Mobile에서 context panel은 Drawer로 인정 가능.

## v1

기존:

```text
ae_web_golden_journey_viewport.v1
```

은 historical evidence로 유지.

## Exit

```text
v2 contract frozen before final Playwright
```

---

# 32. UXM-S19 — Responsive / Accessibility / Playwright v2 Acceptance

## Goal

React UI 전체를 실제 browser로 검증한다.

## Desktop

```text
1440×900
```

## Mobile

```text
390×844
```

## Playwright Journeys

최소:

```text
Login
Approval
Workspace request
Approval waiting/resume [fixture/source-backed]
Result
Document
Artifact
Operations authorization
```

## Accessibility

검사:

```text
keyboard
focus
accessible names
Dialog focus
Drawer focus restore
aria-live
status text
target size
contrast
no color-only meaning
```

## Responsive

검사:

```text
no overflow
no overlap
sidebar/mobile navigation
context drawer
approval list/detail
composer sticky behavior
```

## Screenshot Evidence

각 major screen:

```text
login
approval
workspace
result
document/artifact
```

desktop/mobile evidence.

## Browser Boundary Audit

request log 검사:

```text
/ae-api allowed

127.0.0.1:810x fail
direct service host fail
```

## Full Web Acceptance #1

여기까지 완료 후:

```text
legacy Node test PASS
React test PASS
new Playwright v2 PASS
selected existing Playwright PASS
Vite build PASS
```

## Exit

```text
React UI v2 functionally accepted
legacy retirement authorized
```

---

# 33. UXM-S20 — Production Build / Route / Test Cutover

## Goal

React UI를 canonical production web artifact로 승격할 준비를 한다.

## Vite Production Build

Target:

```text
dist/
```

## Container

`deployment/oci/ae-web.Containerfile`을 multi-stage로 전환.

Concept:

```text
build stage
  npm ci
  vite build

runtime stage
  Node
  dist/
  serve.mjs
```

## `serve.mjs`

Reuse + update:

```text
serve dist
SPA fallback
preserve /ae-api proxy
asset MIME
safe cache headers
```

## Production Runtime Config

Installed deployment:

```text
fetch mode required
/ae-api same-origin
```

## Route Cutover

Root:

```text
/
→ React
```

temporary modern route는 제거 또는 redirect 준비.

## Test Migration

기존 Playwright selector를:

```text
role
accessible name
data-testid [only where needed]
```

중심으로 migration.

## OCI Acceptance

```text
non-root
package-lock
build provenance
no source secret
browser config safe
```

## Exit

```text
React production artifact ready
legacy source still present but inactive
```

---

# 34. UXM-S21 — Legacy Renderer and DOM Orchestration Retirement

## Goal

React parity가 증명된 이후 legacy production code를 제거한다.

## Retire

```text
src/main.js
src/styles.css
approvalUi.js
artifactCard.js
voucherAttachmentUi.js
legacy full static index markup
```

## Retire Render Functions

해당 pure model과 함께 있던:

```text
renderInteractionAgentResult
renderArtifactDownloadFormatSelector
renderArtifactExportResultReadModel
renderArtifactLibraryPanel
renderArtifactPreviewPanel
renderArtifactVersionPanel
renderProjectMembershipBatchResult
renderRepairedResponseReviewCard
applyDocumentMessages
viewFromLocationHash
```

은 React parity 확보 후 제거.

## Important

pure builder/read model은 제거하지 않는다.

예:

```text
build*
create*
normalize*
assert*
findSensitive*
```

## Direct Health

legacy source 제거로:

```text
Browser → localhost service
```

path가 repository active production source에서 완전히 없어야 한다.

## Legacy Dependency Audit

새 audit 추가 권고:

```text
run_ae_web_legacy_dependency_audit.*
```

검사:

```text
no main.js production import
no old renderer import
no styles.css import
no direct service URL
no implicit mock production
```

## Historical Tests

old renderer-only test는:

```text
replacement React test 존재
```

확인 후 retire.

## Exit

```text
React is sole production UI
legacy DOM orchestration absent
```

---

# 35. UXM-S22 — Repository Full Gate / Final As-Built / Handoff

## Goal

UI/UX Modernization을 공식 종료한다.

## Create

```text
docs/transition/UIUX/
NeX_AE_Web_UIUX_Modernization_Final_AsBuilt_v1.0.md
```

## Record

```text
exact commit/tree
React/Vite versions
package-lock hash
Design Token version/hash
production container digest
route inventory
test counts
Playwright acceptance
desktop/mobile screenshots
accessibility checks
legacy retirement audit
same-origin audit
```

## Full Gate

Repository canonical Full Gate 실행.

추가:

```text
npm --prefix apps/nex-ae-web test
React/Vitest suite
UX Acceptance v2 Playwright
existing canonical Golden Journey
OCI/package acceptance
git diff --check
```

## Final Decision

```text
NeX AE Web UI/UX Modernization = CLOSED
React UI = CANONICAL
Legacy UI = RETIRED
PWA Phase = NOT STARTED / SUCCESSOR
```

---

# 36. Gate Matrix

| Slice | Node | React Unit | Playwright | Backend | Full/Checkpoint |
|---|---:|---:|---:|---:|---|
| S00 | - | - | - | - | docs |
| S01 | ✓ | ✓ | - | - | Slice |
| S02 | ✓ | ✓ | - | - | Slice |
| S03 | ✓ | ✓ | - | - | Slice |
| S04 | ✓ | ✓ | optional | - | Checkpoint |
| S05 | ✓ | ✓ | targeted | - | Slice |
| S06 | ✓ | ✓ | auth | optional | Slice |
| S07 | ✓ | ✓ | network audit | - | Checkpoint |
| S08 | ✓ | optional | - | ✓ | Escalated |
| S08A | ✓ | ✓ | - | - | Slice |
| S09 | ✓ | ✓ | targeted | - | Slice |
| S10 | ✓ | ✓ | approval | ✓ if needed | Checkpoint |
| S11 | ✓ | ✓ | - | - | Slice |
| S12 | ✓ | ✓ | workspace | - | Slice |
| S13 | ✓ | optional | - | ✓ | Escalated |
| S14 | ✓ | ✓ | workspace | ✓ if needed | Checkpoint |
| S15 | ✓ | ✓ | docs/upload | - | Slice |
| S16 | ✓ | ✓ | artifact | - | Slice |
| S17 | ✓ | ✓ | ops | ✓ | Escalated |
| S18 | ✓ | ✓ | contract | - | Slice |
| S19 | ✓ | ✓ | full v2 | - | Full Web |
| S20 | ✓ | ✓ | prod route | - | Escalated |
| S21 | ✓ | ✓ | full v2 | - | Checkpoint |
| S22 | ✓ | ✓ | protected | ✓ | Full Gate |

---

# 37. Codex Slice Start Checklist

각 Slice 시작 전 Codex는:

```text
1. git status
2. current HEAD
3. PAD
4. current Slice requirements
5. impacted existing tests
6. source structure
7. refactor necessity
```

를 확인한다.

특히 기존 code가 새 component를 자연스럽게 수용하지 못하면:

```text
small refactor first
```

원칙을 적용한다.

---

# 38. Commit Rule

각 Slice:

```text
implementation
→ focused test
→ regression
→ gate
→ git diff --check
→ commit
```

완료 후 다음 Slice로 이동한다.

추천 commit theme:

```text
feat(ae-web): add React modernization foundation
feat(ae-web): freeze design tokens
feat(ae-web): add design system primitives
feat(ae-web): add React application shell
feat(ae-web): modernize authentication
feat(ae-web): add approval workbench
feat(ae-web): add workspace experience
feat(ae-web): modernize document workflow
feat(ae-web): modernize result artifacts
test(ae-web): freeze UX acceptance v2
refactor(ae-web): retire legacy DOM shell
docs(ae-web): freeze UIUX modernization baseline
```

---

# 39. Coverage / Test Quality

JavaScript coverage percentage 자체를 Python repository 기준과 억지로 맞추지 않는다.

대신 중요 component/domain에 대해:

```text
behavior branch
accessibility branch
error/retry
privacy
authorization
responsive
```

를 explicit test한다.

향후 JS coverage tool 도입은 별도 결정 가능.

현재 primary quality evidence:

```text
Node regression
React unit/component regression
Playwright
Golden Journey
Accessibility
Network boundary
```

이다.

---

# 40. Design Token Drift Gate

S03 이후 모든 UI Slice는:

```text
no arbitrary production hex
no arbitrary status color
no duplicated semantic token
```

정책을 적용한다.

예외:

```text
third-party asset
document preview
user content
```

는 별도.

---

# 41. Component Ownership Rule

Feature가 직접:

```text
button style
modal behavior
toast
badge color
focus ring
```

을 구현하지 않는다.

Design System을 사용한다.

---

# 42. API Ownership Rule

React component가 URL string을 직접 조립하지 않는다.

```text
Component
→ query/hook
→ existing Client
→ route builder
```

구조 유지.

예외:

```text
static navigation route
```

만 허용.

---

# 43. Query Policy

TanStack Query의 query key는 canonical하게 관리한다.

예:

```text
["session"]
["approvals", filters]
["approval", gateId]
["documents", scope]
["artifact", artifactId]
```

mutation 후:

```text
invalidate exact affected keys
```

를 사용.

무분별한 global invalidate 금지.

---

# 44. Polling Policy

Agent work / upload progress 등 polling:

```text
bounded
visible-screen-aware
terminal state stop
error backoff
```

필수.

background hidden tab에서 aggressive polling 금지.

---

# 45. Error UX

기본:

```text
사용자 메시지
다음 행동
retry 여부
```

Technical error code는:

```text
details
```

에 넣는다.

예:

```text
처리를 완료하지 못했습니다.
다시 시도할 수 있습니다.

[다시 시도]

기술 상세:
AE_WORKSPACE_RESULT_CONFLICT
```

---

# 46. Loading UX

금지:

```text
spinner everywhere
```

권고:

```text
skeleton
inline progress
specific status text
```

Approval action 등 critical mutation은:

```text
button pending state
duplicate submit prevention
```

필수.

---

# 47. Empty State

각 주요 screen은 empty state를 별도로 가진다.

```text
Approval
→ 승인 대기 업무가 없습니다.

Documents
→ 등록된 문서가 없습니다.

Artifacts
→ 생성된 결과물이 없습니다.

Workspace
→ 업무를 요청해 보세요.
```

Empty와 Error를 같은 화면으로 처리하지 않는다.

---

# 48. Technical Detail Disclosure

재사용 가능한:

```text
TechnicalDetails
```

component를 만든다.

기본 collapsed.

허용 정보:

```text
correlation/reference
technical status
route label [safe]
```

금지:

```text
secret
DB
provider credential
storage path
raw hidden payload
```

---

# 49. Operations Isolation Acceptance

최종 일반 employee journey에서:

```text
Runtime diagnostics text
service health
provider
route
operation id
```

가 기본 화면에 없음을 Playwright로 검사한다.

---

# 50. Approval Business Data Acceptance

승인 상세에서 source-backed field가 있을 경우:

```text
requester
Project
amount
evidence
risk
```

가 표시되는지 검증.

없는 field는 UI에서 임의 생성하지 않았는지 검증.

---

# 51. Result Business Data Acceptance

Golden A 결과에서 contract가 제공하면:

```text
voucher
amount
account
Project
```

가 표시되는지 검증.

Generic AgentResult에서는 generic safe result만 표시.

---

# 52. Privacy Acceptance

React bundle / DOM / screenshot evidence에서 금지:

```text
password
service token
database_url
provider_url
storage path
OpenBao secret
raw protected payload
```

자동 grep/audit 권고.

---

# 53. Mobile Acceptance

특히 검증:

```text
login form
approval list/detail
workspace composer
context drawer
artifact action
```

390px viewport에서 horizontal scroll 금지.

---

# 54. Dark Mode Acceptance

Core screen:

```text
Login
Approval
Workspace
```

에 대해서 light/dark contrast 확인.

Dark mode 때문에 S09/S12 business flow가 지연되면
기능을 먼저 닫고 S19에서 전체 마감 가능.

---

# 55. Reduced Motion

`prefers-reduced-motion` 지원.

Stepper/Toast/Drawer animation은:

```text
non-essential
```

로 구현.

---

# 56. Font Policy

Pretendard는 optional preferred font.

Bundled font가 없으면:

```text
Apple SD Gothic Neo
Malgun Gothic
system-ui
```

fallback.

Font file을 repository에 새로 넣기 전
license/size 검토.

---

# 57. Legacy Compatibility Duration

Legacy UI는:

```text
S01 ~ S19
```

동안 compatibility surface로 유지 가능.

S19 PASS 후 retirement 시작.

Legacy에 신규 feature 추가는 금지.

예외:

```text
security defect
migration blocker
```

만 수정.

---

# 58. No Parallel Product Logic

Migration 중 다음을 금지한다.

```text
legacy approval logic
+
new React approval logic
```

를 각각 별도 구현.

둘 다:

```text
approvalClient.js
```

같은 canonical logic을 사용한다.

---

# 59. Backend Projection Change Discipline

S08/S13/S17에서 backend 변경이 필요하면:

```text
Source Audit
→ Contract
→ API
→ Test
→ UI
```

순서.

UI mock부터 만들고 backend를 맞추지 않는다.

---

# 60. Projection Versioning

새 user-facing projection은 versioned schema 사용.

예:

```text
ae_user_approval_projection.v1
ae_business_result_summary.v1
ae_operations_summary.v1
```

정확한 이름은 source owner와 contract를 보고 결정.

---

# 61. No Business Logic in React

React에서 금지:

```text
approval authority calculation
Project membership authority
voucher calculation
risk business rule
cost calculation
```

UI는:

```text
presentation
interaction
validation of user input shape
```

만 담당한다.

---

# 62. Suggested Folder Target

Final target example:

```text
apps/nex-ae-web/
├─ index.html
├─ package.json
├─ vite.config.ts
├─ tsconfig.json
├─ src/
│  ├─ app/
│  ├─ design-system/
│  ├─ features/
│  ├─ ux/
│  ├─ locales/
│  └─ [existing reusable JS modules]
├─ scripts/
└─ test/
```

기존 JS를 반드시 `legacy/`로 이동할 필요는 없다.

Path churn 최소화.

---

# 63. Final Production Flow

```text
Browser
   │
   ▼
React AE Web
   │
   ├─ Design System
   ├─ UX State Mapper
   ├─ React Query
   └─ Existing Clients
           │
           ▼
       /ae-api
           │
           ▼
       NeX-AE API
           │
      ┌────┼─────┐
      ▼    ▼     ▼
     OA   WC    EOS ...
```

---

# 64. PWA Successor

S22 이후 별도 문서:

```text
NeX AE Web PWA Phase 1
Pre-Architecture / Slice Plan
```

검토.

Core modernization에 포함하지 않는다.

---

# 65. Final Definition of Done

모두 만족해야 한다.

```text
[ ] React + TypeScript + Vite canonical

[ ] Design Token v1 canonical

[ ] Core Design System active

[ ] Login modernized

[ ] App Shell / Router active

[ ] Approval Inbox modernized

[ ] Workspace modernized

[ ] UX State Mapper active

[ ] Approval user-facing projection source-backed

[ ] Business Result projection source-backed

[ ] Documents / Upload / Retrieval modernized

[ ] Artifact / Result Output modernized

[ ] Operations isolated

[ ] Browser direct 810x call absent

[ ] production implicit mock absent

[ ] same-origin /ae-api enforced

[ ] UX Acceptance v2 PASS

[ ] desktop 1440×900 PASS

[ ] mobile 390×844 PASS

[ ] accessibility PASS

[ ] privacy/redaction PASS

[ ] existing relevant Playwright PASS

[ ] legacy main.js retired

[ ] legacy styles.css retired

[ ] legacy renderer production imports absent

[ ] Vite dist production container PASS

[ ] Repository Full Gate PASS

[ ] Final As-Built frozen
```

---

# 66. Stop Conditions

다음 경우 즉시 중단한다.

```text
existing domain/client tests를 대량 삭제해야 React가 동작

browser가 owner service를 직접 호출

new UI가 raw business JSON을 임의 parsing

UI가 amount/risk/requester를 fabrication

production mock fallback 유지

cross-service DB read 필요

backend authorization 없이 UI hide만 수행

Playwright를 skip해서 cutover

PWA/Service Worker가 Core modernization scope로 유입

전체 JS→TS conversion이 migration을 지연
```

---

# 67. Final Recommendation

권고 implementation order는:

```text
S00  Entry Freeze

S01  Vite/React/TS
S02  Reuse Boundary

S03  Design Tokens
S04  Design System

S05  App Shell
S06  Auth
S07  Runtime/Same-Origin

S08  Approval Projection
S08A UX State Mapper Foundation
S09  Approval Read UX
S10  Approval Decision UX

S11  UX State/Terminology Completion
S12  Workspace
S13  Result Projection
S14  Workspace Result

S15  Document/Upload/Retrieval
S16  Artifact
S17  Operations

S18  UX Acceptance v2 Contract
S19  Playwright/Responsive/Accessibility

S20  Production Cutover
S21  Legacy Retirement

S22  Full Gate / Final As-Built
```

이 순서는:

```text
Foundation
→ Shared UX primitives
→ Business screen
→ Primary Workspace
→ Supporting workflows
→ Acceptance
→ Retirement
```

의 의존성을 따른다.

---

# 68. Codex Execution Principle

Codex에게 가장 중요한 원칙:

> **새 UI를 만들기 위해 기존 NeX business/security logic을 다시 만들지 않는다.**

그리고:

> **React는 NeX의 새로운 View Layer이지,
> 새로운 business authority가 아니다.**

마지막으로:

> **각 Slice는 기존 behavior를 보존하고,
> 새 UX를 추가하며,
> automated regression으로 증명한 후에만 다음 단계로 넘어간다.**

이 Implementation Slice Plan을 NeX AE Web UI/UX Modernization의
canonical implementation baseline으로 사용한다.
