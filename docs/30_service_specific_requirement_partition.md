# Service-Specific Requirement Partition

Status: Draft seed for Slice 440.

Sources:

- [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md)
- [Service Boundary Decision Record](12_service_boundary_decision_record.md)
- [2-Week MVP Capability Map](10_2week_mvp_capability_map.md)
- [Common Contract Freeze Candidate Map](11_common_contract_freeze_candidate_map.md)
- [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md)

This document partitions the assembled MVP SRS into service-owned requirement
sets. The goal is to prevent implementation tickets from mixing ownership across
AE, CX, MO, OA, and AG while keeping cross-service dependencies visible.

## Requirement ID Rules

| Prefix | Owner | Meaning |
| --- | --- | --- |
| `OA-FR-*` | `nex-oa` | Identity, auth, service claims, token/session/API key, permission claim requirements. |
| `CX-FR-*` | `nex-cx` | Content lifecycle, extraction, chunking, indexing, retrieval, evidence, grounded generation lineage. |
| `MO-FR-*` | `nex-mo` | Provider aliases, model execution, route readiness, runtime usage, metrics. |
| `AEAPI-FR-*` | `nex-ae-api` | Chat workspace API, intent routing, orchestration, artifact metadata, render coordination. |
| `AEWEB-FR-*` | `nex-ae-web` | Korean-default user workspace, chat UX, upload/search/generation/artifact UI. |
| `AG-FR-*` | `nex-ag` | Admin/governance views, audit, readiness, policy, operator evidence. |
| `PLAT-FR-*` | Shared contract | Cross-service API, job, error, trace, redaction, schema, and test behavior. |
| `NFR-*` | Shared quality | Security, observability, reproducibility, performance, localization, operability. |

Requirement IDs are stable planning identifiers. Service repositories can create
implementation ticket IDs separately, but should reference these IDs.

## Priority Semantics

| Priority | Meaning |
| --- | --- |
| Must | Required for the first MVP acceptance spine. |
| Should | Important for operating or demonstrating the MVP, but can be sequenced after the first vertical pass. |
| Could | Valuable extension point; do not block the first vertical pass. |
| Deferred | Explicitly out of first MVP unless a new decision changes scope. |

## NeX-OA Partition

| ID | Requirement | Interfaces | Dependencies | Priority |
| --- | --- | --- | --- | --- |
| `OA-FR-001` | Bootstrap user identity flow for MVP users. | AE auth adapter | AE web/API | Must |
| `OA-FR-002` | Issue user access tokens and service tokens. | `/api/v1/auth/login`, `/api/v1/auth/service-token` | All services | Must |
| `OA-FR-003` | Expose JWKS or introspection validation path. | `/api/v1/auth/jwks`, `/api/v1/auth/introspect` | All backend services | Must |
| `OA-FR-004` | Carry user, group, role, scope, and service-principal claim refs. | Token claims, claim refs | CX permission filter, AG audit | Must |
| `OA-FR-005` | Emit safe auth audit events. | `/api/v1/auth/audit-events` | AG | Should |

## NeX-CX Partition

| ID | Requirement | Interfaces | Dependencies | Priority |
| --- | --- | --- | --- | --- |
| `CX-FR-001` | Register uploaded source documents with checksum, extension, visibility, and storage metadata. | Upload handoff API | AE API, OA claims | Must |
| `CX-FR-002` | Extract supported documents into normalized text/Markdown artifacts. | Ingestion job APIs | Extractor registry | Must |
| `CX-FR-003` | Apply active chunk policy and preserve source anchors plus prev/next links. | Chunk repository/API | Extraction artifacts | Must |
| `CX-FR-004` | Maintain BM25 and embedding freshness metadata. | Index readiness APIs | MO embedding, tokenizer config | Must |
| `CX-FR-005` | Provide permission-filtered retrieval with scores and no-answer signals. | `/api/v1/retrieval-context-packages`, search APIs | OA claims, indexes | Must |
| `CX-FR-006` | Create retrieval context packages for AE generation. | Retrieval package API | AE API | Must |
| `CX-FR-007` | Validate generation compatibility, evidence, output schema, and policy before MO calls. | `/api/v1/generations` | AE request, schema catalog | Must |
| `CX-FR-008` | Persist generation execution, structured draft, citations, validation, and recovery lineage. | Generation read/event APIs | MO, AE | Must |

## NeX-MO Partition

| ID | Requirement | Interfaces | Dependencies | Priority |
| --- | --- | --- | --- | --- |
| `MO-FR-001` | Manage provider registry and capability aliases. | `/api/v1/provider-routes` | AG, CX | Must |
| `MO-FR-002` | Execute embedding, reranking, and generation by alias/capability. | Provider APIs | CX | Must |
| `MO-FR-003` | Expose health, readiness, route status, runtime usage, latency, and failure metadata. | Readiness/metrics APIs | AG, CX | Must |
| `MO-FR-004` | Support deterministic mock provider mode and protected live smoke mode. | Runtime profile config | Testing strategy | Must |
| `MO-FR-005` | Capture vLLM and provider resource metrics where available. | Metrics snapshot APIs | AG | Should |

## NeX-AE API Partition

| ID | Requirement | Interfaces | Dependencies | Priority |
| --- | --- | --- | --- | --- |
| `AEAPI-FR-001` | Own chat documents, interactions, workspace state, runtime defaults, and activity history. | Workspace APIs | AE web, OA | Must |
| `AEAPI-FR-002` | Select intent, execution mode, template, prompt contract, output contract, and quality policy. | Generation request facade | Template/prompt catalog | Must |
| `AEAPI-FR-003` | Orchestrate retrieval package request and CX generation request. | AE facade -> CX APIs | CX, OA | Must |
| `AEAPI-FR-004` | Own generated artifact records, versions, render jobs, files, preview routes, and downloads. | Artifact APIs | CX draft reads | Must |
| `AEAPI-FR-005` | Attach artifact links, quality badges, source links, progress, and recovery actions to chat messages. | Chat/artifact link APIs | CX/AE artifact | Must |
| `AEAPI-FR-006` | Recheck permission before preview or download. | Download API | OA claims | Must |

## NeX-AE Web Partition

| ID | Requirement | Interfaces | Dependencies | Priority |
| --- | --- | --- | --- | --- |
| `AEWEB-FR-001` | Provide Korean-default, English-ready workspace UI. | Web app | i18n tokens | Must |
| `AEWEB-FR-002` | Provide chat prompt input with mode, template, and runtime controls. | AE API | Design system | Must |
| `AEWEB-FR-003` | Show upload, ingestion, search, generation, rendering, and recovery progress. | Job/event APIs | AE/CX/MO | Must |
| `AEWEB-FR-004` | Show search evidence, citations, source context, answers, artifact previews, and downloads. | AE/CX APIs | Artifact and retrieval contracts | Must |
| `AEWEB-FR-005` | Show no-answer, low-confidence, citation, completeness, and manual warning badges. | Quality metadata | CX/AE | Must |

## NeX-AG Partition

| ID | Requirement | Interfaces | Dependencies | Priority |
| --- | --- | --- | --- | --- |
| `AG-FR-001` | Show health, readiness, version, failures, queue state, and provider readiness. | Admin dashboards | All services | Must |
| `AG-FR-002` | Provide read-only generation and artifact audit dashboard. | `/admin/v1/generation-audit/*` | AE/CX/MO/OA | Must |
| `AG-FR-003` | Show timeline, lineage, citation, compatibility, download, provider usage, and recovery summaries. | Audit read APIs | AE/CX/MO/OA | Must |
| `AG-FR-004` | Support operator notes and redacted evidence export in AG-owned projections. | AG write APIs | OA admin claims | Should |
| `AG-FR-005` | Preserve redaction boundaries for prompts, secrets, provider paths, source docs, and unauthorized artifacts. | All AG APIs | All services | Must |

## Shared Platform Partition

| ID | Requirement | Owner Style | Priority |
| --- | --- | --- |
| `PLAT-FR-001` | Every backend service exposes `/health`, `/ready`, and `/version`. | Service-local implementation, common contract. | Must |
| `PLAT-FR-002` | Services communicate by explicit APIs and OA-validated claims, not shared tables. | Architecture boundary. | Must |
| `PLAT-FR-003` | Mutating create/control APIs support idempotency keys and request correlation. | Common API behavior. | Must |
| `PLAT-FR-004` | Errors use `application/problem+json`. | Common API behavior. | Must |
| `PLAT-FR-005` | Long-running work exposes common job status, stage, progress, events, and retryability. | Common job contract. | Must |
| `PLAT-FR-006` | Public and AG APIs redact secrets, provider host details, prompts, source docs, and filesystem paths. | Security contract. | Must |
| `PLAT-FR-007` | JSON Schema and OpenAPI contract files remain versioned and contract-testable. | Common contract package. | Should |

## Cross-Service Dependency Order

| Order | Dependency | Why |
| ---: | --- | --- |
| 1 | Common service skeleton and health/version contract | Gives all services a visible spine. |
| 2 | OA claim validation path | Allows AE, CX, MO, and AG to enforce trust boundaries. |
| 3 | MO mock provider aliases | Lets CX and AE build against stable provider capabilities. |
| 4 | CX upload/extraction/chunk/index/retrieval path | Creates evidence for generation. |
| 5 | AE chat/workspace/upload/search UX | Gives users a single entry point. |
| 6 | CX-mediated generation and AE artifact path | Closes answer/document generation. |
| 7 | AG audit/readiness projections | Makes the full flow operable. |
| 8 | Live provider smoke | Confirms mock flow against DGX/vLLM runtime. |

## Partition Guardrails

- Do not assign a requirement to a service that cannot own the corresponding
  data.
- Do not hide a cross-service dependency inside one service backlog item.
- Do not allow AE or AG to call provider runtime endpoints directly.
- Do not allow MO to own document semantics or retrieval indexes.
- Do not let shared contracts become a large runtime utility package before
  service boundaries are proven.

## Next Inputs

This partition should feed:

- Cross-service traceability matrix, starting from
  [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md).
- Service-specific SRS sections.
- First sprint implementation backlog, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
- Contract test ownership map.
