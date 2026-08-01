# MVP SRS Skeleton

Status: Draft bootstrap.

This skeleton seeded the first NeX-Platform SRS. The assembled v0.1 draft now
lives in [NeX-Platform MVP SRS v0.1 Assembly](../../29_nex_platform_mvp_srs_v0_1_assembly.md).
Keep this file as the compact outline and update the assembled SRS for
service-specific implementation planning.

## 1. Introduction

### 1.1 Purpose

Define the minimum NeX-Platform capability needed to upload enterprise
documents, retrieve grounded context, generate citation-aware answers or
documents, and operate the model/provider layer with visible readiness.

### 1.2 Scope

The MVP includes the platform spine:

- `nex-cx` document repository and retrieval API.
- `nex-ae-web` user-facing workspace.
- `nex-ae-api` agent orchestration backend.
- `nex-mo` model provider routing and monitoring.
- `nex-oa` identity and service-auth boundary.
- `nex-ag` admin & governance surface.

### 1.3 Source Inputs

- NeX-PCX SRS and slice history.
- NeX-PCX implemented features and regression evidence.
- 400,000-token design document, after distillation.
- Reduced 2-week MVP document.
- User-confirmed service boundary definitions.

## 2. Users and Roles

| Role | MVP Need |
| --- | --- |
| General employee | Upload or search permitted documents and ask grounded questions. |
| Team lead | Search within team-visible data and review generated outputs. |
| Operator | Check service readiness, provider health, logs, and queue status. |
| Administrator | Manage policies, templates, provider routes, and audit evidence. |
| Service actor | Authenticate service-to-service calls with claims and API keys. |

## 3. Functional Requirement Skeleton

| ID | Requirement | Owner | MVP |
| --- | --- | --- | --- |
| FR-CX-001 | Store original files, extraction artifacts, chunks, embeddings, BM25 terms, graph metadata, and source anchors. | `nex-cx` | Yes |
| FR-CX-002 | Provide retrieval APIs that return ranked chunks, score metadata, source context, and no-answer signals. | `nex-cx` | Yes |
| FR-AE-001 | Provide chat-style UX for direct questions, document-grounded answers, summaries, reports, and artifacts. | `nex-ae-web` | Yes |
| FR-AE-002 | Route user intent and compose retrieval context, prompt packages, provider requests, final formatting, artifact links, and chat workspace responses. | `nex-ae-api` | Yes |
| FR-MO-001 | Manage embedding, reranker, and generation provider routes with health and runtime metrics. | `nex-mo` | Yes |
| FR-OA-001 | Issue and validate user, session, token, API key, service identity, and permission claims. | `nex-oa` | Yes |
| FR-AG-001 | Provide admin & governance views for logs, policies, readiness, monitoring, and audit trails. | `nex-ag` | Yes |

## 4. Data Requirement Skeleton

| Domain | Minimum Data |
| --- | --- |
| Source document | File identity, uploader, upload time, checksum, extension, visibility, storage location. |
| Extraction artifact | Extractor id, version, text/Markdown path, blocks, warnings, quality metadata. |
| Chunk | Chunk policy, text, source anchor, previous/next chunk, token estimate, source block relation. |
| Retrieval index | Embedding profile, vector dimension, BM25 tokenizer, graph relation, freshness metadata. |
| Generation | Prompt version, template version, retrieval package hash, answer, citations, quality metadata. |
| Auth | User, group, service principal, scopes, claims, token/session/API key metadata. |
| Operations | Log event, audit event, readiness snapshot, provider metric, queue state. |

## 5. Non-Functional Requirement Skeleton

| Area | MVP Requirement |
| --- | --- |
| Security | No service trusts caller-supplied identity without `nex-oa` validation. |
| Observability | Critical actions emit logs, audit events, correlation ids, and readiness snapshots. |
| Reproducibility | Search and generation runs preserve profile, policy, prompt, template, and provider metadata. |
| Extensibility | Provider and extractor contracts allow additional models and file formats. |
| Performance | Long-running ingestion and generation must expose progress or queued status. |
| Localization | Korean UI is default; English labels are supported through i18n-ready keys. |

## 6. Acceptance Criteria Skeleton

- A user can upload a document, wait for ingestion, search it, and generate a grounded answer.
- A user can produce a generated artifact with citations and export it.
- An operator can see provider readiness, vLLM metrics, queue backlog, and recent failures.
- An administrator can inspect logs, audit trails, and essential policy settings.
- A service-to-service call can be accepted or rejected based on explicit claims.
- Regression testing reports statement coverage and branch coverage separately.
