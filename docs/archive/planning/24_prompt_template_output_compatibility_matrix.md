# Prompt/Template/Output Compatibility Matrix

Status: Draft seed for Slice 434.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md)
- [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)

This document freezes the first compatibility matrix for generation profiles,
prompt contracts, templates, output schemas, artifact intents, and provider
capabilities. It prevents the class of PCX issue where a report template is
selected but the stored prompt version still looks like a grounded answer
contract.

## Compatibility Ownership

| Area | Owner | Decision |
| --- | --- | --- |
| User intent and execution mode | AE | AE selects the initial mode and may ask CX for intent support, but AE owns the user-facing decision. |
| Template selection | AE | AE owns template ID/version, required sections, rendering hints, and allowed target formats. |
| Prompt contract selection | AE | AE selects a prompt contract that is explicitly compatible with the template and output schema. |
| Compatibility validation | AE first, CX final | AE blocks obvious mismatches before request; CX rejects mismatches before provider execution. |
| Structured output validation | CX | CX validates the returned draft against the output schema and citation policy. |
| Provider capability validation | CX -> MO | CX asks MO for generation through capability aliases, not raw model endpoints. |
| Artifact rendering | AE | AE renders only output kinds and target formats allowed by the compatibility rule. |
| Governance visibility | AG | AG reads compatibility decisions, warnings, and override events through service APIs. |

Compatibility is a contract. It should not be inferred from display labels or
latest-version defaults.

## Rule Key

Each compatibility rule should be addressable by a stable key.

| Field | Required | Notes |
| --- | --- | --- |
| `compatibility_rule_id` | Yes | Stable ID such as `report_grounded_docx_v1`. |
| `rule_schema_version` | Yes | Start with `generation_compatibility_rule.v1`. |
| `execution_mode` | Yes | `GENERAL_ANSWER`, `GROUNDED_ANSWER`, `DOCUMENT_SUMMARY`, or `DOCUMENT_GENERATION`. |
| `template_type` | No | `report`, `proposal`, `memo`, `summary`, or `none`. |
| `template_version_range` | No | Explicit version or semver-like range allowed by AE. |
| `prompt_contract_id` | Yes | Stable prompt contract family. |
| `prompt_version_range` | Yes | Explicit version or compatible range. |
| `output_schema_id` | Yes | Structured draft or chat-answer schema. |
| `artifact_intent` | Yes | `none`, `preview_only`, `create_artifact`, or `create_and_export`. |
| `target_formats` | Yes | Allowed formats such as `MD`, `DOCX`, `PDF`, or `HTML_PREVIEW`. |
| `quality_policy_id` | Yes | Citation, no-answer, confidence, and completeness policy. |
| `generation_profile` | Yes | Logical generation profile used by CX. |
| `provider_capability` | Yes | MO capability alias, not a provider URL or model path. |
| `active` | Yes | Inactive rules must not be selected by default. |

AE can store a local copy for UX speed, but CX performs authoritative
validation before generation execution.

## MVP Compatibility Matrix

| Use Case | Execution Mode | Template | Prompt Contract | Output Schema | Artifact Intent | Target Formats | Required Quality |
| --- | --- | --- | --- | --- | --- | --- | --- |
| General chat answer | `GENERAL_ANSWER` | None | `general_answer_v1` | `chat-answer-v1` | `none` | None | Citation not required, no source claims. |
| Grounded answer | `GROUNDED_ANSWER` | None | `grounded_answer_v1` | `grounded-answer-v1` | `none` or `preview_only` | `MD` optional | Citation required when evidence is used. |
| Corpus summary | `DOCUMENT_SUMMARY` | `summary` optional | `document_summary_v1` | `structured-summary-v1` | `preview_only` or `create_artifact` | `MD`, `DOCX` optional | Citation or source-section trace required. |
| Report document | `DOCUMENT_GENERATION` | `report` required | `report_generation_v1` | `structured-document-v1` | `create_and_export` | `MD`, `DOCX`, `PDF` optional | Required sections and citations validated. |
| Proposal document | `DOCUMENT_GENERATION` | `proposal` required | `proposal_generation_v1` | `structured-document-v1` | `create_and_export` | `MD`, `DOCX`, `PDF` optional | Required sections and citations validated. |
| Memo document | `DOCUMENT_GENERATION` | `memo` required | `memo_generation_v1` | `structured-document-v1` | `create_artifact` | `MD`, `DOCX` | Required sections validated; citations policy-driven. |
| Answer export | `GROUNDED_ANSWER` | `answer_export` optional | `grounded_answer_v1` | `grounded-answer-v1` | `create_artifact` | `MD`, `DOCX`, `PDF` optional | Same citation status as source answer. |
| Artifact transform | `DOCUMENT_GENERATION` | Existing artifact template | `artifact_transform_v1` | `structured-document-v1` | `create_and_export` | Target policy | Source artifact lineage required. |

The matrix is intentionally small. New rows should be added only when a real
workflow needs a new combination.

## Selection Flow

1. AE receives the user prompt and determines `execution_mode`.
2. AE selects a template only when the selected mode and user intent require
   one.
3. AE selects a prompt contract from the compatibility matrix, not from a
   display name.
4. AE packages `template_ref`, `prompt_contract_ref`, `output_contract`, and
   `quality_policy`.
5. CX validates the submitted combination against the active compatibility
   rules.
6. CX builds the provider-facing prompt package only after compatibility and
   retrieval/package checks pass.
7. AE renders artifacts only in formats allowed by the validated rule.

When AE has no exact rule, it should stop and ask the user/operator to choose a
supported mode or template rather than silently falling back.

## Mismatch Handling

| Case | Owner | Result |
| --- | --- | --- |
| Template selected but prompt contract is for another template type | AE/CX | Reject with `cx.prompt_template_mismatch`. |
| Document output requested without a template | AE | Reject before CX call with `ae.template_required`. |
| Template requires sections missing from output schema | AE/CX | Reject with `ae.template_required_section_mismatch`. |
| Export format not allowed for artifact intent | AE | Reject with `ae.output_format_not_allowed`. |
| Output schema unsupported by CX validator | CX | Reject with `cx.output_schema_unsupported`. |
| Generation profile exceeds provider capability or policy | CX/MO | Reject or clamp with `cx.generation_parameter_out_of_bounds`. |
| Inactive compatibility rule selected | AE/CX | Reject with `ae.compatibility_rule_inactive`. |

All rejections use the common `application/problem+json` envelope and include a
safe compatibility summary, not full prompts or provider details.

## Version Policy

| Object | Version Rule |
| --- | --- |
| Template | AE request must include explicit `template_version`. |
| Prompt contract | AE request must include explicit `prompt_version`. |
| Output schema | CX validator records exact schema ID/version used. |
| Quality policy | Store policy ID and hash in AE/CX records. |
| Compatibility rule | Store rule ID/version and hash in the generation execution record. |
| Artifact version | Store the validated rule ID/hash used to render it. |

Default versions can exist in configuration, but resolved generation records
must never say only `latest`.

## Audit Requirements

AG should be able to answer:

- Which template, prompt contract, output schema, and compatibility rule were
  used for a generation?
- Was the selected rule active at request time?
- Did CX reject or warn because of a mismatch?
- Did an operator override a warning or manual acceptance policy?
- Which artifacts were produced from a validated compatibility rule?

The audit view should expose IDs, versions, hashes, actor refs, timestamps,
status, and warning codes. It should not expose raw provider prompts by default.

## Contract Tests To Derive

- Report templates cannot run with `grounded_answer_v1`.
- Document generation without a template is rejected before provider execution.
- Inactive compatibility rules cannot be selected by default.
- CX stores compatibility rule ID/version/hash in the generation execution
  record.
- AE artifact rendering accepts only target formats allowed by the validated
  compatibility rule.
- Compatibility rejection returns `application/problem+json` with stable error
  code, `request_id`, and `trace_id`.
- Explicit template and prompt versions are required; implicit `latest` is not
  accepted in persisted generation records.

## Next Inputs

This matrix should feed:

- AG generation and artifact audit dashboard requirements, starting from
  [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md).
- Generation JSON Schema seed, starting from
  [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md).
- Generation OpenAPI endpoint seed, starting from
  [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md).
- Generation E2E acceptance scenario and contract test plan.
