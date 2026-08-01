# NeX-Platform MVP SRS v0.1 Assembly

Status: Draft assembly for Slice 439.

Sources:

- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)
- [MVP SRS Skeleton](./archive/planning/02_mvp_srs_skeleton.md)
- [2-Week MVP Capability Map](10_2week_mvp_capability_map.md)
- [Common Contract Freeze Candidate Map](11_common_contract_freeze_candidate_map.md)
- [Service Boundary Decision Record](12_service_boundary_decision_record.md)
- [Generation E2E Acceptance + Contract Test Plan](28_generation_e2e_acceptance_contract_test_plan.md)

This document assembles the first NeX-Platform MVP SRS from the distilled PCX
lessons, source-material review, service boundary decisions, and generation
contracts. It is intentionally smaller than the full platform vision. Its job is
to make the first buildable platform baseline clear enough for service-specific
requirements, contract schemas, and implementation backlog work.

## 1. Purpose

NeX-Platform MVP must prove that enterprise document intelligence can be split
into durable services without losing the working vertical flow proven by
NeX-PCX:

```text
authenticate
-> upload documents
-> extract and chunk text
-> build retrieval indexes
-> search permitted evidence
-> generate grounded answer or document
-> render/download artifact
-> observe health, readiness, audit, and provider usage
```

The MVP is not a full enterprise suite. It is the minimum reliable service spine
for future NeX-CX, NeX-AE, NeX-MO, NeX-OA, and NeX-AG expansion.

## 2. Scope

| Scope Area | MVP Decision |
| --- | --- |
| Service spine | Build `nex-oa`, `nex-ag`, `nex-ae-web`, `nex-ae-api`, `nex-cx`, and `nex-mo` as separately owned services. |
| User entry | Users enter through AE web/API only. Users do not call CX or MO directly. |
| Content | CX owns source files, extraction artifacts, chunks, BM25 terms, embeddings, source anchors, retrieval packages, and generated evidence lineage. |
| Model operations | MO owns provider aliases, routes, health, readiness, generation/embedding/reranking execution metadata, and runtime metrics. |
| Auth | OA owns user identity, sessions, service identity, token/API key policy, permission claims, and trust boundary. |
| Admin | AG owns governance views, readiness, audit, policy surface, and operational evidence. |
| Generation | AE orchestrates user intent/template/final UX; CX mediates document-grounded generation; MO executes provider calls. |
| Testing | Mock-first E2E and contract tests are required before live DGX/vLLM smoke is treated as release evidence. |

## 3. MVP Users

| User | MVP Need |
| --- | --- |
| General employee | Search permitted documents and ask grounded questions through a chat workspace. |
| Document contributor | Upload supported files and see ingestion progress or failure. |
| Team lead | Search and generate within team-visible document scope. |
| Operator | Check service readiness, queue state, provider health, vLLM metrics, and recent failures. |
| Administrator | Review audit evidence, policy state, provider configuration, and generated artifact lineage. |
| Service actor | Call another service with OA-issued service claims and traceable scopes. |

## 4. Functional Requirements

### 4.1 NeX-OA

| ID | Requirement | Priority |
| --- | --- | --- |
| `OA-FR-001` | Provide signup/login/password-change or equivalent bootstrap identity flow for MVP users. | Must |
| `OA-FR-002` | Issue and validate user access tokens and service-to-service claims. | Must |
| `OA-FR-003` | Provide JWKS or introspection endpoint for service claim validation. | Must |
| `OA-FR-004` | Include user, group, role, scope, and service-principal claim references usable by AE, CX, MO, and AG. | Must |
| `OA-FR-005` | Emit safe auth audit events for login, token validation failure, and service-auth failure. | Should |

### 4.2 NeX-CX

| ID | Requirement | Priority |
| --- | --- | --- |
| `CX-FR-001` | Register uploaded source documents with uploader, checksum, extension, visibility, and storage metadata. | Must |
| `CX-FR-002` | Extract supported document text into normalized text/Markdown artifacts with extractor metadata and warnings. | Must |
| `CX-FR-003` | Chunk extracted text using an active chunk policy and preserve source anchors plus previous/next chunk links. | Must |
| `CX-FR-004` | Maintain BM25 and embedding indexes with tokenizer/model/chunk-policy freshness metadata. | Must |
| `CX-FR-005` | Provide permission-filtered retrieval APIs with score metadata, source context, confidence, and no-answer signals. | Must |
| `CX-FR-006` | Create retrieval context packages that AE can reference for grounded generation. | Must |
| `CX-FR-007` | Validate AE-to-CX generation request compatibility, evidence, quality policy, and output schema before MO execution. | Must |
| `CX-FR-008` | Store generation execution records, prompt package hashes, structured drafts, citations, validation results, and recovery lineage. | Must |

### 4.3 NeX-MO

| ID | Requirement | Priority |
| --- | --- | --- |
| `MO-FR-001` | Manage provider registry entries and capability aliases for embedding, reranking, and generation. | Must |
| `MO-FR-002` | Execute provider requests by alias/capability, not by caller-supplied raw endpoint fields. | Must |
| `MO-FR-003` | Expose provider health, readiness, route status, runtime usage, latency, and failure metadata. | Must |
| `MO-FR-004` | Support mock provider mode for deterministic CI and live provider smoke for protected environments. | Must |
| `MO-FR-005` | Capture vLLM and provider resource metrics when the runtime exposes them. | Should |

### 4.4 NeX-AE API

| ID | Requirement | Priority |
| --- | --- | --- |
| `AEAPI-FR-001` | Own chat documents, interactions, workspace state, runtime defaults, and activity history. | Must |
| `AEAPI-FR-002` | Select user intent, execution mode, template, prompt contract, output contract, and quality policy. | Must |
| `AEAPI-FR-003` | Request retrieval context packages from CX and submit generation request packages to CX. | Must |
| `AEAPI-FR-004` | Create generated artifact records, versions, render jobs, files, preview routes, and download routes. | Must |
| `AEAPI-FR-005` | Attach artifact cards, quality badges, source links, progress state, and recovery actions to chat messages. | Must |
| `AEAPI-FR-006` | Recheck actor permission before preview or download. | Must |

### 4.5 NeX-AE Web

| ID | Requirement | Priority |
| --- | --- | --- |
| `AEWEB-FR-001` | Provide Korean-default, English-ready workspace UI. | Must |
| `AEWEB-FR-002` | Provide chat-style prompt input with mode/template/runtime controls. | Must |
| `AEWEB-FR-003` | Show upload, ingestion, search, generation, rendering, and recovery progress. | Must |
| `AEWEB-FR-004` | Show search evidence, citations, source context, generated answers, artifact previews, and downloads. | Must |
| `AEWEB-FR-005` | Show low-confidence/no-answer/citation/completeness warnings without hiding them behind polished output. | Must |

### 4.6 NeX-AG

| ID | Requirement | Priority |
| --- | --- | --- |
| `AG-FR-001` | Show service health, readiness, version, recent failures, queue state, and provider readiness. | Must |
| `AG-FR-002` | Provide read-only generation and artifact audit dashboard through service APIs. | Must |
| `AG-FR-003` | Show generation timeline, artifact lineage, citations, compatibility decisions, downloads, provider usage, and recovery events. | Must |
| `AG-FR-004` | Support operator notes and redacted evidence export in AG-owned projection records. | Should |
| `AG-FR-005` | Preserve redaction boundaries for prompts, secrets, provider paths, raw source documents, and unauthorized artifacts. | Must |

## 5. Cross-Service Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| `PLAT-FR-001` | Every backend service exposes `/health`, `/ready`, and `/version`. | Must |
| `PLAT-FR-002` | Services communicate through APIs with OA-validated user/service claims, not shared tables. | Must |
| `PLAT-FR-003` | Mutating create/control APIs support idempotency keys and request correlation. | Must |
| `PLAT-FR-004` | API errors use `application/problem+json` with stable code, retryability, request ID, and trace ID. | Must |
| `PLAT-FR-005` | Long-running work exposes common job status, current stage, progress mode, events, and retryability. | Must |
| `PLAT-FR-006` | Public and AG APIs must redact secrets, provider host details, raw prompts, raw source documents, and filesystem paths. | Must |

## 6. MVP Vertical Acceptance

The MVP is accepted when:

1. A user authenticates through AE using OA-backed claims.
2. A user uploads a supported document through AE and CX registers it.
3. CX extracts text, chunks it, builds BM25 and embedding readiness, and exposes
   progress.
4. A user searches permitted corpus scope and receives evidence plus source
   context.
5. AE submits a grounded generation request to CX using a retrieval package and
   explicit compatibility rule.
6. CX calls MO by provider alias, validates the result, and stores generation
   lineage.
7. AE renders a generated artifact and attaches preview/download links to chat.
8. AG can trace the same flow through service APIs with redacted evidence.
9. Mock-first E2E scenarios pass before live provider evidence is considered.

## 7. Non-Functional Requirements

| Area | Requirement |
| --- | --- |
| Security | OA-issued claims define user and service trust. Services reject unverifiable claims. |
| Ownership | Each service owns its data and rejects writes outside its boundary. |
| Observability | Logs, audit events, progress events, readiness, and provider metrics carry request/trace IDs. |
| Reproducibility | Search and generation preserve profile, policy, prompt, template, provider, schema, and hash metadata. |
| Korean readiness | Korean UI is default; Korean retrieval tokenizer can use fallback if preferred dependency is unavailable. |
| Operability | Operators can distinguish unhealthy services, degraded providers, failed jobs, stale queues, and blocked generation. |
| Testability | Mock providers and deterministic fixtures must cover the end-to-end generation spine. |

## 8. Explicit Deferrals

| Deferred Area | Reason |
| --- | --- |
| GraphDB as primary retrieval | Useful later, but outside the first 2-week MVP. |
| Autonomous multi-agent workflows | AE orchestration is bounded to intent/routing/package/rendering first. |
| Advanced provider failover/ensemble | Start with one active provider per capability and stable aliases. |
| Host lifecycle control UI | AG observes first; start/stop/restart control can follow after service spine stabilizes. |
| Complex RBAC/org chart | OA claims support hooks first; rich org governance can follow. |
| Full template authoring suite | Start with selected template contracts and artifact rendering. |
| Committing raw source-material files | Keep large/private source docs outside committed documentation by default. |

## 9. Open Items

| Topic | Decision Needed |
| --- | --- |
| Repository strategy | Confirm monorepo or multi-repo layout for first implementation. |
| Schema package location | Decide where JSON Schema and OpenAPI files live and how services consume them. |
| Live provider gate | Decide when DGX/vLLM smoke is required versus optional protected evidence. |
| License policy | Clarify MVP license check depth and AG/OA ownership split. |
| First UI scope | Confirm whether chat-first UI starts before or after CX/MO mock service bootstraps. |

## 10. Next Inputs

This SRS assembly should feed:

- Service-specific requirement partition, starting from
  [Service-Specific Requirement Partition](30_service_specific_requirement_partition.md).
- Cross-service traceability matrix, starting from
  [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md).
- Development environment freeze, starting from
  [Platform Development Environment Freeze](32_platform_development_environment_freeze.md).
- Common schema and contract package layout, starting from
  [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md).
- Testing strategy detail, starting from
  [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md).
- Design system expansion, starting from
  [Design System v0.1 Expansion](35_design_system_v0_1_expansion.md).
- First implementation roadmap and sprint backlog, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
