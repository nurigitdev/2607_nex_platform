# NeX AE Web UI/UX Modernization
# Source Audit & Pre-Architecture Decision v1.0

**Status:** FROZEN FOR IMPLEMENTATION PLANNING / PRE-ARCHITECTURE DECISION  
**Mandatory Implementation Amendment:** `UXM_CA01_Source_Backed_Entry_Baseline_and_Design_Asset_Admission_Closure_v1.0.md`
**Program:** NeX Platform v2.1  
**Product:** NeX-AE Web / Assistant Workspace  
**Purpose:** 현재 `master` source와 UI/UX 개선 분석안을 기준으로 NeX-AE Web의 현대화 범위, 자산 보존/재사용/폐기/신규 원칙, target architecture를 고정  
**Repository:** `nurigitdev/2607_nex_platform`  
**Canonical Branch:** `master`  
**Observed Master HEAD:** `4dcecb6c4a682ef1e94ff3a701d5fffe4faa19d7`  
**Observed HEAD Message:** `Merge v2.1 transition baseline into master`  
**Source Audit Date:** 2026-11-08  

---

# 1. Executive Summary

NeX-AE Web은 지금까지 Platform 기능과 보안/계약/접근성의 검증 surface로
성장해 왔다.

이 과정에서 backend/runtime의 기능은 크게 확장되었지만,
사용자 UI는 다음과 같은 한계를 갖게 되었다.

```text
4,015-line main.js
1,967-line styles.css
framework 없는 static JS
대규모 querySelector / innerHTML orchestration
hash 기반 화면 전환
내부 runtime/status/route 정보 노출
일반 사용자가 이해하기 어려운 업무 흐름
디자인 시스템 부족
아이콘 체계 없음
```

반면 현재 source에는 이미 상당한 가치의 재사용 자산이 존재한다.

```text
Client
ReadModel
ActionState
Boundary
Workflow
Session/Auth
Runtime Config
Privacy/Redaction
Golden Journey Test
Playwright Acceptance
```

따라서 이번 UI/UX Modernization은:

```text
Rewrite Everything
```

이 아니라:

```text
Preserve Business / Security / Contract Logic
+
Replace View / Composition Layer
+
Introduce Modern Design System
+
Build User-Facing Business UX
```

로 정의한다.

본 PAD의 핵심 결정은 다음과 같다.

```text
PAD-UX-01
React 19 + TypeScript + Vite 기반으로 View Layer를 현대화한다.

PAD-UX-02
현재 Client / State / ReadModel / Boundary 모듈은 최대한 재사용한다.

PAD-UX-03
main.js 중심 DOM orchestration은 최종적으로 폐기한다.

PAD-UX-04
현재 styles.css monolith는 NeX Design Token + Component Style로 대체한다.

PAD-UX-05
Browser는 same-origin /ae-api만 호출한다.

PAD-UX-06
Browser에서 OA/WC/EOS/WA/CX/MO service를 직접 호출하지 않는다.

PAD-UX-07
운영/진단 정보는 일반 업무 UI에서 숨기고 role-gated Operations surface로 격리한다.

PAD-UX-08
Internal Platform state를 그대로 표시하지 않고 User-Facing UX State로 projection한다.

PAD-UX-09
승인함과 결과 화면에 필요한 업무정보가 현재 projection에 없으면
AE facade의 user-facing projection을 보강하며 browser-side join을 금지한다.

PAD-UX-10
현재 Golden Journey test의 business/security invariants는 유지하되,
새 IA/UX에 맞는 v2 viewport/selector contract를 별도로 freeze한다.

PAD-UX-11
Mock runtime은 test/demo 전용으로 제한하고 production UI는 explicit fetch mode를 요구한다.

PAD-UX-12
PWA는 Core UI Modernization 이후의 별도 단계로 둔다.
```

---

# 2. Inputs

본 Review는 다음 자료를 기준으로 한다.

## 2.1 Collaborator UI/UX Analysis

사용자가 제공한 압축자료:

```text
NeX_AE_Web_UI_UX_개선_분석.zip
```

구성:

```text
NeX_AE_Web_UI_UX_개선_분석.md
NeX_AE_Web_UI_UX_개선안.pdf
report.html
tokens.css
tokens.json
```

분석 자료의 주요 제안:

```text
React + TypeScript + Vite
Design Token
Lucide icon
Login redesign
Workspace redesign
Approval Inbox redesign
Result Card redesign
PWA
```

---

## 2.2 Current Repository

현재 source of truth:

```text
branch = master
HEAD   = 4dcecb6c4a682ef1e94ff3a701d5fffe4faa19d7
```

`master`는 직전 NeX v2.1 transition baseline merge가 완료된 상태이다.

---

## 2.3 External Framework Verification

2026-11-08 기준 공식 문서 확인:

```text
React
- React 19 active major
- latest official documentation is React 19.x

Vite
- current supported active releases include Vite 8.x

TanStack Query
- React Query v5 is current documented major

Radix Primitives
- accessible unstyled React primitives

Lucide React
- tree-shakable typed SVG icon components
```

정확한 patch/minor version은 PAD에서 고정하지 않는다.

Implementation Slice에서:

```text
package-lock.json
```

으로 exact dependency version을 pin한다.

---

# 3. Current Source Quantitative Audit

현재 `master` 기준:

| Item | Current |
|---|---:|
| `src/main.js` | **4,015 lines** |
| `src/styles.css` | **1,967 lines** |
| top-level `src` entries | **67** |
| JS modules including `locales/messages.js` | 약 **66** |
| Node/JS tests | **94** |
| Web scripts / Playwright runners | **26** |
| runtime dependencies | **0** |
| dev dependencies | Playwright only |
| distinct current `--nex-*` variables | **16** |
| distinct hard-coded HEX colors in CSS | **54** |
| `main.js` querySelector hits | 약 **84** |
| `main.js` innerHTML hits | 약 **29** |
| direct local service health URL composition | **present** |

분석 자료의 2026-10-27 Demo branch 상태:

```text
main.js   = 4,014 lines
styles.css= 1,966 lines
```

현재 master는 사실상 그 규모가 그대로 product baseline에 들어온 상태이다.

---

# 4. Important Source Finding — Logic Is Already Modularized

`main.js`는 매우 크지만,
대부분의 다른 모듈은 DOM API를 직접 사용하지 않는다.

Source sampling 결과:

```text
approvalUi.js
  DOM dependent

voucherAttachmentUi.js
  DOM dependent

main.js
  strongly DOM dependent

most Client / State / ReadModel modules
  DOM independent
```

대표적으로 다음은 DOM API를 직접 사용하지 않는다.

```text
approvalClient.js
artifactClient.js
artifactCardReadModel.js
artifactLifecycleActionState.js
authBoundary.js
authenticatedRuntime.js
clientRegistry.js
documentDetailClient.js
documentScope.js
generationLifecycleState.js
groundedGenerationClient.js
operationState.js
repairedResponseReviewReadModel.js
retrievalClient.js
runtimeConfig.js
sessionClient.js
sessionRouteGuard.js
uploadClient.js
voucherAttachmentClient.js
```

따라서 React migration의 핵심은:

```text
DOM-independent logic reuse
+
DOM render layer replacement
```

이다.

---

# 5. Current Architecture

현재 구조는 개념적으로:

```text
index.html
   │
   ▼
main.js
   │
   ├─ querySelector
   ├─ innerHTML
   ├─ event handler
   ├─ screen switching
   ├─ UI state composition
   ├─ service health call
   └─ all page rendering
        │
        ├─ Client modules
        ├─ State modules
        ├─ ReadModel modules
        ├─ Surface modules
        └─ Renderer modules
```

문제는 Client/Domain 계층 자체가 아니라:

```text
main.js
```

에 Composition / View responsibility가 과도하게 집중된 것이다.

---

# 6. Current Runtime Configuration Finding

현재 `runtimeConfig.js` 기본값:

```text
client_mode = mock
fetch_clients_enabled = false
```

현재 `index.html` inline config도:

```json
{
  "client_mode": "mock",
  "features": {
    "fetch_clients_enabled": false
  }
}
```

을 기본으로 한다.

이 구조는 deterministic demo/test에는 유용하지만
실제 사용자용 product UI의 기본값으로는 적합하지 않다.

Target policy:

```text
Test / Local Demo
→ mock allowed

Installed / Production
→ explicit fetch required
→ ae_base_url = same-origin /ae-api
```

Production은 runtime config가 누락되었을 때
silent mock fallback을 해서는 안 된다.

---

# 7. Critical Boundary Finding — Browser Direct Service Call

현재 `main.js`에는:

```text
http://127.0.0.1:${port}
```

형태의 service health 직접 호출이 남아 있다.

대상:

```text
OA
AG
AE
CX
MO
```

이는 collaborator 분석에서 이미 지적되었고,
현재 master에서도 여전히 존재한다.

NeX의 browser boundary 원칙과 충돌한다.

Target:

```text
Browser
    ↓
same-origin /ae-api
    ↓
AE facade
    ↓
owner services
```

금지:

```text
Browser → OA
Browser → WC
Browser → EOS
Browser → WA
Browser → CX
Browser → MO
Browser → localhost service ports
```

---

# 8. Source Disposition Vocabulary

본 PAD에서는 source를 네 가지로 분류한다.

## KEEP / 유지

```text
현재 책임과 contract가 적절하며
새 UI에서도 canonical source로 유지
```

## REUSE / 재사용

```text
핵심 logic은 유지하지만
React/TS architecture에 맞게 wrapper, split, adapter 또는 TS migration 필요
```

## RETIRE / 폐기

```text
새 architecture parity 이후
production path에서 제거
```

즉시 삭제를 의미하지 않는다.

## NEW / 신규

```text
현재 source에는 없으며
새 UX architecture에 필요
```

---

# 9. KEEP — Canonical Logic / Contract Assets

다음 source는 원칙적으로 유지한다.

### Approval / Artifact / Document / Retrieval

```text
approvalClient.js
artifactCardReadModel.js
artifactClient.js
artifactDeliveryActionState.js
artifactDownloadSaveAdapter.js
artifactLifecycleActionState.js
documentBootstrap.js
documentDetailClient.js
documentScope.js
retrievalClient.js
retrievalQualityWarnings.js
```

### Authentication / Session

```text
authBoundary.js
authenticatedRuntime.js
authenticatedUploadWorkflow.js
sessionBootstrap.js
sessionClient.js
sessionIdentityPresentation.js
sessionRouteGuard.js
```

### Generation / Agent Result

```text
generationFeedback.js
generationLifecycleState.js
groundedGenerationClient.js
groundedGenerationRecovery.js
groundedGenerationWorkflow.js
groundedResponseQuality.js
```

### Repaired Response

```text
repairedResponseDecisionClient.js
repairedResponseDecisionState.js
repairedResponseReviewBoundary.js
repairedResponseReviewClient.js
repairedResponseReviewReadModel.js
```

### Runtime / Operation

```text
clientRegistry.js
operationState.js
runtimeConfig.js
runtimeDiagnostics.js
runtimeIdentifiers.js
```

### Upload / Attachment

```text
uploadClient.js
uploadProgressClient.js
voucherAttachmentClient.js
workspaceBootstrap.js
```

이 모듈들은 초기 React migration 시
JavaScript 상태로 그대로 import해도 된다.

TypeScript 전환은 UI migration의 선행조건이 아니다.

---

# 10. KEEP WITH POLICY HARDENING

다음은 source는 유지하지만 policy를 보강한다.

## `runtimeConfig.js`

유지:

```text
safe config validation
unsupported field rejection
browser secret exclusion
AE base URL validation
```

변경:

```text
production silent mock fallback 금지
```

## `clientRegistry.js`

유지:

```text
mock/fetch adapter separation
client composition
```

변경:

```text
production profile에서 fetch 강제
```

## `runtimeDiagnostics.js`

유지:

```text
diagnostic read model
safe/redacted metadata
```

변경:

```text
normal business screen에서 숨김
Operations/Debug surface에서만 사용
```

---

# 11. REUSE — Logic Preserved, View Layer Split

다음 source는 유용하지만
React component와 domain logic을 분리해야 한다.

| Source | Reuse | Replace |
|---|---|---|
| `applicationShell.js` | auth/role/allowed-view rule | hash navigation |
| `credentialLoginSurface.js` | validation/request building | visible tenant/status UX |
| `fetchWorkspacePresentation.js` | safe presentation mapping | old HTML placement |
| `groundedGenerationPresentation.js` | presentation model | old screen composition |
| `operationFeedback.js` | severity/retry mapping | old markup/copy placement |
| `uploadSurface.js` | safe upload model | current metadata-heavy UI |
| `locales/messages.js` | catalog, locale normalization, `message()`, `statusMessage()` | DOM mutation adapter |
| `interactionAgentResultClient.js` | route/client/projection | `renderInteractionAgentResult()` |
| `artifactDownloadFormatSelector.js` | selector/read model | HTML renderer |
| `artifactExportResultReadModel.js` | read model / safety | HTML renderer |
| `artifactLibraryPanel.js` | state/filter/summary | HTML renderer |
| `artifactPreviewPanel.js` | state/read model | HTML renderer |
| `artifactVersionPanel.js` | state/read model | HTML renderer |
| `projectMembershipBatchResult.js` | result surface model | HTML renderer |
| `repairedResponseReviewCard.js` | view model / safety | HTML renderer |

원칙:

```text
build*
create*
normalize*
assert*
findSensitive*
```

계열은 우선 재사용하고,

```text
render*
container.innerHTML
querySelector
```

계열은 React component로 대체한다.

---

# 12. RETIRE — Old View / Composition Layer

새 React UI가 parity를 확보한 뒤 다음은 production path에서 폐기한다.

```text
src/main.js
src/styles.css
index.html의 전체 static application markup
approvalUi.js의 DOM controller/render layer
artifactCard.js HTML renderer
voucherAttachmentUi.js DOM controller/render layer
```

주의:

```text
즉시 삭제 금지
```

Migration 동안 old UI는 비교/reference surface로 유지할 수 있다.

Retirement 조건:

```text
new React screen parity
Node tests preserved
Playwright v2 PASS
same-origin audit PASS
no protected data regression
```

---

# 13. RETIRE — Specific Behaviors

다음 behavior는 반드시 제거한다.

```text
Browser → 127.0.0.1:810x health call

Workspace UUID default exposure

route/status/provider/target/operation default exposure

normal user UI에서 Runtime diagnostics 표시

normal user UI에서 raw internal enum 표시

hash anchor를 primary router로 사용하는 구조

static full-page innerHTML orchestration

production silent mock mode
```

---

# 14. KEEP — Test and Acceptance Assets

현재 AE Web은 이미 매우 큰 검증 자산을 갖는다.

```text
94 Node/JS tests
26 scripts / Playwright runners
```

다음 test asset은 폐기 대상이 아니다.

```text
credentialLoginHarness.js
deterministicGoldenJourney.js
fetchModeHarness.js
goldenJourneyArtifact.js
goldenJourneyGrounding.js
goldenJourneyIngestion.js
goldenJourneyState.js
artifactMockRecord.js
```

역할:

```text
deterministic regression
business contract verification
privacy/redaction
mock acceptance
```

---

# 15. Golden Journey Viewport Contract — Controlled Evolution

현재:

```text
ae_web_golden_journey_viewport.v1
```

은 다음 region을 요구한다.

```text
sidebar
workspace
topbar
summary
content
workspace_column
chat
timeline
```

Collaborator UX proposal은:

```text
workspace-summary band 제거
context panel 강화
```

를 제안한다.

따라서 v1 selector를 억지로 유지하면
새 UX architecture를 왜곡하게 된다.

Decision:

```text
v1
→ historical acceptance evidence

v2
→ new UI contract
```

---

# 16. Golden Journey Viewport v2 Requirements

v2에서도 다음 invariant는 유지한다.

```text
Desktop 1440 × 900
Mobile  390 × 844

html lang = ko

single visible main landmark

single primary h1

no horizontal overflow

accessible control names

minimum target size >= 24px

visible keyboard focus

primary region non-overlap
```

변경 가능한 것은:

```text
exact DOM selector
old summary band
old chat/timeline physical arrangement
```

---

# 17. Proposed v2 Regions

예:

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

Mobile에서는:

```text
context_panel
→ Drawer
```

로 동작할 수 있다.

정확한 selector는 SRS/Implementation Plan에서 freeze한다.

---

# 18. User-Facing Information Architecture

Target IA:

```text
NeX AE
│
├─ Workspace
│   ├─ Conversation
│   ├─ Work Progress
│   ├─ Attachments
│   ├─ Sources
│   └─ Result
│
├─ Approvals
│   ├─ Pending
│   ├─ Completed
│   └─ Rejected
│
├─ Documents
│
├─ Artifacts
│
└─ Operations
    └─ Admin / Operator only
```

Upload/Retrieval은 반드시 sidebar 1급 메뉴로 유지할 필요가 없다.

장기적으로:

```text
Upload
Retrieval
```

은 Workspace / Document workflow 안의 action으로 통합할 수 있다.

단, migration 초기에는 기존 기능 parity를 위해 route를 유지할 수 있다.

---

# 19. Route Decision

Target route concept:

```text
/login
/workspace
/approvals
/documents
/artifacts
/operations
```

초기 compatibility route:

```text
/upload
/retrieval
```

사용 가능.

Router:

```text
React Router
```

권고.

현재 `applicationShell.js`의:

```text
allowedApplicationViews()
canAccessOperations()
```

는 route guard policy에 재사용한다.

현재:

```text
viewFromLocationHash()
```

는 최종 폐기한다.

---

# 20. Framework Decision

Target:

```text
React 19
TypeScript
Vite
```

정확한 minor/patch는 Implementation 시 lock한다.

2026-11 기준 공식 React 문서는 React 19.x를 current major로 제공하며,
Vite는 8.x가 actively supported release line이다.

---

# 21. State / Server Data Decision

권고:

```text
React local state
+
existing domain state models
+
TanStack Query
```

초기에는:

```text
Redux
Zustand
```

같은 별도 global store를 도입하지 않는다.

먼저 기존 state module과 server query를 분리한다.

---

# 22. Existing Client Modules + TanStack Query

현재 Client 모듈은 이미:

```text
route construction
fetch
response validation
safe normalization
mock adapter
error classification
```

을 담당한다.

TanStack Query는 이를 대체하지 않는다.

구조:

```text
React Component
     ↓
TanStack Query
     ↓
existing AE Web Client
     ↓
/ae-api
```

이렇게 한다.

---

# 23. Design System Decision

Collaborator가 제공한:

```text
tokens.json
tokens.css
```

를 **NeX Design Token v1 seed**로 채택한다.

단:

```text
repository import
automated token validation
WCAG regression
```

을 통과한 이후 canonical로 freeze한다.

---

# 24. Styling Decision

권고:

```text
CSS Variables
+
CSS Modules
```

초기 Core Modernization에서는 Tailwind를 필수 도입하지 않는다.

이유:

```text
existing NeX semantic token을 source of truth로 유지

utility value가 token vocabulary를 우회하는 것을 방지

Codex가 arbitrary spacing/color를 추가하는 것을 억제

component ownership을 명확히 함
```

향후 필요하면 별도 검토한다.

---

# 25. Design Token Rules

금지:

```text
arbitrary hex in component
arbitrary pixel spacing
status-specific one-off color
```

허용:

```text
semantic token
component token
layout token
```

예:

```text
--nex-accent
--nex-success-bg
--nex-warning-fg
--nex-space-4
--nex-radius-md
```

---

# 26. Component Foundation

Core components:

```text
Button
IconButton
Input
Select
Textarea/Composer
Checkbox
Radio
Badge
StatusPill
Card
Tabs
Table/List
NavItem
Drawer
Modal
ConfirmDialog
Toast
Stepper
EmptyState
Avatar
Tooltip
```

Collaborator의 15종을 기본으로 하되
IconButton / Tooltip 등 실제 accessibility 필요 요소를 포함할 수 있다.

---

# 27. Accessible Primitive Decision

복잡한 interaction에는:

```text
Radix Primitives
```

를 기반으로 검토한다.

주 대상:

```text
Dialog
Dropdown
Popover
Tabs
Tooltip
Select
```

NeX styling은 Design Token으로 직접 적용한다.

---

# 28. Icon Decision

Target:

```text
Lucide React
```

원칙:

```text
currentColor
16px inline
18~20px navigation/button
24~32px empty state
icon-only button → aria-label mandatory
decorative icon → aria-hidden
```

색만으로 상태를 전달하지 않는다.

---

# 29. i18n Decision

현재:

```text
locales/messages.js
```

는 ko/en parity와 message lookup을 이미 제공한다.

따라서 이를 재사용한다.

초기에는 별도 i18n framework를 필수로 추가하지 않는다.

구조:

```text
Existing Message Catalog
       ↓
React I18n Provider / Hook
       ↓
Component
```

`applyDocumentMessages()`와 DOM attribute scan은 폐기한다.

---

# 30. User-Facing UX State Vocabulary

Internal state를 화면에 그대로 노출하지 않는다.

Target UX vocabulary:

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

사용자 라벨 예:

```text
입력 대기
요청 확인 중
업무 계획 중
처리 중
승인 대기
승인 반영 중
결과 확인 중
완료
일부 완료
처리 실패
취소됨
```

---

# 31. UX State Mapper

신규:

```text
UxWorkStateMapper
```

역할:

```text
Internal AgentExecution
RuntimeJob
Approval
ResultDelivery
Generation
Artifact
```

state를 user-facing state로 projection한다.

화면마다 임의로:

```text
statusLabel()
```

을 호출해 raw enum을 노출하는 구조를 줄인다.

---

# 32. UX State Invariant

> **Platform Complexity는 숨기되 Business Accountability는 숨기지 않는다.**

숨김:

```text
RuntimeJob ID
provider
route
target
operation ID
internal enum
```

기본 표시:

```text
요청 업무
Project
요청자
현재 단계
승인 필요 여부
업무 결과
증빙/근거
```

---

# 33. Login Decision

현재 문제:

```text
tenant-local 노출
READY_FOR_LOGIN badge
Employee access eyebrow
system summary
```

Target:

```text
NeX AE brand
사번
비밀번호
password visibility
Caps Lock indication
login error
remember ID [optional]
```

Tenant:

```text
기본 숨김
```

Tenant resolution 방식은 후속 contract에서 확정한다.

가능:

```text
deployment config
domain mapping
session context
```

다른 tenant 선택이 필요한 환경에서만
secondary control로 노출한다.

---

# 34. Workspace Decision

Workspace가 primary UX이다.

Target:

```text
Conversation
+
Composer
+
Context Panel
```

Empty state:

```text
인사말
추천 업무
최근 작업 [API available when supported]
```

Composer:

```text
auto-growing textarea
attachment
send
optional evidence/format chips
```

---

# 35. Context Panel Decision

Desktop:

```text
fixed right panel
```

Tabs:

```text
진행
첨부
출처
```

Mobile:

```text
Drawer
```

기존 `golden-context-pane` 구조는 개념적으로 재사용 가능하지만
내용과 layout은 전면 재구성한다.

---

# 36. Progress Display Decision

금지:

```text
fake percentage
```

사용:

```text
step-based progress
```

예:

```text
요청 접수
→ 내용 검증
→ 처리
→ 승인 대기
→ 결과 확인
→ 완료
```

실제 runtime state에 존재하지 않는 stage를 만들어내지 않는다.

---

# 37. Approval Inbox Decision

승인함은 Core Modernization의 첫 번째 full business screen으로 권고한다.

이유:

```text
List
Badge
Tabs
Table
Card
Risk
Attachment
Modal
Dialog
Drawer
Action
```

등 Design System을 폭넓게 검증할 수 있다.

---

# 38. Current Approval Projection — Available

현재 `approvalClient.js`가 제공하는 주요 user-safe 정보:

```text
approval domain
state
title
summary
expires_at
provider type
target ref
business operation id
formal approval progress
formal project_id
attachment manifest
attachment count
attachment display name
```

---

# 39. Current Approval Projection — Missing for Target UX

Collaborator target approval UI에는 다음이 필요하다.

```text
requester identity / display name
request time
business amount / currency
business date
account code/name
Project display name
risk level
risk explanation
business-specific line items
```

현재 frontend approval projection에서는
이 정보가 일반적으로 보장되지 않는다.

따라서 UI에서 추측하거나 raw JSON을 parsing하면 안 된다.

---

# 40. Approval Projection Decision

필요한 경우 AE facade에:

```text
User-Facing Approval Projection
```

을 보강한다.

원칙:

```text
Browser
  ↓
AE API
  ↓
WC / EOS / OA server-side authority
```

금지:

```text
Browser → WC
Browser → EOS
Browser → OA
Browser-side business join
```

---

# 41. Approval Projection Principle

승인자가 판단할 수 없는 화면을 만들지 않는다.

최소:

```text
What
Who
Project
Amount / Business Impact [when applicable]
Evidence
Risk
Requested At
```

가 source-backed로 존재해야 한다.

정보가 없으면:

```text
"확인할 수 없음"
```

으로 표시할 수는 있으나
fabrication은 금지한다.

---

# 42. Approval Technical Detail

기존:

```text
provider
target
operation
UUID
```

등은 제거하지 않는다.

기본 UI에서 숨기고:

```text
기술 상세
```

접힘 영역 또는 Operations/Debug mode에서 제공한다.

---

# 43. Approval Decision UX

Target:

```text
Approve
Reject
```

Reject:

```text
reason required
```

Action:

```text
ConfirmDialog
```

Decision 이후:

```text
buttons removed
decision result displayed
next pending item action
```

---

# 44. Result Card Current Projection

현재 `interactionAgentResultClient.js`는 다음을 제공한다.

```text
execution state
result status
business refs
external refs
artifact refs
warnings
delivery state
workspace activity ref
```

안전한 lineage 확인에는 유용하다.

---

# 45. Result Card Projection Gap

사용자 결과 카드에 필요한:

```text
전표번호
금액
계정
Project
결재 상태
결재자
업무 object link
```

는 현재 generic AgentResult projection에 포함되지 않는다.

따라서:

```text
business result summary projection
```

이 별도로 필요할 수 있다.

---

# 46. Result Projection Decision

Generic AgentResult를 business-specific JSON parsing으로 확장하지 않는다.

권고:

```text
AgentResult
+
typed Business Result Summary
```

구조를 AE facade에서 제공한다.

예:

```text
result_type = VOUCHER_DRAFT

summary:
  voucher_no
  amount
  account
  project
  approval_state
```

정확한 schema는 후속 contract closure에서 결정한다.

---

# 47. Document / Upload / Retrieval

현재 Client/State logic은 상당히 잘 분리되어 있으므로
대부분 재사용한다.

UX에서는:

```text
Upload
Retrieval
```

을 기술 기능으로 보여주기보다:

```text
파일 첨부
문서 선택
근거 사용
출처 확인
```

으로 업무 language화한다.

---

# 48. Artifact UX

현재 artifact 기능은:

```text
library
preview
versions
download
lifecycle
export
```

까지 상당히 성숙했다.

따라서 기능은 유지한다.

UI는:

```text
Artifact technical entity
```

보다:

```text
업무 결과물
문서
파일
생성 결과
```

중심으로 표현한다.

`아티팩트`라는 용어는 전문 사용자/상세 화면에서는 유지 가능하다.

---

# 49. Operations / Diagnostics

현재 `applicationShell.js`는:

```text
admin
operator
```

role에만 Operations를 허용한다.

이 정책은 유지한다.

Operations에는:

```text
Runtime diagnostics
Service readiness
Technical IDs
Route
Provider
Execution details
```

을 모은다.

일반 직원 UI에는 노출하지 않는다.

---

# 50. Direct Service Health Replacement

현재 Browser local port health check는 폐기한다.

대안:

```text
Option A
AE API Operations Projection

Option B
AG Operations Projection exposed through AE facade
```

어느 owner가 적절한지는 후속 Source Audit에서 확정한다.

Browser direct call은 허용하지 않는다.

---

# 51. Debug Mode

Target:

```text
normal mode
debug mode
operations mode
```

구분.

Normal:

```text
business information only
```

Debug:

```text
safe technical detail
```

Operations:

```text
role-gated platform operations
```

Query string `?debug=1`만으로 privileged 정보가 열려서는 안 된다.

Debug mode도:

```text
server-authorized runtime feature
```

와 결합해야 한다.

---

# 52. Same-Origin Security Invariant

Browser network:

```text
/ae-api/*
static asset
```

만 허용한다.

Playwright에서 다음을 감사한다.

```text
non-same-origin business API request = FAIL

localhost:810x request = FAIL

service token in browser = FAIL
```

---

# 53. Runtime Config Security

Runtime config에 금지:

```text
service token
provider secret
database URL
storage credential
OpenBao credential
raw business payload
```

현재 `runtimeConfig.js`의 supported-field fail-closed model을 유지한다.

---

# 54. Mock Policy

Mock adapter는 중요한 test asset이다.

따라서 삭제하지 않는다.

하지만:

```text
Production Runtime
```

에서 implicit mock은 금지한다.

Target:

```text
NODE_ENV / build profile만으로 결정하지 않음

explicit runtime config
+
installed deployment contract
```

으로 fetch mode를 확정한다.

---

# 55. Build / Deployment Decision

현재 container:

```text
Node 22
index.html
src/*
serve.mjs
```

를 그대로 실행한다.

Target:

```text
Build Stage
  npm ci
  vite build
       ↓
  dist/

Runtime Stage
  Node minimal static/proxy server
  dist/
  serve.mjs
```

으로 변경한다.

---

# 56. `serve.mjs` Disposition

`serve.mjs`는 **REUSE**한다.

유지:

```text
same-origin /ae-api proxy
Node stdlib
no browser credential injection
```

변경:

```text
serve dist/
SPA route fallback
asset MIME support
cache header policy
```

Vite dev server는 개발용이다.

Production runtime server를 Vite dev server로 사용하지 않는다.

---

# 57. Containerfile Decision

현재:

```text
deployment/oci/ae-web.Containerfile
```

은 static source를 copy하고 `npm start`를 실행한다.

Target:

```text
multi-stage build
```

로 변경한다.

원칙:

```text
exact package-lock
non-root runtime
no dev server in production
no source secret
same OCI provenance policy
```

---

# 58. React Dependency Policy

최소 dependency를 권고한다.

Core:

```text
react
react-dom
typescript
vite
```

App:

```text
react-router
@tanstack/react-query
```

UI:

```text
selected @radix-ui primitives
lucide-react
```

Test:

```text
Playwright
Vitest
React Testing Library
```

정확한 package selection은 Implementation Plan에서 freeze한다.

---

# 59. Avoid Dependency Explosion

초기에는 도입하지 않는다.

```text
Redux
large enterprise UI suite
multiple CSS systems
multiple icon sets
multiple state managers
```

NeX Design System ownership을 유지한다.

---

# 60. React Component Structure

권고 구조:

```text
src/
├─ app/
│  ├─ App.tsx
│  ├─ router.tsx
│  └─ providers.tsx
│
├─ design-system/
│  ├─ tokens/
│  ├─ components/
│  └─ styles/
│
├─ features/
│  ├─ auth/
│  ├─ workspace/
│  ├─ approvals/
│  ├─ documents/
│  ├─ artifacts/
│  └─ operations/
│
├─ domain/
│  └─ existing reusable logic
│
├─ api/
│  └─ existing client adapters
│
├─ i18n/
└─ ux/
   ├─ workState.ts
   └─ terminology.ts
```

정확한 physical move는 필요할 때만 한다.

대규모 file move 자체를 목표로 하지 않는다.

---

# 61. Migration Rule

가능하면 기존 JS module을:

```text
React TS → JS module import
```

형태로 먼저 사용한다.

기능 migration과 TypeScript conversion을 동시에 하지 않는다.

순서:

```text
Behavior Preserve
→ View Migration
→ Regression
→ Optional TS Conversion
```

---

# 62. Test Strategy

기존:

```text
node --test
Playwright
```

를 유지한다.

신규 React component:

```text
Vitest
React Testing Library
```

권고.

---

# 63. Test Asset Preservation

기존 94 test를 일괄 삭제/변환하지 않는다.

분류:

```text
Domain/Client tests
→ KEEP

Renderer tests
→ React component test로 대체 후 retire

Playwright business journey
→ KEEP / selector migration

Historical P8 demo tests
→ compatibility evidence
```

---

# 64. UI Contract Migration Rule

Old selector를 무조건 유지하지 않는다.

다음은 유지:

```text
business outcome
privacy
accessibility
responsive
security
```

다음은 변경 가능:

```text
specific DOM shape
legacy region IDs
summary band selector
hash navigation
```

---

# 65. New UX Acceptance Contract

필요:

```text
AE Web UX Acceptance v2
```

최소 범위:

```text
Login
Approval
Workspace
Result
Documents
Artifacts
Operations isolation
Desktop/mobile
Keyboard
Screen reader naming
No overflow
No overlap
No internal debug leakage
Same-origin API only
```

---

# 66. Accessibility

기준:

```text
WCAG 2.2 AA
```

Collaborator token 검증의 52개 contrast 조합을
automated design-token regression으로 옮긴다.

추가:

```text
focus-visible
keyboard navigation
Dialog focus trap
Drawer focus restore
aria live
status icon + text
no color-only state
```

---

# 67. Responsive

기준 viewport는 기존 acceptance를 유지한다.

```text
1440×900
390×844
```

Design tokens:

```text
sidebar
context panel
chat column
breakpoints
```

을 활용한다.

---

# 68. Mobile Principle

Desktop을 단순 축소하지 않는다.

Mobile:

```text
sidebar → drawer / bottom navigation candidate
context panel → drawer
approval list/detail → sequential navigation
composer → sticky bottom
```

정확한 navigation pattern은 UI SRS에서 확정한다.

---

# 69. PWA Disposition

PWA는 유용하지만 Core modernization의 entry condition은 아니다.

따라서:

```text
Core UI Modernization
→ First

PWA Phase 1
→ Later

Web Push
→ Separate Approval / External Transmission Review
```

---

# 70. PWA Phase 1 Candidate

후속:

```text
manifest
static shell precache
offline notice
update prompt
```

허용.

금지:

```text
/ae-api caching
business response caching
artifact caching
offline approval
offline WRITE
```

---

# 71. Web Push

별도 phase.

알림:

```text
NeX AE · 승인 대기 1건
```

정도만 허용.

알림 payload에 금지:

```text
금액
요청자
문서명
민감 업무정보
```

외부 push provider 사용은 별도 보안/외부전송 승인 필요.

---

# 72. Source Disposition — Test-Only / Mock Assets

다음은 Product UI로 승격하지 않지만 유지한다.

```text
artifactMockRecord.js
credentialLoginHarness.js
deterministicGoldenJourney.js
fetchModeHarness.js
goldenJourneyArtifact.js
goldenJourneyGrounding.js
goldenJourneyIngestion.js
goldenJourneyState.js
goldenJourneyViewport.js [v1 historical]
```

Target React production module이 이 test-only fixture에 의존해서는 안 된다.

---

# 73. Source Disposition — Legacy Renderer Detail

## `approvalUi.js`

현재:

```text
container.innerHTML
querySelector
event delegation
HTML string
```

Target:

```text
Approval React Feature
```

상태/오류 mapping이 필요하면 별도 pure model로 추출.

---

## `voucherAttachmentUi.js`

현재 DOM controller와 renderer를 포함한다.

Target:

```text
VoucherAttachment React Component
```

Client:

```text
voucherAttachmentClient.js
```

는 유지한다.

---

## `artifactCard.js`

HTML renderer 자체는 폐기한다.

기존:

```text
artifactCardReadModel.js
```

을 React card에서 사용한다.

Renderer safety test는
React component redaction test로 이관한다.

---

# 74. UX Business Terminology

정확한 용어 dictionary를 신규 관리한다.

예:

```text
assistant
→ NeX 어시스턴트

HUMAN GATE
→ 승인

SUCCEEDED
→ 완료

READY_FOR_PROMPT
→ 입력 대기

admit
→ 요청 확인 / 요청 접수

Artifact
→ 결과물 [default]
```

전문가/운영 화면에서는 원래 용어를 볼 수 있다.

---

# 75. User-Facing Title Generation

기존:

```text
NeX-Platform
계약 기반 생성 흐름
```

같은 title을 primary title로 사용하지 않는다.

Workspace title:

```text
Project + 업무
```

예:

```text
PROJECT-A 출장비 정산
```

실제 title data가 없으면 generic title을 사용한다.

LLM이 title을 임의로 생성하는 것은 별도 정책이 필요하다.

---

# 76. Design Principle

본 UI modernization의 최상위 UX 원칙:

> **Platform Complexity는 숨기되 Business Accountability는 숨기지 않는다.**

두 번째 원칙:

> **사용자는 NeX 내부 state machine을 배우지 않아도 업무를 처리할 수 있어야 한다.**

세 번째 원칙:

> **기술 상세는 제거하지 않고 필요할 때만 reveal한다.**

---

# 77. Keep / Reuse / Retire / New Summary

## KEEP

```text
Client
Boundary
State
ReadModel
Workflow
Privacy/Redaction
Session/Auth
Mock/Test
Golden Journey business invariants
```

## REUSE

```text
Presentation model
Surface model
Shell authorization logic
i18n catalog
safe summary
mixed model+renderer modules after split
serve.mjs
```

## RETIRE

```text
main.js orchestration
styles.css monolith
static full app index.html
innerHTML renderer
DOM controller
hash primary navigation
browser direct service calls
normal-screen debug metadata
production implicit mock
```

## NEW

```text
React App
TypeScript
Vite
Router
TanStack Query orchestration
NeX Design System
Design Token v1
Radix primitives
Lucide
UX State Mapper
Business Terminology
Context Panel
Approval Workbench
Business Result Card
UX Acceptance v2
Product-safe runtime config profile
```

---

# 78. NEW — Target Approval Component Tree

Concept:

```text
ApprovalPage
├─ ApprovalTabs
├─ ApprovalFilterBar
├─ ApprovalList
│  └─ ApprovalListItem
└─ ApprovalDetail
   ├─ BusinessSummary
   ├─ VoucherLines [typed]
   ├─ EvidenceList
   ├─ RiskSummary
   ├─ TechnicalDetails
   └─ ApprovalActionBar
```

---

# 79. NEW — Target Workspace Component Tree

```text
WorkspacePage
├─ WorkspaceHeader
├─ Conversation
│  ├─ UserMessage
│  ├─ AgentMessage
│  ├─ WorkStepper
│  └─ ResultCard
├─ Composer
│  ├─ AttachmentChips
│  ├─ EvidenceOption
│  └─ SendAction
└─ ContextPanel
   ├─ ProgressTab
   ├─ AttachmentTab
   └─ SourcesTab
```

---

# 80. NEW — Design System Ownership

Design System은:

```text
NeX-AE specific CSS
```

보다:

```text
NeX Enterprise UX Design System
```

으로 발전 가능한 naming을 사용한다.

단, 이번 implementation scope는 AE Web이다.

MyBee 등 다른 서비스로 자동 확대하지 않는다.

---

# 81. Backend Projection Entry Gate

Approval / Result 화면의 full UX 구현 전:

```text
Projection Source Audit
```

필수.

질문:

```text
요청자 정보는 어디에 있는가?
금액은 어디에 있는가?
Account는 어디에 있는가?
Project display name은 어디에 있는가?
Risk는 어디서 계산되는가?
Result business summary는 어디에 있는가?
```

SoR를 먼저 확인한다.

---

# 82. Projection Invariant

UI를 위해:

```text
cross-service DB read
```

를 추가하지 않는다.

AE facade가 필요한 owner API를 사용한다.

---

# 83. Privacy Invariant

Default UI에 금지:

```text
service token
DB URL
provider URL
storage path
raw prompt in diagnostic evidence
raw hidden source
full UUID when not business-relevant
```

필요한 correlation ID는 기술 상세에서 제한적으로 노출한다.

---

# 84. Existing Redaction Logic

현재 source는 많은 모듈에서:

```text
assert*Safe
findSensitive*
rawProtectedPayloadRendered: false
providerUrlIncluded: false
```

같은 security regression logic을 가진다.

이 자산을 반드시 재사용한다.

React migration 때문에 안전성 test를 약화하지 않는다.

---

# 85. Migration Strategy

권고:

```text
Phase A
Foundation alongside current UI

Phase B
Screen-by-screen replacement

Phase C
Golden Journey v2 parity

Phase D
Legacy renderer retirement
```

Big-bang cutover를 하지 않는다.

---

# 86. Suggested Future Implementation Order

본 PAD 이후 별도 Implementation Slice Plan에서 구체화한다.

권고 순서:

```text
M01 Source/PAD Closure
M02 Vite/React/TS Build Foundation
M03 Design Token + Core Components
M04 App Shell / Auth / Router
M05 Approval Inbox
M06 Workspace / UX State
M07 Documents / Upload / Retrieval
M08 Result / Artifact
M09 Operations / Diagnostics Isolation
M10 UX Acceptance v2 / Responsive / Accessibility
M11 Legacy UI Retirement
M12 PWA Phase 1 [optional successor]
```

---

# 87. Why Approval Before Workspace

승인함은:

```text
Card
List
Table
Badge
Tabs
Filter
Modal
Drawer
Attachment
Risk
Primary/Danger Action
```

을 거의 모두 사용한다.

따라서 Design System의 첫 real business validation screen으로 적합하다.

---

# 88. Current Tests Must Drive Migration

각 screen migration 시:

```text
Existing Node regression
+
New component tests
+
Existing relevant Playwright
+
New UX v2 Playwright
```

를 함께 실행한다.

기존 test를 disable하여 migration을 통과시키지 않는다.

---

# 89. Selector Compatibility

Migration 초기에는 가능한 selector를 유지할 수 있다.

그러나:

```text
old DOM structure preservation
```

을 architecture requirement로 만들지는 않는다.

Test는 가능한 한:

```text
role
accessible name
stable test id
```

기반으로 이동한다.

---

# 90. Design Token Acceptance

Collaborator token baseline이 canonical이 되기 위한 Gate:

```text
JSON schema/shape validation
CSS generation parity
no arbitrary token drift
WCAG contrast regression
light/dark screenshot
focus ring
reduced motion
```

---

# 91. Dark Mode

Design Token은 light/dark를 모두 정의한다.

Dark mode는 지원 대상으로 두되,
Core business journey보다 우선하지 않는다.

설정:

```text
system preference
+
explicit user override
```

---

# 92. Font

Collaborator 제안:

```text
Pretendard Variable
```

은 적절한 후보이다.

다만 font asset distribution/licensing/deployment은
Implementation 단계에서 별도 확인한다.

Font file이 없더라도:

```text
system Korean font fallback
```

으로 동작해야 한다.

---

# 93. No UI Fabrication

중요 invariant:

> UI가 보기 좋아지기 위해 존재하지 않는 업무정보를 만들어서는 안 된다.

예:

```text
risk
amount
requester
project
approval stage
```

가 authoritative projection에 없으면
UI가 mock/default 값을 만들어 production에서 표시하지 않는다.

---

# 94. No Fake Progress

동일하게:

```text
50%
70%
90%
```

같은 fake progress 금지.

실제 durable stage만 보여준다.

---

# 95. Performance

React 도입 자체를 performance improvement로 주장하지 않는다.

Performance target:

```text
avoid full document re-render
preserve input focus
preserve scroll
bounded polling
query cache
code-split routes if needed
```

실측은 Implementation 단계에서 수행한다.

---

# 96. Bundle / Security

Vite build:

```text
source map policy
asset hash
CSP compatibility
dependency audit
SBOM
```

은 deployment closure에서 검증한다.

Client bundle에 secret이 들어가지 않아야 한다.

---

# 97. PWA Security

향후 service worker가 도입되더라도:

```text
/ae-api = network only
```

를 기본 invariant로 유지한다.

이 규칙은 Playwright에서 검사한다.

---

# 98. Open Decisions

후속 설계에서 결정:

```text
OPEN-01
Approval user-facing projection schema

OPEN-02
Business result summary schema

OPEN-03
Tenant auto-resolution UX / contract

OPEN-04
Upload/Retrieval을 top-level navigation에 계속 둘지 여부

OPEN-05
Mobile navigation: drawer vs bottom navigation

OPEN-06
Storybook 도입 여부

OPEN-07
PWA Phase 1 시작 시점

OPEN-08
Web Push activation 여부
```

---

# 99. Not Open — Frozen Decisions

다음은 본 PAD에서 결정한다.

```text
React + TypeScript + Vite

existing domain/client logic reuse

Design Token adoption

Lucide

same-origin /ae-api only

no browser cross-service call

no production implicit mock

debug/operations isolation

Golden Journey business/security invariants preserved

new UX acceptance v2

PWA deferred
```

---

# 100. Stop Conditions

다음 상황이면 구현을 중단하고 architecture review한다.

```text
React migration 때문에 backend contract를 무시

Browser가 WC/EOS/OA를 직접 호출

existing privacy/redaction test 삭제

Golden Journey를 test fixture로 우회

production mock fallback 유지

UI를 위해 cross-service DB join 추가

internal runtime state를 business state로 오해

대규모 TypeScript rewrite와 UI rewrite를 한 Slice에 동시 수행

PWA가 /ae-api response를 cache

Web Push에 민감정보 포함
```

---

# 101. Acceptance of This PAD

본 PAD가 승인되면 다음 문서는:

```text
NeX AE Web UI/UX Modernization
Implementation Slice Plan
```

으로 진행한다.

단, Implementation Slice Plan 전에 다음 두 bounded audit을
문서 내부 또는 S01에서 닫는 것을 권고한다.

```text
1. Approval / Result User-Facing Projection Gap Audit
2. Design Token Import / Validation Audit
```

---

# 102. Recommended Final Architecture

```text
                    Browser
                       │
                       ▼
              NeX AE React Application
      ┌────────────────────────────────┐
      │ Router                         │
      │ Design System                  │
      │ UX State Mapper                │
      │ TanStack Query                 │
      │ Feature Components             │
      └───────────────┬────────────────┘
                      │
               Existing Clients
                      │
                      ▼
              same-origin /ae-api
                      │
                      ▼
                  NeX-AE API
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
      OA             WC             EOS
       │              │              │
       └────── server-side only ─────┘
```

Browser는 owner service topology를 알 필요가 없다.

---

# 103. Source Disposition Final Summary

```text
Existing Product Logic
→ KEEP

Existing Safe Presentation / Surface Logic
→ REUSE

Existing Renderer / DOM Composition
→ RETIRE after parity

Modern App / Design / UX Projection
→ NEW
```

이 원칙을 구현 전체에서 유지한다.

---

# 104. Final Position

이번 Modernization의 목표는:

```text
"더 예쁜 화면"
```

이 아니다.

목표는:

```text
Platform validation UI
        ↓
Enterprise work UX
```

로의 전환이다.

최종 사용자는 다음 질문에 즉시 답을 얻을 수 있어야 한다.

```text
나는 지금 어떤 업무를 하고 있는가?

NeX가 내 요청을 어떻게 처리하고 있는가?

누가 또는 어떤 Agent가 작업하고 있는가?

내가 승인할 것이 있는가?

무엇이 변경되는가?

결과는 무엇인가?

결과의 근거는 무엇인가?

생성된 업무 결과물은 어디 있는가?
```

NeX 내부 구현의 복잡성은 숨겨야 한다.

하지만:

```text
책임
승인
근거
결과
```

는 숨기지 않는다.

본 PAD는 이 방향을 NeX-AE Web UI/UX Modernization의
pre-implementation architecture baseline으로 고정한다.

---

# Appendix A — Source Disposition Ledger

## A.1 KEEP — Canonical Product Logic

```text
approvalClient.js
artifactCardReadModel.js
artifactClient.js
artifactDeliveryActionState.js
artifactDownloadSaveAdapter.js
artifactLifecycleActionState.js
authBoundary.js
authenticatedRuntime.js
authenticatedUploadWorkflow.js
clientRegistry.js
documentBootstrap.js
documentDetailClient.js
documentScope.js
generationFeedback.js
generationLifecycleState.js
groundedGenerationClient.js
groundedGenerationRecovery.js
groundedGenerationWorkflow.js
groundedResponseQuality.js
operationState.js
repairedResponseDecisionClient.js
repairedResponseDecisionState.js
repairedResponseReviewBoundary.js
repairedResponseReviewClient.js
repairedResponseReviewReadModel.js
retrievalClient.js
retrievalQualityWarnings.js
runtimeConfig.js
runtimeDiagnostics.js
runtimeIdentifiers.js
sessionBootstrap.js
sessionClient.js
sessionIdentityPresentation.js
sessionRouteGuard.js
uploadClient.js
uploadProgressClient.js
voucherAttachmentClient.js
workspaceBootstrap.js
```

---

## A.2 REUSE / SPLIT

```text
applicationShell.js
credentialLoginSurface.js
fetchWorkspacePresentation.js
groundedGenerationPresentation.js
operationFeedback.js
uploadSurface.js
locales/messages.js

interactionAgentResultClient.js
artifactDownloadFormatSelector.js
artifactExportResultReadModel.js
artifactLibraryPanel.js
artifactPreviewPanel.js
artifactVersionPanel.js
projectMembershipBatchResult.js
repairedResponseReviewCard.js
```

---

## A.3 RETIRE AFTER PARITY

```text
src/main.js
src/styles.css
approvalUi.js
artifactCard.js
voucherAttachmentUi.js
root index.html full static application markup
```

Sub-function retirement:

```text
locales/messages.js::applyDocumentMessages
applicationShell.js::viewFromLocationHash
interactionAgentResultClient.js::renderInteractionAgentResult
artifactDownloadFormatSelector.js::renderArtifactDownloadFormatSelector
artifactExportResultReadModel.js::renderArtifactExportResultReadModel
artifactLibraryPanel.js::renderArtifactLibraryPanel
artifactPreviewPanel.js::renderArtifactPreviewPanel
artifactVersionPanel.js::renderArtifactVersionPanel
projectMembershipBatchResult.js::renderProjectMembershipBatchResult
repairedResponseReviewCard.js::renderRepairedResponseReviewCard
```

---

## A.4 KEEP — TEST / MOCK / ACCEPTANCE ONLY

```text
artifactMockRecord.js
credentialLoginHarness.js
deterministicGoldenJourney.js
fetchModeHarness.js
goldenJourneyArtifact.js
goldenJourneyGrounding.js
goldenJourneyIngestion.js
goldenJourneyState.js
goldenJourneyViewport.js [v1 historical / v2 successor required]
```

Production React feature는 이 test-only module에 의존하지 않는다.

---

## A.5 REUSE — Runtime Web Server

```text
scripts/serve.mjs
```

Rework:

```text
serve dist
SPA fallback
preserve /ae-api proxy
```

---

## A.6 KEEP / MIGRATE — Test Scripts

현재 `scripts/`의 26개 runner는 원칙적으로 유지한다.

특히:

```text
runAuthenticationFirstShellPlaywrightSmoke.mjs
runApprovalProtectedPlaywrightSmoke.mjs
runBusinessFormalApprovalPlaywrightSmoke.mjs
runAuthenticatedUploadPlaywrightSmoke.mjs
runArtifactPlaywrightSmoke.mjs
runKoreanGoldenJourneyPlaywrightAcceptance.mjs
runCanonicalPlatformGoldenJourney.mjs
```

은 new UI parity에서 중요한 acceptance evidence이다.

필요한 것은 삭제가 아니라 selector/route migration이다.

---

# Appendix B — Current Source Facts to Protect

```text
main.js = 4,015 lines

styles.css = 1,967 lines

styles.css distinct hard-coded HEX = 54

runtime dependency = none

Playwright = existing

same-origin proxy = /ae-api

runtime config validation = fail-closed on unsupported fields

client registry = mock / fetch split

Operations role gate = admin/operator

Golden Journey viewports =
  1440×900
  390×844

minimum control target =
  24px

redaction =
  existing extensive regression
```

---

# Appendix C — Framework References

Official sources checked during this Review:

```text
React
https://react.dev/versions

Vite
https://vite.dev/releases

TanStack Query
https://tanstack.com/query/latest/docs/framework/react

Radix Primitives
https://www.radix-ui.com/primitives

Lucide React
https://lucide.dev/guide/react/
```

Exact package versions are intentionally deferred to the implementation lock.

---

# Appendix D — Collaborator Design Baseline

Provided design assets:

```text
tokens.json
tokens.css
report.html
NeX_AE_Web_UI_UX_개선안.pdf
```

These are treated as:

```text
Design Baseline
```

not automatically executable product code.

Before import:

```text
token validation
contrast validation
naming consistency
repository ownership
license/font review
```

must pass.
