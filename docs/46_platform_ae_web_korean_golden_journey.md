# Platform AE Web Korean-Default Playwright Golden Journey

Status: S139 active through Slice 1385.

## Required Outcome

S139 proves one owner-authenticated AE Web journey in the Korean-default UI:
login, document upload, ingestion progress, permission-filtered retrieval,
grounded generation, quality warnings, citations, artifact preview, and
download. The same acceptance must pass in desktop and mobile viewports with
stable, non-overlapping controls and metadata-only evidence.

## Boundary

- The browser calls AE through the same-origin `/ae-api` facade. It does not
  call OA, CX, MO, or AG directly and never reads a service database.
- OA remains the identity owner. AE derives owner and tenant scope from the
  authenticated session and does not accept browser-supplied ownership.
- CX owns ingestion, retrieval, generation, citation, and repair semantics.
  MO remains behind CX capability aliases. AG exposes redacted trace status
  through service APIs only.
- Browser evidence may contain stable opaque identifiers, bounded states,
  Korean labels, viewport dimensions, screenshot references, and safe routes.
  It must not contain passwords, tokens, prompts, document text, generated
  text, source bytes, storage references, provider endpoints, or database
  locations.
- S139 requires an actual Chromium process and actual service processes for
  protected closure. Test PostgreSQL is permitted. Remote model providers are
  not required; the protected journey may use the deterministic MO mock
  capability because live provider behavior was accepted in S136 and S137.

## Current State

The repository has focused Playwright harnesses for credential login,
authenticated upload, grounded generation, artifact preview/download,
artifact library, and artifact lifecycle. These harnesses are useful component
evidence but do not yet prove a single correlated golden journey.

The document language is Korean, but visible labels and generated status text
still mix Korean and English. Existing browser harnesses generally execute one
desktop viewport and do not freeze mobile layout, screenshot evidence,
full-journey correlation, or browser-visible privacy assertions as one
acceptance contract.

## Slice Plan

| Slice | Scope |
| --- | --- |
| `1382` | Freeze the S139 browser boundary, eight gaps, and S140 handoff. |
| `1383` | Define Korean-default, English-ready UI message and status contracts. |
| `1384` | Define the correlated golden-journey state and browser-safe evidence model. |
| `1385` | Integrate login, upload, and ingestion-progress browser acceptance. |
| `1386` | Integrate retrieval, generation, warning, citation, and repair acceptance; run Checkpoint Gate. |
| `1387` | Integrate artifact render, preview, and download acceptance. |
| `1388` | Harden desktop/mobile responsive, accessibility, and non-overlap acceptance. |
| `1389` | Execute deterministic two-viewport Playwright golden-journey acceptance. |
| `1390` | Execute protected browser plus service-process and test-PostgreSQL acceptance. |
| `1391` | Publish the runbook, close S139, run Full Gate, and activate S140. |

## Frozen Gaps

1. Korean-default visible-message contract is not centralized.
2. A single correlated browser-journey state model is missing.
3. Login, upload, and ingestion progress are verified by separate harnesses.
4. Retrieval, grounded generation, warnings, citations, and repair are not one
   browser acceptance sequence.
5. Artifact preview and download are not bound to the same golden journey.
6. Desktop and mobile non-overlap and accessibility acceptance are not frozen.
7. Deterministic Playwright evidence does not cover the complete journey.
8. Protected actual-browser, service-process, and test-PostgreSQL evidence is
   missing.

## Progress

- Slice 1382 froze the same-origin browser boundary, the eight acceptance
  gaps, and the S140 release-candidate handoff.
- Slice 1383 introduced one `ko`/`en` catalog with exact key parity, Korean
  fallback behavior, stable dynamic status keys, and declarative static text
  and accessible-label bindings. The default remains Korean; an English
  catalog is readiness evidence rather than a second business workflow.
- Slice 1384 introduced one immutable nine-stage `journey_id` state and a
  browser-safe evidence projection. Ordered transitions, opaque ref/detail
  allowlists, monotonic timestamps, terminal guards, and private-field
  rejection are now frozen for subsequent Playwright integration.
- Slice 1385 connected authenticated OA session claims, AE upload submission,
  and owner-scoped ingestion progress to the first three journey stages. AE
  Web now owns a same-origin progress adapter and requires `INDEX_READY` plus
  retrieval usability without accepting browser-supplied ownership.

## Acceptance Rules

- Default document language and primary user-facing workflow labels are Korean.
- English readiness is preserved through stable message keys rather than
  duplicated business behavior.
- Desktop and mobile use the same semantic journey and acceptance checks.
- Screenshots are evidence of visible state only and cannot become a source of
  private payload retention.
- Every failed browser or service boundary is explicit, retry-aware where
  allowed, and fail-closed for identity, ownership, citation, or artifact
  access.

## S140 Handoff

S140 receives a repeatable browser journey, its redacted correlation evidence,
desktop/mobile screenshots, and the protected service-process command. S140
owns release-candidate execution across all test databases, live provider
capabilities, browser acceptance, restart, privacy, and deployment deferrals.
