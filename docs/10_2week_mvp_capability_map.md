# 2-Week MVP Capability Distillation + Service Map

Status: Draft seed for Slice 420.

Source: `NP-SRC-13`
(`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`).

This document distills the uploaded 2-week barebone SRS into a service-owned MVP
capability map. It does not copy the source document wholesale. It converts the
source into a smaller planning artifact that can feed the first NeX-Platform SRS
draft and backlog.

## Distillation Rule

`NP-SRC-13` is the first scope gate, but it is still ambitious. For platform
planning, each item is classified as:

| Classification | Meaning |
| --- | --- |
| MVP Core | Required for the first useful end-to-end platform baseline. |
| MVP Stretch | Valuable in the 2-week baseline, but dependent on external readiness, team capacity, or unresolved architecture choices. |
| Deferred | Explicitly outside the first build or too broad for the first baseline. |
| Boundary Review | Source intent is useful, but ownership must be reconciled with the user-confirmed service boundary. |

## Source Vertical Flow

`NP-SRC-13` defines the first vertical flow as:

```text
login
-> file upload
-> text extraction, chunking, BM25, embedding
-> hybrid search and reranking
-> LLM generation using evidence
-> result preview
-> Markdown artifact download
-> admin view of 5-service health/license status
```

Distilled MVP goal:

```text
User can authenticate, upload one or more supported documents, see ingestion
progress, search grounded evidence, generate a citation-ready answer or draft,
download a Markdown artifact, and an operator can verify the 5-service spine.
```

## Boundary Alignment

`NP-SRC-13` says `NeX-CX` owns search and generation orchestration. The
user-confirmed NeX-Platform boundary is slightly different:

| Concern | Source Direction | Distilled Platform Alignment |
| --- | --- | --- |
| Browser calls | Browser calls NeX-AE API only. | Keep. Browser should call `nex-ae-web`/`nex-ae-api`, not `nex-cx` or `nex-mo` directly. |
| Search orchestration | `NeX-CX` owns search. | Keep for retrieval execution and evidence packaging. |
| Generation orchestration | `NeX-CX` owns generation orchestration. | Reconciled: keep user intent, template choice, final formatting, chat state, and artifact links in `nex-ae-api`; route document-grounded generation through `nex-cx`; keep provider execution in `nex-mo`. |
| Provider calls | `NeX-CX` calls `NeX-MO`. | Keep for retrieval-time embedding/reranking and document-grounded generation. Direct `nex-ae-api` to `nex-mo` generation requires a later explicit policy. |
| Admin operations | `NeX-AG` shows service/license state. | Keep, with later governance expansion. |
| Auth | `NeX-OA` owns user auth and service account token. | Keep and rename mentally as NeX Open Auth, not operations administration. |

Canonical first-call chain:

```text
Browser -> nex-ae-web -> nex-ae-api -> nex-cx -> nex-mo
```

## Service Capability Map

| Service | MVP Core | MVP Stretch | Deferred |
| --- | --- | --- | --- |
| `nex-oa` | Bootstrap admin, signup, login, password change, JWT access token, service account token, development/test license validation. | Refresh token if schedule allows. | Email verification, password reset email, complex RBAC, organization chart. |
| `nex-ag` | Admin login, 5-service health/ready/version dashboard, license status, last polling time, response time, error state. | Basic service status snapshot history. | Service start/stop/restart UI, host agent, advanced alerting, multi-host operations. |
| `nex-ae-web` | Login, signup, password change, workspace, document groups, chat documents, drag-and-drop upload, prompt input, search/generate mode, progress, preview, Markdown download. | SSE job progress. One-second polling is acceptable as a fallback while keeping the same job event contract. | Agent automation, advanced template authoring, DOCX/PPTX/PDF rendering. |
| `nex-ae-api` | Auth flow adapter to `nex-oa`, workspace API, interaction/activity persistence, attachment/artifact metadata, calls to `nex-cx`, result shaping. | Template-aware generation request packaging. | Domain agent, tool calling, autonomous routines. |
| `nex-cx` | Upload registration, content object/version, extraction registry, active extractor selection, normalized Markdown/text, active chunk policy, prev/next chunk links, BM25, vector search, hybrid retrieval, evidence package. | HWP/HWPX through Kordoc MCP if runtime is already ready; MeCab tokenizer if dependency is settled. | GraphDB, retention/archive automation, advanced backup UI, Kordoc compare/fill features. |
| `nex-mo` | Provider registry, capability aliases, active provider per capability, embedding API, reranking API, generation API, health/ready/version, timeout, usage metadata. | Live DGX provider smoke and health evidence in the first demo. | Automatic provider routing/failover, ensemble providers, model revision/deployment lifecycle. |
| Shared | Per-service database/user separation, no cross-service foreign keys, health/ready/version, request id, traceparent, idempotency key, problem+json errors, common job state. | Monorepo common package if it reduces duplicate contract work. | Large shared utility framework before contracts stabilize. |

## Data Ownership Map

| Data | Owner | Notes |
| --- | --- | --- |
| Users, credentials, service accounts, auth events, license | `nex-oa` | AE stores no password or credential records. |
| Service definitions, status snapshots, admin actions | `nex-ag` | AG reads service state through APIs. |
| Document groups, chat documents, interactions, activities, attachments, artifacts | `nex-ae-api` | User workspace state and downloadable artifact metadata. |
| Content objects, versions, source assets, extractors, chunk policies, chunks, BM25 indexes, embedding profiles, segment embeddings, search evidence | `nex-cx` | No other service directly writes CX-owned storage. |
| Providers, aliases, provider requests, activation events | `nex-mo` | CX and AE should reference aliases or route IDs, not implementation-specific process details. |
| Jobs, job events, workers | Service-local or shared contract | Each service may own its own job tables, but the state model should be canonical. |

## MVP API Map

| Service | Core API Families |
| --- | --- |
| `nex-oa` | `/api/v1/auth/signup`, `/api/v1/auth/login`, `/api/v1/auth/change-password`, `/api/v1/auth/service-token`, `/api/v1/auth/me`, `/admin/v1/licenses/current`, `/health`, `/ready`, `/version`. |
| `nex-ag` | `/admin/v1/services`, `/admin/v1/services/status`, `/admin/v1/license`, `/health`, `/ready`, `/version`. |
| `nex-ae-api` | Workspace, document group, chat document, interaction, upload attachment, artifact download, and job event proxy APIs. |
| `nex-cx` | `/api/v1/documents/uploads`, `/api/v1/jobs/{job_id}`, `/api/v1/jobs/{job_id}/events`, `/api/v1/search`, `/api/v1/generations`, `/api/v1/structured-drafts/{draft_id}`, extractor/chunk policy admin APIs, `/health`, `/ready`, `/version`. |
| `nex-mo` | `/api/v1/embeddings`, `/api/v1/rerankings`, `/api/v1/generations`, `/admin/v1/providers`, `/admin/v1/providers/{provider_id}/activate`, `/health`, `/ready`, `/version`. |

## Capability Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Keep 5-service spine from the first baseline. | MVP Core | The platform is meant to split PCX responsibilities into durable services. |
| Keep service-owned databases and users. | MVP Core | Prevents early coupling and cross-service table ownership. |
| Keep browser calls behind AE. | MVP Core | Gives one UX/API boundary for users and reduces exposed internal service surface. |
| Use `heading_1000_100` as the first active chunk policy. | MVP Core | Matches PCX experience and source SRS. |
| Preserve chunk `prev_chunk_id` and `next_chunk_id`. | MVP Core | Supports source context expansion and later generation quality. |
| Use Qwen3 embedding 2560, Qwen3 reranker, and Qwen LLM as default provider aliases. | MVP Core | Matches PCX direction and source SRS, but implementation should call aliases. |
| Treat MeCab BM25 as preferred Korean tokenizer, with fallback if installation blocks MVP. | MVP Stretch | The tokenizer improves Korean retrieval, but dependency/runtime readiness can block the 2-week schedule. |
| Treat HWP/HWPX Kordoc MCP as stretch unless runtime is ready before CX extraction work starts. | MVP Stretch | Valuable for Korean enterprise documents, but external process integration is a schedule risk. |
| Keep document-grounded generation CX-mediated. | MVP Core | AE API acts as the agent/orchestrator and final UX owner, but CX connects evidence, prompt package, generation record, and MO provider usage. |
| Defer GraphDB. | Deferred | Source explicitly excludes GraphDB from the barebone. |
| Defer provider failover and ensemble. | Deferred | Useful later, but the MVP needs one active provider per capability. |
| Defer service lifecycle UI and host agent. | Deferred | AG dashboard is MVP; start/stop/restart control can follow after the service spine proves stable. |

## First Acceptance Scenario

1. Services `nex-oa`, `nex-ag`, `nex-ae`, `nex-cx`, and `nex-mo` expose
   `/health`, `/ready`, and `/version`.
2. A user signs up, logs in, and changes a password through AE using OA-owned
   credentials.
3. The user creates a document group and chat document.
4. The user uploads a supported file and sees job progress.
5. CX extracts text, chunks with `heading_1000_100`, stores prev/next links,
   refreshes BM25, stores embedding vectors, and marks ingestion ready.
6. The user runs search and sees evidence with source context.
7. The user runs generation using evidence and sees a preview.
8. The user downloads a Markdown artifact.
9. AG shows 5-service health/ready/version and license status.
10. Regression passes with statement coverage target 95% and branch coverage
    target 85%, or a written exception is recorded for the first baseline.

## 2-Week Sequence

| Window | Distilled Work |
| --- | --- |
| Day 1 | Repository structure, PostgreSQL profiles, common contracts, health/ready/version. |
| Day 2-3 | OA signup/login/password/service-token/license minimum. |
| Day 3-4 | AG dashboard and license/status read path. |
| Day 4-6 | MO provider registry, aliases, embedding/reranking/generation facade. |
| Day 5-8 | CX extraction/chunk/BM25/vector/evidence path with active registries. |
| Day 7-10 | AE web/API workspace, upload, prompt modes, progress, preview. |
| Day 10-12 | Generation flow, structured draft, Markdown artifact. |
| Day 12-13 | E2E, error handling, progress behavior, authentication chain. |
| Day 14 | Regression, coverage, demo, documentation cleanup. |

## Next Inputs

This map should feed:

- NeX-Platform MVP SRS v0.1, assembled in
  [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md).
- NeX-PCX evidence index.
- Common contract freeze candidate map.
- Service boundary conflict review, especially `nex-oa` and generation ownership.
