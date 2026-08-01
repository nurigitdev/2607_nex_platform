# Generation OpenAPI Endpoint Seed

Status: Draft seed for Slice 437.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)
- [Service Boundary Decision Record](../../12_service_boundary_decision_record.md)
- [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md)
- [CX-to-AE Retrieval Context Package Contract](../../14_cx_ae_retrieval_context_package_contract.md)
- [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md)
- [CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)
- [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md)
- [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md)

This document seeds the OpenAPI surface for generation-related platform
contracts. It keeps endpoint ownership aligned with the service boundary while
giving future implementation slices a concrete path list to turn into OpenAPI
3.1 files and contract tests.

## API Conventions

| Convention | Decision |
| --- | --- |
| OpenAPI version | Use OpenAPI 3.1 so JSON Schema 2020-12 definitions can be reused. |
| Business routes | Use `/api/v1/...` within each service. |
| Admin routes | Use `/admin/v1/...` within `nex-ag` and service admin surfaces. |
| Health routes | Keep `/health`, `/ready`, and `/version` service-local. |
| Auth | User and service requests carry `Authorization`; services validate OA claims. |
| Correlation | Support `X-Request-ID`, `traceparent`, and `tracestate`. |
| Idempotency | Mutating create/control endpoints require `Idempotency-Key`. |
| Lists | Use `cursor`, `limit`, `next_cursor`, and `has_more`. |
| Errors | Use `application/problem+json` with stable `error_code`, `retryable`, `request_id`, and `trace_id`. |

Endpoint paths are service-local. The same path name in AE, CX, and MO does not
mean the same service owns the same data.

## AE API Seed

`nex-ae-api` owns user workspace orchestration, chat state, artifact metadata,
and artifact rendering.

| Method | Path | Request Schema | Response Schema | Notes |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/chat-interactions` | `ae_chat_interaction_request.v1` | `ae_chat_interaction_response.v1` | Accept user prompt, selected mode, runtime defaults, and optional template. |
| `GET` | `/api/v1/chat-documents/{chat_document_id}/messages` | Query params | `ae_chat_messages_page.v1` | Cursor-paginated chat message read. |
| `GET` | `/api/v1/chat-messages/{message_id}/artifact-links` | Path params | `ae_artifact_link.v1` page | Read artifact cards attached to one assistant message. |
| `POST` | `/api/v1/generation-requests` | `ae_generation_orchestration_request.v1` | `ae_generation_orchestration_response.v1` | AE facade that may call CX retrieval and CX generation. |
| `POST` | `/api/v1/artifacts` | `ae_artifact_handoff.v1` | `ae_artifact.v1` | Create AE artifact shell from a CX validated draft. |
| `GET` | `/api/v1/artifacts/{artifact_id}` | Path params | `ae_artifact.v1` | Read artifact metadata, current version, quality badges, and actions. |
| `GET` | `/api/v1/artifacts/{artifact_id}/versions` | Query params | `ae_artifact_versions_page.v1` | Read version lineage and current version marker. |
| `POST` | `/api/v1/artifacts/{artifact_id}/render-jobs` | `ae_artifact_render_request.v1` | `common_job.v1` | Start or retry rendering. |
| `GET` | `/api/v1/artifact-render-jobs/{render_job_id}` | Path params | `common_job.v1` | Read render progress. |
| `GET` | `/api/v1/artifact-render-jobs/{render_job_id}/events` | Query params | `generation_progress_event.v1` page | Read render events with same progress envelope. |
| `GET` | `/api/v1/artifact-files/{artifact_file_id}/download` | Path params | Binary or redirect | Recheck actor permission before download. |

AE can expose a single user-facing interaction endpoint while still calling CX
and MO through service boundaries internally.

## CX API Seed

`nex-cx` owns corpus retrieval, evidence packages, document-grounded generation
execution records, structured draft validation, citation validation, and safe
source detail reads.

| Method | Path | Request Schema | Response Schema | Notes |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/retrieval-context-packages` | `cx_retrieval_context_request.v1` | `cx_retrieval_context_package.v1` | AE requests permission-filtered evidence package. |
| `GET` | `/api/v1/retrieval-context-packages/{package_id}` | Path params | `cx_retrieval_context_package.v1` | Read package summary and safe evidence refs. |
| `POST` | `/api/v1/generations` | `ae_cx_generation_request.v1` | `ae_cx_generation_response.v1` | AE asks CX to run document-grounded generation. |
| `GET` | `/api/v1/generations/{generation_id}` | Path params | `cx_generation_execution.v1` | Safe generation execution read for AE/AG. |
| `GET` | `/api/v1/generations/{generation_id}/events` | Query params | `generation_progress_event.v1` page | Progress timeline. |
| `GET` | `/api/v1/generations/{generation_id}/events/stream` | Cursor/header | SSE `generation_progress_event.v1` | Optional streaming endpoint. |
| `POST` | `/api/v1/generations/{generation_id}/retry` | `generation_recovery_request.v1` | `ae_cx_generation_response.v1` | Retry or regenerate through lineage. |
| `POST` | `/api/v1/generations/{generation_id}/repair` | `generation_recovery_request.v1` | `ae_cx_generation_response.v1` | Repair draft/citation/section issues when policy allows. |
| `GET` | `/api/v1/generations/{generation_id}/structured-draft` | Path params | `cx_structured_draft.v1` | Read validated draft for AE artifact rendering. |
| `GET` | `/api/v1/generations/{generation_id}/citations` | Query params | `cx_citation_claim.v1` page | Read citation/source anchor validation. |

CX rejects AE requests that include provider URLs, raw model paths, provider API
keys, or selected evidence IDs outside the referenced retrieval package.

## MO API Seed

`nex-mo` owns provider admission, routing, model execution, streaming/cancel,
health, readiness, and provider usage metadata.

| Method | Path | Request Schema | Response Schema | Notes |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/generations` | `cx_mo_generation_request.v1` | `cx_mo_generation_response.v1` | CX calls MO by provider capability alias. |
| `GET` | `/api/v1/provider-generations/{mo_generation_id}` | Path params | `mo_generation_execution.v1` | Provider runtime status and usage summary. |
| `GET` | `/api/v1/provider-generations/{mo_generation_id}/events` | Query params | `generation_progress_event.v1` page | Provider progress mapped to public events. |
| `GET` | `/api/v1/provider-generations/{mo_generation_id}/stream` | Cursor/header | SSE delta/event stream | Optional streaming bridge. |
| `POST` | `/api/v1/provider-generations/{mo_generation_id}/cancel` | `common_cancel_request.v1` | `common_job.v1` | Cancel provider execution when supported. |
| `GET` | `/api/v1/provider-routes` | Query params | `mo_provider_routes_page.v1` | Read route aliases and capability summaries. |
| `GET` | `/api/v1/provider-routes/{route_id}/readiness` | Path params | `mo_provider_readiness.v1` | Health, readiness, and degraded reason. |

MO responses expose aliases, model revisions, usage, latency, readiness, and
finish reasons. They must not expose private host credentials or API keys.

## AG API Seed

`nex-ag` owns read-only governance projections, operator notes, and evidence
exports for MVP generation oversight.

| Method | Path | Request Schema | Response Schema | Notes |
| --- | --- | --- | --- | --- |
| `GET` | `/admin/v1/generation-audit/events` | Query params | `ag_generation_audit_event.v1` page | Filtered audit event timeline. |
| `GET` | `/admin/v1/generation-audit/generations/{generation_id}` | Path params | `ag_generation_detail.v1` | Aggregated AE/CX/MO/OA safe read. |
| `GET` | `/admin/v1/generation-audit/artifacts/{artifact_id}` | Path params | `ag_artifact_audit_detail.v1` | Artifact lineage, downloads, render jobs, and warnings. |
| `GET` | `/admin/v1/generation-audit/failures` | Query params | `ag_generation_failure_page.v1` | Failure/retry/repair summary. |
| `GET` | `/admin/v1/generation-audit/provider-usage` | Query params | `ag_provider_usage_summary.v1` | Provider usage and degraded state summary. |
| `POST` | `/admin/v1/generation-audit/exports` | `ag_audit_export_request.v1` | `common_job.v1` | Export redacted evidence snapshot. |
| `POST` | `/admin/v1/generation-audit/notes` | `ag_operator_note_request.v1` | `ag_operator_note.v1` | Add an operator note without mutating source records. |

AG write actions affect AG projection records only unless a later policy
contract explicitly delegates a control operation to AG.

## OA Touchpoints

Generation flows rely on OA but do not move auth ownership into AE/CX/MO/AG.

| Method | Path | Consumer | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/v1/auth/jwks` | All services | Validate signed service/user tokens. |
| `POST` | `/api/v1/auth/introspect` | Backend services | Optional token introspection for opaque tokens. |
| `GET` | `/api/v1/auth/audit-events` | AG | Safe auth event read by trace ID, actor, or service principal. |

OA endpoints are listed here only as dependencies for generation contract
testing.

## Error Codes To Surface

| Code | Source |
| --- | --- |
| `auth.claim_invalid` | OA/target service |
| `cx.retrieval_package_not_found` | CX |
| `cx.retrieval_package_hash_mismatch` | CX |
| `cx.no_answer_generation_blocked` | CX |
| `cx.low_confidence_generation_blocked` | CX |
| `cx.prompt_template_mismatch` | CX |
| `cx.output_schema_unsupported` | CX |
| `cx.generation_parameter_out_of_bounds` | CX/MO |
| `mo.admission_throttled` | MO |
| `mo.provider_timeout` | MO |
| `ae.render_job_failed` | AE |
| `ae.artifact_access_denied` | AE |

Every error response must include `request_id`, `trace_id`, and `retryable`
where the source service can determine retryability.

## Contract Tests To Derive

- Mutating AE/CX/MO/AG endpoints require `Idempotency-Key` when they create or
  control work.
- CX generation rejects provider runtime fields in AE requests.
- MO generation accepts capability aliases, not raw provider URLs.
- AE artifact downloads recheck actor permission and never expose raw paths.
- AG audit endpoints read through service APIs and return cursor pagination.
- SSE and polling event APIs return the same `generation_progress_event.v1`
  envelope.
- OpenAPI examples validate against the JSON Schema seed catalog.

## Next Inputs

This endpoint seed should feed:

- Generation E2E acceptance scenario and contract test plan, starting from
  [Generation E2E Acceptance + Contract Test Plan](../../28_generation_e2e_acceptance_contract_test_plan.md).
- Service-specific OpenAPI file generation, starting from
  [Common Schema + Contract Package Layout](../../33_common_schema_contract_package_layout.md).
- Contract test fixtures and example payloads.
