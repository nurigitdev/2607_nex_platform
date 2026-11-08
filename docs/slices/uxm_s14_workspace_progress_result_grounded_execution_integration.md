# UXM-S14 Workspace Progress / Result / Grounded Execution Integration

## Outcome

PASS / CLOSED. The React v2 Workspace route now composes the installed AE
Workspace, grounded-generation, and owner-scoped AgentResult clients. Durable
runtime phases are presented as a compact progress strip, approval wait and
resume are visible, and admitted business results, artifacts, warnings, and
grounded citations are projected without exposing raw runtime payloads.

## Source Audit and Composition

The Slice reuses existing service contracts and does not add a database table,
migration, or backend endpoint:

```text
browser claims
  -> POST /api/v1/workspaces
  -> POST /api/v1/chat/interactions
  -> GET /api/v1/chat/interactions/{interaction_id}/agent-result
  -> strict browser projection
  -> Workspace progress and result presentation
```

`WorkspaceRuntimeRoute` is the installed composition root. The route creates
an owner-scoped Workspace idempotently, submits the existing grounded request,
polls the existing owner-scoped result facade, and supplies only the admitted
projection to `WorkspacePage`. The static presentation remains available only
as an explicit component fallback for isolated tests.

## Durable State Vocabulary

The UI does not estimate work or create decorative progress. It maps source
runtime phases through the shared UX state mapper:

```text
REQUEST_ADMITTED / PLANNING -> 요청 접수 / 업무 계획
RUNNING                     -> 처리 중
WAITING_APPROVAL            -> 승인 대기
RESUMING                    -> 처리 재개
VERIFYING                   -> 결과 확인
SUCCEEDED                   -> 완료
FAILED / BLOCKED            -> 실패
```

Only states observed for the current execution are retained in the progress
history. Terminal business result content uses the UXM-S13 typed summary;
artifacts are represented by admitted reference counts and grounded sources by
citation counts. Raw AgentResult, prompt/provider payload, tenant identity, and
internal operation identifiers are not rendered.

## Error and Security Boundary

The main error surface contains a human-readable reason, retry availability,
and next action. A technical code is secondary and collapsible. Only admitted
uppercase error codes can cross the projection; unknown exceptions collapse to
`WORKSPACE_EXECUTION_UNAVAILABLE`. Tenant and owner fields are derived from the
browser session claims and are never accepted from Workspace form input.

## Scope Boundary

The runtime supports a supplied set of document IDs and renders grounded
citations. The installed Workspace does not yet include document selection, so
it submits an empty document set. Upload, document selection, and retrieval UI
belong to UXM-S15. S14 therefore proves installed execution and result wiring,
not the S15 document journey.

## Verification

```text
focused Workspace React and adapter tests       = PASS, 39 tests / 6 files
installed runtime route integration             = PASS
browser unit regression                         = PASS, 410 tests
React component regression                       = PASS, 99 tests / 20 files
TypeScript typecheck                            = PASS
modern production import audit                  = PASS, 40 files
modern browser security audit                   = PASS, 41 files
protected desktop/mobile Playwright smoke       = PASS, 8 requests / 3 result reads / 9 checks
Checkpoint #3 repository regression             = PASS, 19,678 passed / 132 skipped
Checkpoint #3 coverage                          = PASS, statement 98.66% / branch 97.31%
contract / Golden Journey / dependency audits   = PASS
PostgreSQL / remote providers                   = NOT REQUIRED
```

The protected smoke covers login, owner-scoped Workspace creation, request
admission, planning, approval wait, resume, terminal verification, typed
Voucher projection, artifact presence, and mobile overflow. Visual evidence:

```text
reports/uiux/workspace-checkpoint/01-approval-wait-desktop.png
reports/uiux/workspace-checkpoint/02-result-desktop.png
reports/uiux/workspace-checkpoint/03-result-mobile.png
```

Checkpoint #3 completed the cumulative S11-S14 gate in 1,097.342 seconds.
Contract validation covered 232 schemas, 292 examples, 245 negative examples,
and 10 OpenAPI documents. The protected PostgreSQL and live-provider tests
listed as skipped require their explicit environment gates and are outside the
UI-only S14 boundary.

## Decision

```text
UXM-S14 = PASS / CLOSED
Checkpoint #3 = PASS
UXM-S15 = AUTHORIZED
```
