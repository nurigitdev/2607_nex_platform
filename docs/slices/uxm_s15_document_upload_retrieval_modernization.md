# UXM-S15 Document / Upload / Retrieval Modernization

## Outcome

PASS / CLOSED. The React v2 document route now provides one owner-scoped
business flow for document listing, file attachment, ingestion progress,
document detail, document selection, and retrieval-quality feedback.

## Source-Backed Composition

The Slice reuses the existing upload, upload-progress, document-detail,
document-scope, retrieval, and retrieval-quality modules. The only missing
browser boundary was a typed projection for:

```text
GET /api/v1/workspaces/{workspace_id}/documents
```

`DocumentLibraryClientPort` now admits that response and removes tenant,
owner, source hash, CX storage, provider, and internal link fields before the
React surface receives an item. No backend endpoint, database migration, or
cross-service browser call was added.

## User Flow

```text
내 문서
  -> 처리/요약 상태
  -> 문서 상세

파일 첨부
  -> multipart AE facade upload
  -> bounded progress polling
  -> duplicate guidance
  -> retrieval-ready result

문서 근거 찾기
  -> explicit document selection
  -> hybrid retrieval request
  -> evidence count / confidence / no-answer guidance
```

The compatibility routes `/upload` and `/retrieval` remain and open the same
canonical document work surface at the appropriate tab. `/documents` is the
primary navigation route.

## Security

All network calls remain below `/ae-api`. The browser does not render local
storage paths, source hashes, provider URLs, raw source, vectors, tenant IDs,
or owner IDs. The AE facade remains authoritative for owner-claim validation;
a wrong-owner response becomes bounded user guidance without reflecting the
server detail.

## Verification

```text
focused React/adapter tests                = PASS, 9 tests / 3 files
browser unit regression                    = PASS, 411 tests
React component regression                 = PASS, 108 tests / 23 files
TypeScript typecheck                       = PASS
modern production import audit             = PASS, 44 files
modern browser security audit              = PASS, 45 files
design token consistency                   = PASS, 146 variables / 15 components
React v2 production build                  = PASS
protected document Playwright smoke        = PASS, 12 requests / 3 screenshots / 9 checks
PostgreSQL / remote providers              = NOT REQUIRED
```

Visual evidence:

```text
reports/uiux/document-modernization/01-document-desktop.png
reports/uiux/document-modernization/02-retrieval-desktop.png
reports/uiux/document-modernization/03-retrieval-mobile.png
```

The existing Vite bundle-size advisory remains non-blocking and is unchanged
as an accepted modernization-stage risk.

## Decision

```text
UXM-S15 = PASS / CLOSED
Document flow parity = PASS
UXM-S16 = AUTHORIZED
```
