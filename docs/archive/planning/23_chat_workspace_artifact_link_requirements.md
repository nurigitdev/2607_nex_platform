# Chat Workspace Artifact Link Requirements

Status: Draft seed for Slice 433.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Progress Event Contract](21_generation_progress_event_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)

This document freezes the first chat workspace requirements for showing
generated artifacts. AE should make generated documents feel like part of a
conversation while preserving artifact versions, downloads, source lineage,
progress, and recovery actions.

## UX Ownership

| Area | Owner | Requirement |
| --- | --- | --- |
| Chat message stream | AE web/API | Chat messages are the user's primary workspace timeline. |
| Artifact card/link | AE web/API | Generated artifacts appear as linked cards attached to assistant messages. |
| Artifact metadata | AE API | AE owns artifact ID, version, status, title, preview, and download links. |
| Source drilldown | AE -> CX | AE links to CX generation/source details instead of duplicating full evidence. |
| Progress display | AE web/API | Long-running generation and render jobs show Slice 431 progress events. |
| Recovery controls | AE web/API | Retry, repair, regenerate, render retry, and manual accept actions are visible when allowed. |

CX and MO do not write chat messages. AG observes chat/artifact metadata only
through service APIs and governed audit views.

## Chat Message Link Shape

Assistant messages that produce artifacts should include an artifact reference
array.

| Field | Required | Notes |
| --- | --- | --- |
| `message_id` | Yes | AE chat message ID. |
| `chat_document_id` | Yes | Workspace conversation/document ID. |
| `interaction_id` | Yes | User interaction lineage ID. |
| `artifact_refs` | Yes | Ordered array of artifact link objects. |
| `generation_refs` | Yes when generated | CX generation ID, trace ID, and status summary. |
| `source_context_refs` | No | Safe retrieval package/source context links. |
| `quality_badges` | No | Citation, completeness, confidence, and warning badges. |
| `created_at` / `updated_at` | Yes | RFC3339 UTC timestamps. |

The chat message stores references and summary metadata. The artifact store owns
files, versions, preview data, and download links.

## Artifact Link Object

| Field | Required | Notes |
| --- | --- | --- |
| `artifact_id` | Yes | AE artifact ID. |
| `artifact_version_id` | Yes | Current version shown in chat. |
| `display_title` | Yes | User-facing title. |
| `artifact_type` | Yes | `generated_document`, `summary`, `answer_export`, or future type. |
| `artifact_status` | Yes | `DRAFT`, `RENDERING`, `READY`, `FAILED`, `ARCHIVED`, or `DELETED`. |
| `primary_format` | Yes | Usually `MD`, `HTML_PREVIEW`, `DOCX`, or `PDF`. |
| `available_formats` | Yes | Rendered formats currently downloadable. |
| `preview_route` | No | AE route for preview, not a raw file path. |
| `download_routes` | No | Format-keyed AE download routes or signed-link references. |
| `source_generation_id` | Yes | CX generation ID. |
| `source_content_hash` | Yes | Structured draft hash used for the current version. |
| `quality_summary` | Yes | Citation/completeness/confidence warning summary. |
| `actions` | Yes | Allowed user actions based on status and policy. |

Links must remain usable even after later regenerate/edit branches create new
artifact versions.

## Artifact Card States

| State | UI Requirement |
| --- | --- |
| `RENDERING` | Show progress stage and disable unavailable downloads. |
| `READY` | Show preview and available download buttons. |
| `FAILED` | Show failure reason, retryable flag, and render retry action if allowed. |
| `ARCHIVED` | Keep lineage visible, hide normal download affordance unless policy allows. |
| `DELETED` | Show tombstone and audit-safe metadata only. |
| Warning accepted | Show warning badge and accepted risk summary. |

Do not hide validation warnings inside a successful-looking document card.

## Required Actions

| Action | When Available | Owner |
| --- | --- | --- |
| `preview` | Artifact has previewable file or HTML preview. | AE |
| `download_md` | Markdown file is ready. | AE |
| `download_docx` | DOCX file is ready. | AE |
| `download_pdf` | PDF file is ready. | AE |
| `view_sources` | Source refs are available. | AE -> CX |
| `view_lineage` | Generation or artifact lineage exists. | AE/CX |
| `retry_generation` | Recovery policy allows generation retry. | AE -> CX |
| `repair_generation` | Recovery policy allows repair. | AE -> CX |
| `retry_render` | Render failed or target format missing. | AE |
| `clone_artifact` | User wants a new editable branch. | AE |
| `rollback_version` | Prior artifact version exists and policy allows rollback. | AE |

Action availability should be returned by AE API, not inferred only in the
browser.

## Source And Citation Display

| Requirement | Rule |
| --- | --- |
| Citation labels | Show labels from CX citation claims where available. |
| Source drilldown | Open AE-controlled panel that reads CX source context by safe reference. |
| No evidence duplication | Do not store full source documents in chat messages. |
| Warning badges | Show no-answer, low-confidence, invalid citation, partial completeness, and manual warning acceptance. |
| Permission recheck | Source drilldown and downloads revalidate actor claims. |

User-visible citations should remain stable for the artifact version. If a
regeneration changes citations, the new artifact version gets its own citation
summary.

## API Requirements

Recommended AE read APIs:

```text
GET /api/v1/chat-documents/{chat_document_id}/messages
GET /api/v1/chat-messages/{message_id}/artifact-links
GET /api/v1/artifacts/{artifact_id}
GET /api/v1/artifacts/{artifact_id}/versions
GET /api/v1/artifacts/{artifact_id}/lineage
GET /api/v1/artifact-files/{artifact_file_id}/download
```

Recommended AE action APIs:

```text
POST /api/v1/artifacts/{artifact_id}/render-jobs
POST /api/v1/artifacts/{artifact_id}/clone
POST /api/v1/artifacts/{artifact_id}/versions/{version_id}/rollback
POST /api/v1/generations/{generation_id}/retry
POST /api/v1/generations/{generation_id}/repair
```

Mutating calls require `Idempotency-Key`, `X-Request-ID`, and `traceparent`.

## Accessibility And Localization

| Requirement | Rule |
| --- | --- |
| Korean default | Primary labels and messages are Korean by default. |
| English support | Message keys must be localizable to English. |
| Keyboard access | Preview, download, source, and retry controls are keyboard reachable. |
| Status text | Icon-only status indicators need text alternatives. |
| Long running work | Progress cards should remain visible and announce state changes where supported. |

UI text should come from message keys and status values, not hard-coded service
internals.

## Contract Tests To Derive

- Assistant messages that create artifacts include `artifact_refs`,
  `generation_refs`, and quality summary metadata.
- Artifact links contain artifact ID, version ID, status, available formats,
  source generation ID, source content hash, and allowed actions.
- `FAILED` render state exposes retry action only when policy says retryable.
- Download routes never expose raw filesystem paths.
- Source drilldown uses safe CX refs and rechecks permission.
- Regenerated artifacts create new version/link lineage instead of mutating old
  chat messages in place.

## Next Inputs

This requirements document should feed:

- Prompt/template/output compatibility rule matrix, starting from
  [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md).
- AG generation and artifact audit dashboard requirements, starting from
  [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md).
- Generation OpenAPI endpoint seed.
- Generation E2E acceptance scenario and contract test plan.
