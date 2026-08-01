# CX-to-MO Generation Provider Contract

Status: Draft seed for Slice 427.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- [Service Boundary Decision Record](12_service_boundary_decision_record.md)
- [Generation Routing Boundary Reconciliation](./archive/planning/15_generation_routing_boundary_reconciliation.md)
- [AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md)

This document freezes the first provider-facing generation contract between
`nex-cx` and `nex-mo`. CX owns retrieval evidence, content template alignment,
provider-facing prompt package construction, structured draft validation, and
citation lineage. MO owns alias resolution, admission control, provider routing,
model runtime execution, streaming/cancel semantics, and usage/latency metadata.

MO is not a document-generation orchestrator. It receives resolved messages or a
resolved prompt package from CX and returns model output plus runtime metadata.
It must not receive raw source chunks as an implicit private retrieval package,
content template ownership decisions, artifact rendering instructions, or raw
provider endpoint details selected by CX.

## Direction Decision

| Interaction | Caller | Receiver | Endpoint | Decision |
| --- | --- | --- | --- | --- |
| Synchronous or queued generation | `nex-cx` | `nex-mo` | `POST /api/v1/generations` | CX sends a stable MO Generation Provider Request by alias/capability. |
| Streaming generation | `nex-cx` | `nex-mo` | `POST /api/v1/generations/stream` | MO emits provider runtime events; CX maps them to CX generation progress. |
| Generation cancel | `nex-cx` | `nex-mo` | `POST /api/v1/jobs/{job_id}/cancel` | CX can cancel a MO generation job it created. |
| Provider runtime | `nex-mo` | Provider adapter | Internal MO route | MO hides vLLM/provider URLs, model paths, ports, and deployment details. |

CX calls MO with service-auth claims and stable aliases. CX does not call vLLM,
FastAPI provider runtimes, or model-host ports directly.

## Request Headers

| Header | Required | Notes |
| --- | --- | --- |
| `Authorization` | Yes | OA-issued service token for CX calling MO. |
| `Idempotency-Key` | Yes for create | Same key and same request hash returns the same MO request/job result. |
| `X-Request-ID` | Yes | CX request ID for operator support. |
| `traceparent` | Yes | Distributed trace propagated from AE through CX to MO. |
| `X-Service-ID` | Yes | Must identify `nex-cx`. |
| `Content-Type` | Yes | `application/json`. |

## Generation Provider Request

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `request_schema_version` | Yes | Shared | Start with `cx_mo_generation_request.v1`. |
| `client_request_id` | Yes | CX | CX generation execution request ID. |
| `trace_id` | Yes | Shared | Propagated from AE/CX. |
| `cx_generation_id` | Yes | CX | CX generation execution record ID. |
| `provider_prompt_package_hash` | Yes | CX | Hash over resolved provider-facing prompt package. |
| `alias` | Yes | CX/MO | Stable logical alias such as `general-llm-default` or `long-document-llm`. |
| `provider_capability` | Yes | CX/MO | `generation`, `summary_generation`, `long_document_generation`, or similar capability. |
| `workload_class` | Yes | CX/MO | `LLM_INTERACTIVE`, `LLM_DOCUMENT`, `LLM_BATCH`, or later class. |
| `generation_profile` | Yes | CX | Logical profile such as `grounded-answer`, `summary`, or `general-document`. |
| `messages` | Yes unless `prompt` is used | CX | Resolved provider-facing messages. |
| `prompt` | No | CX | Optional single prompt for providers that do not use chat messages. |
| `response_format` | Yes | CX/MO | Text or JSON Schema constrained output. |
| `max_output_tokens` | Yes | CX/MO | Bounded by MO deployment policy. |
| `temperature` | Yes | CX/MO | Bounded by MO deployment policy. |
| `top_p` | No | CX/MO | Optional; bounded by policy when supplied. |
| `stream` | Yes | CX | Whether CX expects streaming events. |
| `timeout_ms` | Yes | CX/MO | MO admission plus provider execution timeout budget. |
| `seed` | No | CX/MO | Optional reproducibility seed if provider supports it. |
| `metadata` | Yes | CX | Safe lineage metadata; no raw tokens or full private source corpus dump. |

## Metadata Object

`metadata` lets MO return useful runtime evidence without becoming the owner of
document semantics.

| Field | Required | Notes |
| --- | --- | --- |
| `retrieval_package_id` | Yes for grounded generation | CX package ID used to build the prompt. |
| `retrieval_package_hash` | Yes for grounded generation | Package hash used by CX. |
| `generation_request_hash` | Yes | Hash over normalized AE-to-CX request package. |
| `content_template_id` | No | Template ID used by CX prompt packaging. |
| `content_template_version` | No | Explicit template version. |
| `output_schema_id` | Yes | Expected output schema such as `structured-document-v1`. |
| `citation_required` | Yes | Whether CX expects citation-capable output. |
| `tenant_or_workspace_ref` | No | Safe workspace/tenant reference for routing policy and audit. |
| `data_classification` | No | Classification label if policy requires route filtering. |

MO may persist metadata for audit and metrics, but it must not interpret
citations, validate templates, fetch chunks, or render artifacts.

## Response Format

| Field | Required | Notes |
| --- | --- | --- |
| `type` | Yes | `text`, `json_object`, or `json_schema`. |
| `schema_id` | Required for schema output | Stable schema ID from CX. |
| `json_schema` | Required for schema output | JSON Schema payload or schema reference. |
| `strict` | No | Whether provider must follow schema strictly when supported. |

MO should validate the requested response format against deployment capability
before dispatching to a provider adapter.

## Generation Provider Response

MO returns raw resource JSON for a completed synchronous generation. Queued or
long-running requests may return `202 Accepted` with a job resource.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `mo_generation_id` | Yes | MO | Stable MO request/execution ID. |
| `job_id` | No | MO | Present for async or streaming jobs. |
| `alias` | Yes | MO | Resolved logical alias. |
| `model_revision` | Yes | MO | Actual model revision used. |
| `deployment_id` | Yes | MO | Deployment selected by routing/admission. |
| `provider_type` | Yes | MO | Runtime adapter type such as `vllm-generation`. |
| `output` | No | Provider/MO | Text or structured object when completed. |
| `finish_reason` | No | Provider/MO | `STOP`, `LENGTH`, `TIMEOUT`, `CANCELLED`, `ERROR`, or provider-specific mapped value. |
| `usage` | No | Provider/MO | Token counts and optional billing/cost fields. |
| `runtime_metadata` | Yes | MO | Queue, provider latency, route, and admission metadata. |
| `created_at` / `updated_at` | Yes | MO | RFC3339 UTC timestamps. |

## Runtime Metadata

| Field | Required | Notes |
| --- | --- | --- |
| `request_id` | Yes | MO request ID. |
| `trace_id` | Yes | Propagated trace ID. |
| `queue_ms` | Yes | Time spent in MO admission/queue. |
| `provider_ms` | Yes when provider called | Provider runtime latency. |
| `total_ms` | Yes | End-to-end MO handling time. |
| `route_id` | No | Selected route/policy ID. |
| `admission_decision` | Yes | `ACCEPTED`, `QUEUED`, `REJECTED`, or `THROTTLED`. |
| `provider_request_id` | No | Provider-native request ID when available. |
| `stream_event_count` | No | Count of emitted stream events. |

## Usage Object

| Field | Required | Notes |
| --- | --- | --- |
| `input_tokens` | Yes when available | Prompt/message token count. |
| `output_tokens` | Yes when available | Generated token count. |
| `total_tokens` | Yes when available | Sum or provider-reported total. |
| `cached_tokens` | No | Provider cache/KV-cache metadata when exposed safely. |
| `tokens_per_second` | No | Runtime throughput estimate. |

CX stores `usage` in its generation execution record and returns safe metadata
to AE for user-facing history and AG for operations.

## Streaming Events

`POST /api/v1/generations/stream` uses event semantics that keep job state,
stage, and event type separate.

| Field | Required | Notes |
| --- | --- | --- |
| `event_type` | Yes | `STATUS`, `ADMISSION`, `STREAM_STARTED`, `TOKEN_CHUNK`, `USAGE`, `FINAL`, or `ERROR`. |
| `job_status` | Yes | Common `job_status`, such as `QUEUED`, `RUNNING`, `COMPLETED`, or `FAILED`. |
| `current_stage` | Yes | `ADMISSION_WAITING`, `PREPARING`, `GENERATING`, or `FINALIZING`. |
| `sequence_no` | Yes | Monotonic stream sequence number. |
| `data` | Yes | Event-specific payload. |
| `trace_id` | Yes | Trace continuity. |

CX maps MO stream events into CX generation progress. AE should observe progress
through CX, not directly through MO.

## Idempotency And Replay

- `Idempotency-Key` is required for CX-to-MO generation create requests.
- Same key plus same `provider_prompt_package_hash` and request hash returns the
  same `mo_generation_id` or `job_id`.
- Same key plus different request hash returns `409 Conflict`.
- MO stores a `mo_generation_request_hash` over the normalized request.
- CX stores `mo_generation_id`, `job_id`, route metadata, and usage metadata in
  the CX generation execution record.

## Admission And Routing

| Concern | Rule |
| --- | --- |
| Alias resolution | MO resolves `alias` to an active deployment. |
| Capability check | Deployment must support requested `provider_capability` and `response_format`. |
| Bounds check | MO clamps or rejects unsafe `max_output_tokens`, `temperature`, `top_p`, and timeout values. |
| Workload policy | Interactive, document, and batch workloads can have different queue/admission rules. |
| Route privacy | MO returns alias, model revision, deployment ID, and route ID; it never exposes provider URL or model file path to CX. |

## Error Cases

| Case | HTTP Status | Error Code |
| --- | --- | --- |
| Missing service auth | `401` or `403` | `auth.service_claim_invalid` |
| Unknown alias | `404` | `mo.alias_not_found` |
| No active deployment | `503` | `mo.deployment_unavailable` |
| Capability mismatch | `422` | `mo.capability_not_supported` |
| Response format unsupported | `422` | `mo.response_format_not_supported` |
| Admission throttled | `429` | `mo.admission_throttled` |
| Parameter outside policy | `422` | `mo.generation_parameter_out_of_bounds` |
| Provider timeout | `504` | `mo.provider_timeout` |
| Provider runtime failure | `503` | `mo.provider_runtime_failed` |
| Idempotency conflict | `409` | `IDEMPOTENCY_KEY_CONFLICT` |

All errors use `application/problem+json` and include `request_id`, `trace_id`,
`retryable`, safe route metadata when available, and no raw prompt body.

## Guardrails

| Guardrail | Rule |
| --- | --- |
| No provider direct access | CX calls MO stable API, not provider ports or vLLM URLs. |
| No document semantics in MO | MO does not select evidence, interpret citations, validate templates, or render artifacts. |
| No raw source corpus dump | CX sends resolved prompt/messages and safe metadata, not a private copied corpus package. |
| No hidden route mutation | Alias resolution, route ID, model revision, and deployment ID are returned for lineage. |
| No leaked runtime secret | MO never returns provider credentials, raw model paths, or internal host secrets. |
| No lost usage metadata | Token, latency, finish, queue, and provider metadata flow back to CX. |

## Contract Tests To Derive

- CX generation request includes `request_schema_version`, `client_request_id`,
  `trace_id`, `cx_generation_id`, `provider_prompt_package_hash`, `alias`,
  `workload_class`, `generation_profile`, and `metadata`.
- MO rejects unknown alias and unsupported capability with stable problem codes.
- MO rejects raw provider URL, model path, or provider-native endpoint fields if
  CX sends them.
- Same idempotency key and same prompt package hash returns the same
  `mo_generation_id` or `job_id`; different hash returns `409`.
- Response includes alias, model revision, deployment ID, provider type,
  runtime metadata, and timestamps.
- Usage object reports input/output/total tokens when provider supplies them.
- Streaming events keep `event_type`, `job_status`, and `current_stage`
  separate.
- CX never exposes MO stream directly to AE; CX maps it to CX generation
  progress.

## Next Inputs

This contract should feed:

- CX generation execution record and lineage contract, starting from
  [CX Generation Execution Record + Lineage Contract](./archive/planning/18_cx_generation_execution_record_lineage_contract.md).
- Structured draft and citation validation schema, starting from
  [Structured Draft + Citation Schema Contract](./archive/planning/19_structured_draft_citation_schema_contract.md).
- MO provider route and admission policy schema.
- AG provider/generation operations dashboard requirements.
- OA service scope catalog for `cx:generation.run` and `mo:generation`.
