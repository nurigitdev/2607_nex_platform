# AE Artifact Rendering Handoff Contract

Status: Draft seed for Slice 430.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md)
- [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md)
- [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
- [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md)
- [Generation Progress Event Contract](21_generation_progress_event_contract.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)

This document freezes the first handoff contract for turning a CX-validated
structured draft into AE-owned user artifacts. The handoff keeps generated
document ownership in AE while preserving CX generation lineage, structured
draft hashes, citation validation metadata, and source anchors for audit and
reproducibility.

## Boundary Decision

| Area | Owner | Decision |
| --- | --- | --- |
| Structured draft validation | CX | CX validates draft schema, citations, source anchors, and completeness before handoff. |
| Artifact metadata | AE | AE owns artifact records, versions, titles, workspace links, previews, and downloads. |
| Render jobs | AE | AE converts a safe CX draft into Markdown, HTML preview, DOCX, PDF, or later formats. |
| Source lineage refs | CX/AE | CX owns evidence and citation anchors; AE stores safe references and hashes only. |
| Provider runtime metadata | MO/CX | MO returns usage through CX; AE stores safe run metadata but no provider secrets. |
| Governance visibility | AG | AG reads artifact lineage and rendering status through AE/CX service APIs. |

AE must not become a CX corpus repository. CX must not own user-facing artifact records or download links.
MO is not involved in artifact rendering.

## Handoff Direction

| Step | Caller | Receiver | Endpoint | Notes |
| --- | --- | --- | --- | --- |
| Fetch generation summary | `nex-ae-api` | `nex-cx` | `GET /api/v1/generations/{generation_id}` | AE verifies generation status, validation status, and safe lineage refs. |
| Fetch structured draft | `nex-ae-api` | `nex-cx` | `GET /api/v1/generations/{generation_id}/structured-draft` | AE receives safe sections, blocks, citations, and validation metadata. |
| Create artifact record | `nex-ae-api` | AE artifact module | `POST /api/v1/artifacts` | AE creates an artifact shell linked to chat/workspace lineage. |
| Render artifact version | AE render job | AE artifact module | `POST /api/v1/artifacts/{artifact_id}/render-jobs` | AE renders Markdown/HTML/DOCX/PDF using approved rendering policy. |
| Preview or download | `nex-ae-web` | `nex-ae-api` | `GET /api/v1/artifacts/{artifact_id}` and file endpoints | Web consumes AE-owned preview/download links. |

Endpoint names are service-local. CX exposes generation/structured draft reads.
AE exposes artifact and render job APIs.

## Handoff Package

AE stores a normalized handoff package before rendering.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `artifact_request_id` | Yes | AE | Idempotent AE request ID for artifact creation. |
| `handoff_schema_version` | Yes | Shared | Start with `ae_artifact_handoff.v1`. |
| `trace_id` / `request_id` | Yes | Shared | Propagated from the user generation flow. |
| `chat_document_id` | Yes | AE | Chat/workspace target that will display the artifact link. |
| `interaction_id` | Yes | AE | User-facing interaction that requested artifact creation. |
| `actor_claims_ref` | Yes | OA/AE | Safe actor reference; no raw token copy. |
| `cx_generation_id` | Yes | CX/AE | Source CX generation execution ID. |
| `structured_draft_id` | Yes | CX | Source structured draft ID. |
| `draft_schema_version` | Yes | CX | Such as `cx_structured_draft.v1`. |
| `structured_draft_content_hash` | Yes | CX | Prevents silent draft drift between validation and rendering. |
| `citation_claims_hash` | Yes when grounded | CX | Citation claim hash from Slice 429. |
| `validation_result_hash` | Yes | CX | Schema/citation/completeness validation hash. |
| `template_id` / `template_version` | No | AE | Template used for document outputs. |
| `rendering_template_id` | No | AE | AE rendering template or style guide reference. |
| `artifact_intent` | Yes | AE | `preview_only`, `create_artifact`, or `create_and_export`. |
| `target_formats` | Yes | AE | Ordered set such as `MD`, `HTML_PREVIEW`, `DOCX`, `PDF`. |
| `artifact_title` | No | AE | User-facing title. |
| `language` | Yes | AE | Korean default; English supported. |
| `retention_policy_ref` | Yes | AE/AG | Retention policy for generated artifact files and metadata. |
| `requested_at` | Yes | AE | RFC3339 UTC timestamp. |

The handoff package references CX records by ID/hash. It does not copy full
private source documents, provider prompts, provider URLs, or model paths.

## Artifact Record Family

| Record | Owner | Purpose |
| --- | --- | --- |
| `ae_artifacts` | AE | Root user-facing artifact record. |
| `ae_artifact_versions` | AE | Versioned logical content/render lineage. |
| `ae_artifact_render_jobs` | AE | Async render status, progress, and retry metadata. |
| `ae_artifact_files` | AE | Rendered file metadata and storage references. |
| `ae_artifact_links` | AE | Preview/download link metadata and expiry policy. |
| `ae_artifact_source_refs` | AE/CX | Safe refs to CX generation, draft, citation, and evidence lineage. |
| `ae_artifact_audit_events` | AE/AG | User/operator activity around render, download, clone, rollback, delete. |

The names are logical record names, not final physical table mandates.

## Artifact Root Fields

| Field | Required | Notes |
| --- | --- | --- |
| `artifact_id` | Yes | Stable AE artifact ID. |
| `artifact_schema_version` | Yes | Start with `ae_artifact.v1`. |
| `artifact_type` | Yes | `generated_document`, `summary`, `answer_export`, or future type. |
| `artifact_status` | Yes | `DRAFT`, `RENDERING`, `READY`, `FAILED`, `ARCHIVED`, or `DELETED`. |
| `current_version_id` | No | Present after the first version is created. |
| `chat_document_id` / `interaction_id` | Yes | User-facing workspace lineage. |
| `owner_actor_ref` | Yes | Safe OA actor reference. |
| `workspace_ref` | Yes | Workspace/group/document scope used for visibility. |
| `display_title` | Yes | AE-owned title for list/search/detail views. |
| `language` | Yes | Korean default; English supported. |
| `created_at` / `updated_at` | Yes | RFC3339 UTC timestamps. |

Artifact lifecycle is separate from CX generation lifecycle. Deleting or
archiving an AE artifact does not delete CX generation records or source corpus.

## Artifact Version Fields

| Field | Required | Notes |
| --- | --- | --- |
| `artifact_version_id` | Yes | Stable version ID. |
| `artifact_id` | Yes | Parent artifact. |
| `version_no` | Yes | Monotonic integer starting at 1. |
| `version_reason` | Yes | `initial_render`, `rerender`, `manual_edit`, `rollback`, or `repair_render`. |
| `source_generation_id` | Yes | CX generation execution ID. |
| `source_structured_draft_id` | Yes | CX structured draft ID. |
| `source_content_hash` | Yes | `structured_draft_content_hash` copied from CX. |
| `source_citation_claims_hash` | Yes when grounded | Citation claim hash copied from CX. |
| `render_policy_hash` | Yes | Hash over AE rendering policy, template, and target format options. |
| `artifact_content_hash` | Yes | Hash over normalized AE-renderable content. |
| `rendered_formats` | Yes | Formats successfully produced. |
| `validation_snapshot` | Yes | Safe copy of CX validation result summary. |
| `created_at` | Yes | RFC3339 UTC timestamp. |

Rollback changes `current_version_id`; it must not mutate the historical
version records.

## Render Job Fields

| Field | Required | Notes |
| --- | --- | --- |
| `render_job_id` | Yes | Stable AE render job ID. |
| `artifact_id` | Yes | Target artifact. |
| `artifact_version_id` | No | Present once the job creates or updates a version. |
| `job_status` | Yes | Common job status: `PENDING`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `TIMEOUT`, or `CANCELLED`. |
| `current_stage` | Yes | `HANDOFF_VALIDATING`, `MARKDOWN_RENDERING`, `HTML_PREVIEW_RENDERING`, `DOCX_RENDERING`, `PDF_RENDERING`, `LINK_CREATING`, or `FINALIZING`. |
| `progress_mode` | Yes | `DETERMINATE`, `INDETERMINATE`, or `STREAMING`. |
| `progress_percent` | No | Only when determinate. |
| `retryable` | Yes | Whether AE can retry without a new CX generation. |
| `failure_code` | No | Stable AE error code. |
| `started_at` / `completed_at` | No | RFC3339 UTC timestamps. |

Rendering can be asynchronous. The first MVP can render Markdown and HTML
preview synchronously, but the contract should not require synchronous DOCX/PDF
export.

## Rendered File Fields

| Field | Required | Notes |
| --- | --- | --- |
| `artifact_file_id` | Yes | Stable file metadata ID. |
| `artifact_version_id` | Yes | Parent version. |
| `format` | Yes | `MD`, `HTML_PREVIEW`, `DOCX`, `PDF`, or future allowlisted format. |
| `mime_type` | Yes | Such as `text/markdown` or DOCX/PDF MIME type. |
| `file_name` | Yes | Safe generated file name. |
| `storage_ref` | Yes | AE-owned storage reference; not a raw local path on public APIs. |
| `file_size_bytes` | No | Present when known. |
| `file_hash` | Yes | Hash over rendered bytes. |
| `source_version_hash` | Yes | Artifact version hash used to render this file. |
| `created_at` | Yes | RFC3339 UTC timestamp. |

Public APIs must expose download URLs or link tokens, not server filesystem
paths.

## Preview And Download Links

| Field | Required | Notes |
| --- | --- | --- |
| `artifact_link_id` | Yes | Stable link metadata ID. |
| `artifact_file_id` | Yes | Target rendered file. |
| `link_type` | Yes | `preview`, `download`, or `share`. |
| `access_policy` | Yes | `owner_only`, `workspace_scope`, or future policy. |
| `expires_at` | No | Required for temporary signed download links. |
| `created_by_actor_ref` | Yes | Safe actor or service reference. |
| `download_count` | No | Optional audit counter. |
| `revoked_at` | No | Present if manually revoked. |

Download link authorization must be rechecked through OA/AE policy when the link
is used. Link possession alone is not a permission proof unless an explicit
signed-link policy allows it.

## Source Reference Shape

AE stores enough lineage to explain where an artifact came from without taking
over CX source data.

| Field | Required | Notes |
| --- | --- | --- |
| `source_ref_id` | Yes | Stable AE source reference ID. |
| `cx_generation_id` | Yes | CX execution that produced the draft. |
| `structured_draft_id` | Yes | CX draft ID. |
| `structured_draft_content_hash` | Yes | Drift guard. |
| `citation_claims_hash` | Yes when grounded | Drift guard for citation claims. |
| `retrieval_package_id` | Yes when grounded | CX retrieval package ID. |
| `retrieval_package_hash` | Yes when grounded | CX retrieval package hash. |
| `evidence_ref_count` | Yes | Count of evidence refs used in the draft. |
| `source_anchor_count` | Yes | Count of available anchors. |
| `quality_summary` | Yes | No-answer, confidence, citation, and completeness summary. |

For detail drilldown, AE calls CX by `cx_generation_id` or `retrieval_package_id`
instead of duplicating full evidence payloads in the artifact store.

## API Shapes

Recommended AE APIs:

```text
POST /api/v1/artifacts
GET  /api/v1/artifacts/{artifact_id}
GET  /api/v1/artifacts/{artifact_id}/versions
POST /api/v1/artifacts/{artifact_id}/render-jobs
GET  /api/v1/artifact-render-jobs/{render_job_id}
POST /api/v1/artifacts/{artifact_id}/versions/{version_id}/rollback
GET  /api/v1/artifact-files/{artifact_file_id}/download
```

Recommended CX read APIs consumed by AE:

```text
GET /api/v1/generations/{generation_id}
GET /api/v1/generations/{generation_id}/structured-draft
```

Mutating AE artifact calls require `Idempotency-Key`, `X-Request-ID`, and
`traceparent`. List APIs should use cursor pagination.

## Guardrails

| Guardrail | Rule |
| --- | --- |
| No unvalidated draft artifact | AE should not create a `READY` artifact when CX draft or citation validation failed, unless an explicit warning/override policy is stored. |
| No hidden source drift | Handoff must store `structured_draft_content_hash`, `citation_claims_hash`, and `validation_result_hash`. |
| No provider secret leakage | Artifact records and files exclude provider endpoints, API keys, model paths, and raw prompts unless retention policy explicitly allows safe redacted prompt metadata. |
| No raw filesystem path leak | Public APIs expose AE download routes or signed links, never local paths. |
| No artifact-only lineage | Chat messages store `artifact_id`, `artifact_version_id`, `cx_generation_id`, and `trace_id`. |
| No cross-service writes | AE does not update CX generation records; CX does not create AE artifact records. |
| Permission recheck | Preview/download requests revalidate actor access against AE workspace policy and OA claims. |

## Error Codes

| Error Code | Trigger |
| --- | --- |
| `ae.artifact_handoff_invalid` | Required handoff fields or hashes are missing. |
| `ae.source_generation_not_ready` | CX generation is not terminal success or allowed warning state. |
| `ae.source_draft_hash_mismatch` | Structured draft hash no longer matches the stored handoff. |
| `ae.citation_validation_required` | Grounded artifact is requested but citation validation is invalid/missing. |
| `ae.render_format_unsupported` | Requested export format is outside the allowlist. |
| `ae.render_job_failed` | Rendering failed after retry budget. |
| `ae.artifact_file_not_ready` | Download requested before rendered file is ready. |
| `ae.artifact_access_denied` | Actor lacks permission for preview/download. |

All errors use the common `application/problem+json` envelope and preserve
`request_id`, `trace_id`, `artifact_id` when known, and safe actor metadata.

## Contract Tests To Derive

- AE artifact creation requires `cx_generation_id`, `structured_draft_id`,
  `structured_draft_content_hash`, `validation_result_hash`, workspace refs,
  and actor refs.
- Handoff with a mismatched structured draft hash returns
  `ae.source_draft_hash_mismatch`.
- Grounded artifact creation fails or warns when citation validation is invalid,
  according to explicit policy.
- Render jobs keep `job_status`, `current_stage`, and `progress_mode` separate.
- Rendered file public metadata includes format, MIME type, file hash, size
  when known, and no raw filesystem path.
- Chat lineage stores `artifact_id`, `artifact_version_id`,
  `cx_generation_id`, and `trace_id`.
- Rollback changes only the current version pointer and preserves old version
  records.
- Preview/download rechecks actor permissions and rejects unauthorized access.

## Next Inputs

This contract should feed:

- AE chat workspace artifact link and preview requirements, starting from
  [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md).
- Generation progress event contract, starting from
  [Generation Progress Event Contract](21_generation_progress_event_contract.md).
- Artifact render job JSON Schema and OpenAPI seed.
- Generation failure, repair, and retry policy contract.
- AG artifact audit and generated-document governance dashboard requirements,
  starting from
  [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md).
