# Generation Contract JSON Schema Seed

Status: Draft seed for Slice 436.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)
- [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md)
- [CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md)
- [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
- [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Progress Event Contract](21_generation_progress_event_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)
- [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md)
- [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md)

This document seeds the JSON Schema set that should be generated from the
generation contract documents. It is not the final schema package. Its purpose is
to freeze schema names, ownership, validation posture, and cross-reference
rules before OpenAPI endpoints and contract tests are written.

## Schema Convention

| Convention | Decision |
| --- | --- |
| Draft | Use JSON Schema 2020-12 unless service tooling forces a documented exception. |
| File naming | Use lower_snake_case schema names with version suffix, such as `ae_cx_generation_request.v1.schema.json`. |
| Object naming | Use lower_snake_case field names and UPPER_SNAKE_CASE enum values. |
| Time | Use RFC3339 UTC string fields with `format: date-time`. |
| IDs | Use UUID strings for first-platform internal IDs. |
| Nullable fields | Prefer absent optional fields over `null` unless `null` has explicit meaning. |
| Unknown fields | Reject by default on write contracts; allow extension blocks only where named. |
| Error shape | Validation errors map to the shared `application/problem+json` envelope. |
| Redaction | Schemas must not include raw secrets, provider host paths, or full prompts unless a retention policy explicitly allows it. |

Schemas are shared contract artifacts. They do not imply a shared database or a
shared runtime utility package.

## Schema Catalog Seed

| Schema ID | Owner | Source Contract | Purpose |
| --- | --- | --- | --- |
| `ae_cx_generation_request.v1` | AE/CX | Slice 426 | AE-owned request package for CX-mediated generation. |
| `ae_cx_generation_response.v1` | CX | Slice 426 | CX accepted/result summary returned to AE. |
| `cx_mo_generation_request.v1` | CX/MO | Slice 427 | Provider-facing generation request sent from CX to MO. |
| `cx_mo_generation_response.v1` | MO | Slice 427 | Provider execution result, streaming handle, usage, and finish metadata. |
| `cx_generation_execution.v1` | CX | Slice 428 | Root generation execution record and safe read shape. |
| `cx_generation_lineage.v1` | CX | Slice 428/432 | Retry, repair, regenerate, and supersede lineage edge. |
| `cx_structured_draft.v1` | CX | Slice 429 | Section/block draft shape returned to AE. |
| `cx_citation_claim.v1` | CX | Slice 429 | Citation claim and source anchor validation record. |
| `ae_artifact_handoff.v1` | AE/CX | Slice 430 | Handoff package from CX validated draft to AE artifact rendering. |
| `ae_artifact_link.v1` | AE | Slice 433 | Artifact card/link shape embedded in chat messages. |
| `generation_progress_event.v1` | AE/CX/MO/AG | Slice 431 | Long-running generation and render progress event envelope. |
| `generation_recovery_policy.v1` | AE/CX/MO/AG | Slice 432 | Failure class, retryability, action, and repair policy shape. |
| `generation_compatibility_rule.v1` | AE/CX | Slice 434 | Valid template/prompt/output/provider combinations. |
| `ag_generation_audit_event.v1` | AG | Slice 435 | Redacted audit projection for dashboard and export. |

The schema catalog should be implemented before service teams add endpoint
payloads that rely on free-form dictionaries.

## Shared Definitions

Common reusable schema definitions should include:

| Definition | Values Or Shape |
| --- | --- |
| `ServiceId` | `nex-oa`, `nex-ag`, `nex-ae-web`, `nex-ae-api`, `nex-cx`, `nex-mo`. |
| `JobStatus` | `PENDING`, `QUEUED`, `RUNNING`, `CANCEL_REQUESTED`, `CANCELLED`, `RETRYING`, `COMPLETED`, `FAILED`, `TIMEOUT`. |
| `ProgressMode` | `DETERMINATE`, `INDETERMINATE`, `STREAMING`. |
| `ExecutionMode` | `GENERAL_ANSWER`, `GROUNDED_ANSWER`, `DOCUMENT_SUMMARY`, `DOCUMENT_GENERATION`. |
| `ArtifactIntent` | `none`, `preview_only`, `create_artifact`, `create_and_export`. |
| `ArtifactStatus` | `DRAFT`, `RENDERING`, `READY`, `FAILED`, `ARCHIVED`, `DELETED`. |
| `TargetFormat` | `MD`, `HTML_PREVIEW`, `DOCX`, `PDF`. |
| `ValidationStatus` | `PENDING`, `VALID`, `INVALID`, `PARTIAL`, `REPAIRED`, `FAILED`, `NOT_REQUIRED`. |
| `TraceRefs` | `trace_id`, `request_id`, optional `traceparent`. |
| `ActorRefs` | Safe actor and service claim references, never raw tokens. |
| `HashRef` | Algorithm, value, and source field summary when hash reproducibility matters. |

These definitions can live in a shared schema directory and be referenced by
service-owned schemas.

## Minimal Schema Skeleton

Example style for later concrete files:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://contracts.nex-platform.local/schemas/generation/ae_cx_generation_request.v1.schema.json",
  "title": "AE to CX Generation Request",
  "type": "object",
  "required": [
    "request_schema_version",
    "request_id",
    "trace_id",
    "chat_document_id",
    "interaction_id",
    "actor_claims_ref",
    "execution_mode",
    "prompt_contract_ref",
    "output_contract",
    "generation_parameters",
    "quality_policy",
    "requested_at"
  ],
  "additionalProperties": false,
  "properties": {
    "request_schema_version": { "const": "ae_cx_generation_request.v1" },
    "request_id": { "type": "string", "format": "uuid" },
    "trace_id": { "type": "string" },
    "execution_mode": { "$ref": "../common/execution_mode.v1.schema.json" },
    "requested_at": { "type": "string", "format": "date-time" }
  }
}
```

The example is intentionally incomplete. The final schema files should be
generated from the field tables in the contract documents and reviewed as their
own implementation slice.

## Validation Rules

| Rule | Requirement |
| --- | --- |
| Write requests | Reject unknown fields unless an explicit `extensions` object is present. |
| Read responses | May include additive optional fields, but must not remove required fields within the same major version. |
| Version references | Persist exact schema ID/version used by request, execution, draft, artifact, and audit records. |
| Compatibility | Validate `generation_compatibility_rule.v1` before CX builds provider prompts. |
| Lineage | Validate retry/repair lineage before terminal records are superseded. |
| Redaction | Schema examples and generated docs must use placeholders for secrets and prompt bodies. |
| Localization | UI labels and localized messages stay outside schema enum values. |

## Contract Tests To Derive

- Every write schema rejects unknown top-level fields by default.
- Required ID, trace, actor, status, timestamp, and version fields are enforced.
- `execution_mode`, `job_status`, `progress_mode`, and artifact enums use only
  frozen values.
- `ae_cx_generation_request.v1` cannot contain raw provider URL, port, model
  path, or API key fields.
- Compatibility rule schema requires template/prompt/output/provider fields.
- Audit event schema allows redacted summaries but rejects full prompt and
  secret-like fields.
- Example payloads in OpenAPI validate against the schema catalog.

## Next Inputs

This seed should feed:

- Generation OpenAPI endpoint seed, starting from
  [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md).
- Generation E2E acceptance scenario and contract test plan, starting from
  [Generation E2E Acceptance + Contract Test Plan](../../28_generation_e2e_acceptance_contract_test_plan.md).
- Schema package layout decision, starting from
  [Common Schema + Contract Package Layout](../../33_common_schema_contract_package_layout.md).
