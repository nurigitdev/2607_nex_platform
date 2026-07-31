# AE-to-CX Generation Request Package Contract

Status: Draft seed for Slice 426.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- [AE Agent Orchestration Contract](13_ae_agent_orchestration_contract.md)
- [CX-to-AE Retrieval Context Package Contract](14_cx_ae_retrieval_context_package_contract.md)
- [Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md)

This document freezes the first request package that `nex-ae-api` sends to
`nex-cx` when a user-facing interaction needs document-grounded generation,
summary, or structured draft creation. The package lets AE keep ownership of
intent, template selection, user-facing prompt policy, output target, final
formatting, and artifact links while CX keeps ownership of evidence continuity,
provider-facing prompt package construction, citation validation, and the
generation execution record that later connects to `nex-mo`.

## Direction Decision

| Interaction | Caller | Receiver | Endpoint | Decision |
| --- | --- | --- | --- | --- |
| Generation request | `nex-ae-api` | `nex-cx` | `POST /api/v1/generations` | AE sends a Generation Request Package, not a raw provider prompt. |
| Generation status/result | `nex-ae-api` | `nex-cx` | `GET /api/v1/generations/{generation_id}` | CX returns structured draft, citation status, package hashes, and MO usage metadata. |
| Provider execution | `nex-cx` | `nex-mo` | `POST /api/v1/generations` | CX builds provider-facing prompt package and calls MO by capability alias. |
| Artifact rendering | `nex-ae-api` | Internal AE artifact API/job | AE-owned route | AE renders Markdown/DOCX/PDF artifacts from CX result metadata. |

The endpoint name `/api/v1/generations` is service-local. AE calls the CX
generation API; CX calls the MO generation API. AE does not call MO directly for
document-grounded generation.

## Request Envelope

`POST /api/v1/generations` from AE to CX should use `Idempotency-Key`,
`X-Request-ID`, and `traceparent` headers. The body is a JSON-compatible
Generation Request Package.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `request_schema_version` | Yes | Shared | Start with `ae_cx_generation_request.v1`. |
| `request_id` | Yes | AE | Stable request correlation ID from AE. |
| `trace_id` | Yes | Shared | Propagated across AE, CX, MO, logs, and audit. |
| `chat_document_id` | Yes | AE | User workspace/chat target; CX stores only lineage reference. |
| `interaction_id` | Yes | AE | User-facing chat interaction that triggered generation. |
| `actor_claims_ref` | Yes | OA/AE | Validated claim reference; no raw bearer token or password. |
| `service_claims_ref` | Yes | OA/AE | Service-to-service trust reference for AE calling CX. |
| `execution_mode` | Yes | AE | `GROUNDED_ANSWER`, `DOCUMENT_SUMMARY`, or `DOCUMENT_GENERATION`. |
| `language` | Yes | AE | Korean default; English supported. |
| `user_prompt` | Yes | AE | Original user prompt or approved edited prompt. |
| `intent_summary` | No | AE | Short structured intent summary; CX does not re-own final intent. |
| `retrieval_package_ref` | Yes for grounded modes | CX/AE | Package ID/hash/status from CX retrieval context package. |
| `selected_evidence_ids` | No | AE/CX | Subset of evidence IDs from the referenced retrieval package. |
| `context_scope` | Yes | AE/CX | Workspace, collection, document, group, classification, or global scope. |
| `template_ref` | Yes for document outputs | AE | Content template ID/version and selected section policy. |
| `prompt_contract_ref` | Yes | AE | Prompt contract ID/version and user-facing system prompt policy ID. |
| `output_contract` | Yes | AE | Output schema, target format, artifact intent, and rendering hint. |
| `generation_parameters` | Yes | AE/CX | Bounded generation settings; CX may clamp to policy. |
| `quality_policy` | Yes | AE/CX | Citation, no-answer, low-confidence, and completeness behavior. |
| `client_package_hash` | Yes | AE | Hash over the AE-owned policy package for replay detection. |
| `requested_at` | Yes | AE | RFC3339 UTC timestamp. |

## Retrieval Package Reference

The retrieval reference prevents AE from copying ad hoc chunks into generation
history and lets CX verify evidence freshness.

| Field | Required | Notes |
| --- | --- | --- |
| `retrieval_package_id` | Yes | Stable CX retrieval package identifier. |
| `package_hash` | Yes | Hash over query, profile, permissions, evidence IDs, and scoring metadata. |
| `status` | Yes | `READY`, `LOW_CONFIDENCE`, `PARTIAL`, or other CX status. |
| `confidence_bucket` | No | User-facing confidence bucket used by AE guardrails. |
| `retrieval_profile` | No | Search strategy, chunk policy, BM25 tokenizer, embedding profile, reranker profile. |

Rules:

- `selected_evidence_ids` must be empty or a subset of the referenced package.
- CX rejects stale or unknown `retrieval_package_id` / `package_hash` pairs.
- CX applies permission validation again before provider-facing prompt package
  construction.
- `NO_ANSWER` retrieval packages cannot be used for grounded generation unless
  AE explicitly changes the mode to a general answer policy.

## Template And Prompt Contract

AE owns the user-facing template and prompt policy, but CX owns the
provider-facing prompt package.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `template_ref.template_id` | Yes for documents | AE | Content template such as report, proposal, summary, or memo. |
| `template_ref.template_version` | Yes | AE | Explicit version, not implicit latest. |
| `template_ref.required_section_ids` | No | AE | Sections AE expects CX output to cover. |
| `prompt_contract_ref.prompt_contract_id` | Yes | AE | Stable prompt contract, not a hidden free-form prompt. |
| `prompt_contract_ref.prompt_version` | Yes | AE | Must align with template type/version. |
| `prompt_contract_ref.system_prompt_policy_id` | Yes | AE | User-facing policy reference; full text retention is policy controlled. |
| `prompt_contract_ref.citation_style` | Yes | AE/CX | Citation format AE expects CX to validate. |

CX should persist the resulting `provider_prompt_package_hash`, template
metadata, selected evidence IDs, output schema ID, and generation profile in the
CX generation execution record.

## Output Contract

| Field | Required | Notes |
| --- | --- | --- |
| `output_schema_id` | Yes | Structured output schema such as `structured-document-v1`. |
| `output_kind` | Yes | `chat_answer`, `structured_draft`, `markdown_artifact`, or future kind. |
| `artifact_intent` | No | `none`, `preview_only`, `create_artifact`, or `create_and_export`. |
| `artifact_title` | No | AE-owned display title for generated artifact. |
| `preferred_export_format` | No | `MD`, `DOCX`, `PDF`, or later format. |
| `rendering_template_id` | No | AE rendering template hint; CX should not own rendering. |

CX returns structured content and validation metadata. AE decides whether and how
to render user-facing artifacts.

## Generation Parameters

| Field | Required | Notes |
| --- | --- | --- |
| `generation_profile` | Yes | Logical profile such as `grounded-answer`, `summary`, or `general-document`. |
| `provider_capability` | No | Preferred capability alias; CX may choose default before calling MO. |
| `max_tokens` | Yes | Bounded by CX/MO policy; document outputs can request larger limits. |
| `temperature` | Yes | Bounded by policy. |
| `streaming` | Yes | Whether AE expects progress or streaming semantics. |
| `timeout_ms` | Yes | End-to-end CX generation timeout budget. |
| `seed` | No | Optional reproducibility seed if provider supports it. |

AE must not send provider URL, port, raw vLLM options, or model file paths.

## Quality Policy

| Field | Required | Notes |
| --- | --- | --- |
| `grounding_required` | Yes | True for grounded answer, summary, and source-based document generation. |
| `citation_required` | Yes | Whether CX must validate citations before returning success. |
| `low_confidence_behavior` | Yes | `block`, `warn`, `ask_confirmation`, or `allow_with_caveat`. |
| `no_answer_behavior` | Yes | `block_grounded_generation` unless AE explicitly selects general answer. |
| `template_completeness_required` | No | Whether all required sections must be present. |
| `untrusted_context_boundary` | Yes | CX must treat source chunks as untrusted context. |

## Response Shape

CX should return `202 Accepted` for asynchronous generation and may return
`200 OK` only when a short generation completed synchronously.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `generation_id` | Yes | CX | Stable CX generation execution record ID. |
| `request_schema_version` | Yes | Shared | Echoed request schema version. |
| `generation_status` | Yes | CX | `ACCEPTED`, `RUNNING`, `SUCCEEDED`, `REJECTED`, or `FAILED`. |
| `current_stage` | Yes | CX | Uses common job-stage semantics, not lifecycle state. |
| `retrieval_package_ref` | Yes | CX | Echoed and verified package ID/hash. |
| `provider_prompt_package_hash` | No | CX | Present after CX builds provider-facing prompt package. |
| `structured_draft_id` | No | CX | Present when structured draft exists. |
| `citation_validation_status` | No | CX | `VALID`, `INVALID`, `PARTIAL`, or `NOT_REQUIRED`. |
| `quality_metadata` | No | CX | No-answer, confidence, warning, and completeness metadata. |
| `provider_usage` | No | MO/CX | Tokens, latency, provider alias, model revision, and runtime metadata. |
| `warnings` | No | CX | Stale index, partial evidence, tokenizer fallback, or provider warning. |
| `created_at` / `updated_at` | Yes | CX | RFC3339 UTC timestamps. |

## Idempotency And Replay

- `Idempotency-Key` is required for mutating generation requests.
- Same key plus same `client_package_hash` returns the same `generation_id`.
- Same key plus different package hash returns `409 Conflict`.
- CX stores a `generation_request_hash` over the normalized AE request package.
- AE stores the CX `generation_id` in chat interaction lineage after acceptance.

## Rejection Cases

| Case | HTTP Status | Error Code |
| --- | --- | --- |
| Missing or invalid OA claim reference | `401` or `403` | `auth.claim_invalid` |
| Unknown retrieval package | `404` | `cx.retrieval_package_not_found` |
| Retrieval package hash mismatch | `409` | `cx.retrieval_package_hash_mismatch` |
| Evidence IDs outside package | `422` | `cx.evidence_selection_invalid` |
| No-answer package used for grounded generation | `409` | `cx.no_answer_generation_blocked` |
| Template and prompt contract mismatch | `422` | `cx.prompt_template_mismatch` |
| Provider URL or raw model path supplied by AE | `422` | `cx.provider_runtime_field_forbidden` |
| Generation parameter outside policy | `422` | `cx.generation_parameter_out_of_bounds` |

All errors use the common `application/problem+json` envelope and preserve
`request_id`, `trace_id`, and safe actor metadata.

## Guardrails

| Guardrail | Rule |
| --- | --- |
| No direct provider fields | AE cannot send raw provider URL, port, model path, or vLLM-specific private options. |
| No copied evidence blob | AE references CX evidence IDs and package hash rather than copying source chunks as a private prompt. |
| No hidden prompt drift | Prompt contract ID/version and template ID/version are explicit and stored. |
| No unsupported grounded claim | CX blocks or warns based on retrieval status and quality policy. |
| No artifact ownership leak | CX returns structured draft metadata; AE owns rendering, artifact records, and download links. |
| No lost lineage | AE and CX both persist request hash, retrieval package hash, generation ID, and trace ID. |

## Contract Tests To Derive

- AE generation request includes `request_schema_version`, `request_id`,
  `trace_id`, `chat_document_id`, `interaction_id`, and claim references.
- `selected_evidence_ids` must be a subset of the referenced retrieval package.
- `retrieval_package_id` plus `package_hash` mismatch returns `409`.
- `NO_ANSWER` package blocks grounded generation unless AE changes the mode.
- Template ID/version must align with prompt contract ID/version.
- AE request containing raw provider URL, port, or model path is rejected.
- Idempotent replay returns the same `generation_id`; conflicting replay returns
  `409`.
- CX response includes `generation_id`, `generation_status`, `current_stage`,
  retrieval package echo, and timestamps.
- Successful CX result exposes `provider_prompt_package_hash`, citation
  validation status, structured draft reference, and MO usage metadata when
  available.

## Next Inputs

This contract should feed:

- CX-to-MO generation provider request/response contract, starting from
  [CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md).
- CX generation execution record and lineage contract, starting from
  [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md).
- Structured draft and citation validation schema, starting from
  [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md).
- AE artifact rendering handoff contract, starting from
  [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md).
- Prompt/template/output compatibility rule matrix, starting from
  [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md).
- OA service scope catalog for `ae:generation.request` and `cx:generation.run`.
- AG generation audit and lineage dashboard requirements.
