# Common Modules Skeleton

Status: Draft bootstrap.

Common modules should be defined by stable cross-service contracts, not by early
code sharing. Start with shared schemas and error behavior; delay reusable
packages until service boundaries have survived implementation.

## Candidate Common Contracts

| Module | Purpose | Consumers |
| --- | --- | --- |
| Config | Environment parsing, profile selection, default values, secret references. | All services |
| Error envelope | Consistent API errors with code, message, retryability, and correlation id. | All services |
| Logging | Structured event fields, retention hints, severity, service name, actor. | All services |
| Audit event | Actor/action/target/result/event metadata for governance review. | All services, `nex-ag` |
| Auth claims | User id, groups, roles, scopes, service principal, trust boundary. | All services, `nex-oa` |
| Service identity | Service-to-service authentication and API key metadata. | All backend services |
| Health/readiness | Liveness, dependency readiness, degraded reason, last check time. | `nex-mo`, `nex-ag`, all services |
| Provider contract | Embedding, reranker, generation request/response and runtime metadata. | `nex-mo`, `nex-cx` |
| Retrieval package | Query, profiles, chunks, scores, source anchors, no-answer evidence. | `nex-cx`, `nex-ae-api` |
| Agent orchestration package | Intent, execution mode, generation policy package, retrieval package reference, job stage, and result lineage. | `nex-ae-api`, `nex-ae-web` |
| Generation routing contract | AE-owned user intent, CX-mediated document generation, MO provider execution, and returned usage lineage. | `nex-ae-api`, `nex-cx`, `nex-mo` |
| AE-to-CX generation request package | Template, prompt contract, retrieval package reference, output contract, quality policy, and bounded generation parameters. | `nex-ae-api`, `nex-cx` |
| CX-to-MO generation provider contract | Alias, workload class, provider-facing prompt package hash, response format, admission, streaming, usage, and runtime metadata. | `nex-cx`, `nex-mo` |
| CX generation execution record | Retrieval package hash, prompt package hash, MO call metadata, draft validation, citation validation, and retry lineage. | `nex-cx`, `nex-ae-api`, `nex-ag` |
| Structured draft and citation schema | Sections, blocks, citation claims, source anchors, validation statuses, completeness checks, and safe read shape. | `nex-cx`, `nex-ae-api`, `nex-ag` |
| AE artifact rendering handoff contract | Generated artifact records, versions, render jobs, rendered files, preview/download links, and CX source lineage refs. | `nex-ae-api`, `nex-ae-web`, `nex-ag` |
| Generation progress event contract | Event envelope, event types, current stages, common job status, streaming/polling semantics, and redacted progress metadata. | `nex-ae-api`, `nex-ae-web`, `nex-cx`, `nex-mo`, `nex-ag` |
| Generation failure and repair policy | Failure classes, retryability, repair/regenerate actions, lineage edges, policy hashes, and user-facing recovery behavior. | `nex-ae-api`, `nex-cx`, `nex-mo`, `nex-ag` |
| Chat workspace artifact link requirements | Artifact cards, preview/download routes, source drilldown, quality badges, recovery actions, localization, and accessibility requirements. | `nex-ae-web`, `nex-ae-api` |
| Prompt/template/output compatibility matrix | Valid combinations of execution mode, template, prompt contract, output schema, artifact intent, target format, quality policy, and provider capability. | `nex-ae-api`, `nex-cx`, `nex-mo`, `nex-ag` |
| AG generation artifact audit requirements | Read-only dashboard views, filters, redaction, audit event projections, operator notes, and export requirements for generation and artifacts. | `nex-ag`, all services |
| Generation contract JSON schema seed | Versioned schema catalog, shared definitions, validation rules, and schema-to-contract traceability for generation payloads. | All backend services, `nex-ae-web` |
| Generation OpenAPI endpoint seed | Service-owned route map, headers, status codes, schemas, streaming/polling endpoints, and contract-test surface. | All services |
| Generation E2E acceptance plan | Mock-first end-to-end scenarios, contract-test matrix, evidence artifacts, and MVP exit criteria. | All services |
| Feature flag | Runtime toggles for experimental providers, tokenizers, templates, policies. | All services |

## Contract Style

- Use explicit version fields for provider, retrieval, prompt, and artifact contracts.
- Include correlation ids for cross-service tracing.
- Include actor and authorization context where a user action changes state.
- Separate public API fields from internal diagnostic metadata.
- Keep JSON-compatible schemas as the first contract artifact.

## Early Guardrails

| Guardrail | Reason |
| --- | --- |
| Do not create a large shared utility package first | It can hide boundary mistakes. |
| Do not let services share private database tables | It makes ownership unclear. |
| Do not duplicate auth validation logic | `nex-oa` owns trust decisions. |
| Do not bury provider runtime state inside UI code | `nex-mo` owns provider metadata. |
| Do not store generated artifacts only in chat messages | Artifact lineage and downloads need durable records. |

## Documentation To Add Later

- JSON schema files for each shared contract, starting from
  [Common Contract Freeze Candidate Map](../../11_common_contract_freeze_candidate_map.md).
- Service owner-specific schemas and API boundaries, starting from
  [Service Boundary Decision Record](../../12_service_boundary_decision_record.md).
- Agent orchestration schemas, starting from
  [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md).
- Retrieval context package schemas, starting from
  [CX-to-AE Retrieval Context Package Contract](../../14_cx_ae_retrieval_context_package_contract.md).
- Generation routing and mediation schemas, starting from
  [Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md).
- AE-to-CX generation request schemas, starting from
  [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md).
- CX-to-MO generation provider schemas, starting from
  [CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md).
- CX generation execution and lineage schemas, starting from
  [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md).
- Structured draft and citation schemas, starting from
  [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md).
- AE artifact rendering handoff schemas, starting from
  [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md).
- Generation progress event schemas, starting from
  [Generation Progress Event Contract](21_generation_progress_event_contract.md).
- Generation failure and repair policy schemas, starting from
  [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md).
- Chat workspace artifact link requirements, starting from
  [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md).
- Prompt/template/output compatibility schemas, starting from
  [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md).
- AG generation artifact audit dashboard schemas, starting from
  [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md).
- Generation JSON Schema catalog, starting from
  [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md).
- Generation OpenAPI endpoint seed, starting from
  [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md).
- Generation E2E acceptance and contract test plan, starting from
  [Generation E2E Acceptance + Contract Test Plan](../../28_generation_e2e_acceptance_contract_test_plan.md).
- Error code catalog.
- Claim and scope catalog.
- Audit event taxonomy.
- OpenAPI generation strategy.
- Version compatibility policy.
