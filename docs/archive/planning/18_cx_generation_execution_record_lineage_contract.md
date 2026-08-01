# CX Generation Execution Record + Lineage Contract

Status: Draft seed for Slice 428.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md)
- [CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md)
- [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Progress Event Contract](21_generation_progress_event_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)

This document freezes the first CX-owned generation execution record and lineage
contract. The purpose is to preserve evidence continuity from retrieval through
provider execution and structured draft validation without moving user-facing
chat state or artifact ownership away from AE.

CX owns this record because it is the service that can connect retrieval package
identity, permission-filtered evidence, provider-facing prompt package, MO
runtime metadata, structured draft validation, citation validation, and
no-answer/low-confidence policy. AE stores references to the CX generation
record in chat and artifact metadata. MO stores provider runtime history, but it
does not own document semantics.

## Record Family

| Record | Owner | Purpose |
| --- | --- | --- |
| `cx_generation_executions` | CX | Root execution record for one AE-to-CX generation request. |
| `cx_generation_request_snapshots` | CX | Normalized AE-to-CX request summary and request hash. |
| `cx_generation_prompt_packages` | CX | Provider-facing prompt package metadata and hash. |
| `cx_generation_evidence_refs` | CX | Evidence IDs, source anchors, permission snapshot, and citation labels used. |
| `cx_generation_mo_calls` | CX/MO | MO request/response IDs, route metadata, usage, latency, and finish metadata. |
| `cx_structured_drafts` | CX | Structured draft reference, content hash, schema, and validation status. |
| `cx_generation_validation_results` | CX | Citation, schema, section completeness, and safety validation results. |

The names are logical record names, not a final physical schema mandate. Service
implementation may split or merge physical tables as long as the contract fields
and ownership remain intact.

## Root Execution Record

| Field | Required | Notes |
| --- | --- | --- |
| `cx_generation_id` | Yes | Stable CX generation execution ID. |
| `request_schema_version` | Yes | AE-to-CX request schema version accepted by CX. |
| `generation_status` | Yes | `ACCEPTED`, `RUNNING`, `SUCCEEDED`, `REJECTED`, `FAILED`, `CANCELLED`, or `TIMEOUT`. |
| `current_stage` | Yes | `EVIDENCE_VALIDATING`, `PROMPT_ASSEMBLING`, `MO_ADMISSION_WAITING`, `GENERATING`, `DRAFT_VALIDATING`, `CITATION_VALIDATING`, or `FINALIZING`. |
| `progress_mode` | Yes | Common `progress_mode`: `DETERMINATE`, `INDETERMINATE`, or `STREAMING`. |
| `trace_id` | Yes | Cross-service trace propagated from AE through CX to MO. |
| `request_id` | Yes | CX request ID for operator support. |
| `ae_request_id` | Yes | AE request ID from the accepted Generation Request Package. |
| `chat_document_id` | Yes | AE chat/workspace reference; CX does not own the chat document. |
| `interaction_id` | Yes | AE interaction reference for user-facing lineage. |
| `actor_claims_ref` | Yes | Safe OA-validated actor reference. |
| `service_claims_ref` | Yes | Safe service-auth reference. |
| `execution_mode` | Yes | `GROUNDED_ANSWER`, `DOCUMENT_SUMMARY`, or `DOCUMENT_GENERATION`. |
| `language` | Yes | Korean default; English supported. |
| `created_at` / `updated_at` | Yes | RFC3339 UTC timestamps. |
| `started_at` / `completed_at` | No | Present when work starts or reaches a terminal state. |

`generation_status` is not `current_stage`. The root record must preserve the
same separation used by the common job contract.

## Request Snapshot

CX stores a normalized, redacted summary of the AE-to-CX request.

| Field | Required | Notes |
| --- | --- | --- |
| `generation_request_hash` | Yes | Hash over the normalized AE request package. |
| `client_package_hash` | Yes | AE-owned package hash from Slice 426. |
| `user_prompt_ref` | Yes | Redacted or policy-controlled prompt reference; avoid raw prompt over-retention. |
| `context_scope` | Yes | Scope requested/applied for generation. |
| `template_id` / `template_version` | No | Content template selected by AE. |
| `prompt_contract_id` / `prompt_version` | Yes | User-facing prompt policy contract. |
| `output_schema_id` | Yes | Structured output schema requested. |
| `output_kind` | Yes | `chat_answer`, `structured_draft`, `markdown_artifact`, or future kind. |
| `generation_profile` | Yes | Logical profile accepted by CX. |
| `quality_policy_hash` | Yes | Hash of no-answer, citation, low-confidence, and completeness rules. |

Raw bearer tokens, passwords, provider URLs, and full source corpus blobs are not
stored in the request snapshot.

## Retrieval And Evidence Lineage

| Field | Required | Notes |
| --- | --- | --- |
| `retrieval_package_id` | Yes for grounded modes | CX package used for prompt package construction. |
| `retrieval_package_hash` | Yes for grounded modes | Prevents silent evidence drift. |
| `retrieval_status` | Yes | `READY`, `LOW_CONFIDENCE`, `PARTIAL`, `NO_ANSWER`, or `FAILED`. |
| `permission_snapshot_ref` | Yes | Permission policy and actor/scope snapshot used. |
| `selected_evidence_ids` | Yes | Final evidence IDs included or intentionally empty. |
| `selected_evidence_count` | Yes | Count after validation and filtering. |
| `source_anchor_count` | Yes | Number of source anchors available for citation. |
| `filtered_document_count` | No | Permission-filtered document count. |
| `filtered_chunk_count` | No | Permission-filtered chunk count. |
| `evidence_selection_policy` | Yes | `ae_selected`, `cx_auto_selected`, or `mixed`. |

Evidence refs should preserve `evidence_id`, `content_object_id`,
`content_version_id`, `chunk_id`, `chunk_policy_id`, `source_anchor`,
`citation_label`, `permission_result`, and score summary fields.

## Prompt Package Lineage

| Field | Required | Notes |
| --- | --- | --- |
| `provider_prompt_package_id` | Yes | CX prompt package record ID. |
| `provider_prompt_package_hash` | Yes | Hash passed to MO in Slice 427. |
| `prompt_package_schema_version` | Yes | Start with `cx_provider_prompt_package.v1`. |
| `message_count` | Yes | Count of provider-facing messages. |
| `estimated_input_tokens` | No | CX estimate before MO/provider tokenization. |
| `response_format_type` | Yes | `text`, `json_object`, or `json_schema`. |
| `response_schema_id` | No | Required when schema output is requested. |
| `untrusted_context_boundary` | Yes | Marks source chunks as untrusted context. |
| `prompt_retention_policy` | Yes | `hash_only`, `redacted_summary`, or `retain_full_by_policy`. |

CX can retain the full provider prompt only when policy allows it. The hash must
be retained even when the full prompt is not.

## MO Call Lineage

| Field | Required | Notes |
| --- | --- | --- |
| `mo_generation_id` | Yes when MO accepts | Stable MO generation execution ID. |
| `mo_job_id` | No | Present for queued, streaming, or async generation. |
| `mo_generation_request_hash` | Yes when MO accepts | Hash over normalized CX-to-MO provider request. |
| `alias` | Yes when MO accepts | Resolved logical alias. |
| `provider_capability` | Yes | Requested capability. |
| `workload_class` | Yes | Workload class sent to MO. |
| `model_revision` | No | Actual model revision returned by MO. |
| `deployment_id` | No | Selected deployment returned by MO. |
| `route_id` | No | MO route/policy ID when available. |
| `admission_decision` | No | `ACCEPTED`, `QUEUED`, `REJECTED`, or `THROTTLED`. |
| `finish_reason` | No | `STOP`, `LENGTH`, `TIMEOUT`, `CANCELLED`, or `ERROR`. |
| `queue_ms` / `provider_ms` / `total_ms` | No | Runtime latency metadata. |
| `usage` | No | Input/output/total tokens and safe throughput/cache metadata. |

CX stores MO runtime metadata but must not expose provider host secrets, model
file paths, or provider credentials to AE.

## Structured Draft And Validation

| Field | Required | Notes |
| --- | --- | --- |
| `structured_draft_id` | No | Present when structured output exists. |
| `structured_draft_schema_id` | No | Such as `structured-document-v1`. |
| `structured_draft_content_hash` | No | Hash over normalized draft content. |
| `structured_draft_validation_status` | No | `PENDING`, `VALID`, `INVALID`, `REPAIRED`, or `FAILED`. |
| `citation_validation_status` | Yes when citation required | `VALID`, `INVALID`, `PARTIAL`, `NOT_REQUIRED`, or `FAILED`. |
| `template_completeness_status` | No | `VALID`, `MISSING_REQUIRED_SECTION`, `PARTIAL`, or `NOT_REQUIRED`. |
| `missing_section_ids` | No | Required when template completeness fails. |
| `invalid_citation_count` | No | Count of citations not tied to evidence refs. |
| `repair_attempt_count` | No | Count of CX repair attempts. |

Structured draft schema details are defined in
[Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md).
This Slice freezes how draft and validation IDs/statuses connect back to the
generation execution record.

## Status And Stage Rules

| Event | Required Update |
| --- | --- |
| AE request accepted | Create root execution record with `generation_status=ACCEPTED`. |
| Evidence validated | Store retrieval package hash, selected evidence refs, and permission snapshot. |
| Prompt packaged | Store provider prompt package ID/hash and prompt retention policy. |
| MO request accepted | Store MO generation ID/job ID and route/admission metadata. |
| Provider output received | Store finish reason, usage, latency, and output hash or draft reference. |
| Draft validated | Store structured draft validation status and content hash. |
| Citation validated | Store citation validation status and invalid citation count. |
| Terminal result | Set `generation_status` and `completed_at`. |

Terminal statuses are `SUCCEEDED`, `REJECTED`, `FAILED`, `CANCELLED`, and
`TIMEOUT`. Terminal records must not return to `RUNNING` without creating a retry
or repair lineage edge.

## Retry And Repair Lineage

| Field | Required | Notes |
| --- | --- | --- |
| `parent_generation_id` | No | Prior CX generation execution when retrying or repairing. |
| `lineage_type` | Yes when parent exists | `retry`, `repair`, `regenerate`, or `sectional_retry`. |
| `lineage_reason` | No | Timeout, invalid citation, schema violation, user retry, or operator retry. |
| `attempt_no` | Yes | Starts at 1 for the first generation execution. |
| `supersedes_generation_id` | No | Previous execution replaced in AE-visible lineage. |

Retries must preserve the original retrieval package ID/hash unless the retry
explicitly requests fresh retrieval.

## AE And AG Read Views

`GET /api/v1/generations/{generation_id}` from AE to CX should expose a safe
lineage view:

| Field | Included | Notes |
| --- | --- | --- |
| Root execution metadata | Yes | Status, stage, timestamps, trace ID, request ID. |
| Retrieval package ref | Yes | ID/hash/status, score/confidence summary, permission snapshot summary. |
| Evidence refs | Yes | Evidence IDs, citation labels, source anchors, and safe snippets. |
| Prompt package hash | Yes | Full prompt body only when policy allows. |
| MO runtime metadata | Yes | Alias, model revision, deployment ID, usage, latency, finish reason. |
| Structured draft ref | Yes | Draft ID, schema ID, validation status, content hash. |
| Artifact refs | No | AE owns artifact records and download links. |
| Provider secrets | Never | No provider credentials, raw endpoint URLs, or model paths. |

AG can consume the same safe view plus audit fields for operations dashboards,
but AG should read through service APIs, not CX tables.

## Reproducibility Hashes

The following hashes should be persisted together:

```text
generation_request_hash
client_package_hash
retrieval_package_hash
provider_prompt_package_hash
mo_generation_request_hash
structured_draft_content_hash
```

These hashes are not a guarantee that a non-deterministic LLM will reproduce the
same text. They guarantee that the inputs, package boundaries, and runtime
metadata are auditable.

## Error And Guardrail Outcomes

| Outcome | Required Record Detail |
| --- | --- |
| `cx.no_answer_generation_blocked` | Retrieval package status/reason and quality policy that blocked generation. |
| `cx.prompt_template_mismatch` | Template ID/version and prompt contract ID/version. |
| `mo.alias_not_found` | Requested alias and provider capability. |
| `mo.admission_throttled` | Workload class, admission decision, and retry-after hint when available. |
| `mo.provider_timeout` | MO job ID, timeout budget, elapsed runtime metadata. |
| `cx.citation_validation_failed` | Invalid citation count and failed evidence/citation refs. |
| `cx.structured_draft_invalid` | Schema ID, validation errors summary, repair attempt count. |

All failure records preserve `request_id`, `trace_id`, safe actor metadata, and
retryability. They must not store raw tokens or unredacted provider prompts in
error details.

## Contract Tests To Derive

- Creating a CX generation execution stores request, retrieval, prompt package,
  and trace hashes separately.
- Evidence refs preserve `evidence_id`, `content_version_id`, `chunk_id`,
  `source_anchor`, `citation_label`, and permission result.
- MO acceptance stores `mo_generation_id`, optional `mo_job_id`, alias, model
  revision, deployment ID, route ID, admission decision, finish reason, usage,
  and latency metadata.
- Structured draft validation status uses `PENDING`, `VALID`, `INVALID`,
  `REPAIRED`, or `FAILED`.
- Citation validation failure records invalid citation count and does not mark
  the root execution as `SUCCEEDED`.
- Retry, repair, regenerate, and sectional retry executions link to a parent
  generation ID and increment `attempt_no`.
- AE safe read view includes lineage refs and excludes provider secrets.
- AG observes generation records through CX APIs, not direct database access.

## Next Inputs

This contract should feed:

- Structured draft and citation validation schema, starting from
  [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md).
- Generation progress event contract, starting from
  [Generation Progress Event Contract](21_generation_progress_event_contract.md).
- AE artifact rendering handoff contract, starting from
  [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md).
- Generation failure and retry policy contract, starting from
  [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md).
- AG generation audit and lineage dashboard requirements.
