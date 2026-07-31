# Service Boundary Decision Record + Ownership Freeze Candidate

Status: Draft seed for Slice 422.

Sources:

- `NP-SRC-07`
  (`07_260723_NeX_OA_Operations_Administration_Design_v1.2.md`)
- `NP-SRC-08`
  (`08_260723_NeX_AG_Operations_Administration_Design_v1.6.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- User-confirmed service boundary from NeX-PCX platform planning.

This decision record turns the service-specific source documents into a first
ownership map. It is intentionally stricter than several source documents where
generation, administration, and operations responsibilities overlap. The goal is
to freeze the first platform spine before writing service SRS documents.

## Decision Scope

| Classification | Meaning |
| --- | --- |
| Freeze Now | Use as an MVP boundary rule unless a later explicit decision changes it. |
| Freeze Candidate | Direction is stable, but endpoint or storage details need a follow-up contract. |
| Boundary Conflict | Source documents or older names disagree with the user-confirmed split. |
| Defer | Keep as a later platform capability, not a first MVP boundary. |

## Boundary Principles

| Principle | Decision |
| --- | --- |
| User entry point | Browser traffic enters through `nex-ae-web` and `nex-ae-api`; users do not call `nex-cx` or `nex-mo` directly. |
| Service ownership | Each service owns its database, write model, and authoritative records. |
| Cross-service access | Services communicate through explicit APIs and signed service claims, not shared tables. |
| Model access | Provider runtimes are reached through `nex-mo` stable APIs, not direct provider URLs. |
| Retrieval before generation | `nex-cx` produces retrieval context; `nex-ae-api` owns user intent/template/final response; `nex-cx` mediates document-grounded generation before `nex-mo` executes provider calls. |
| Admin visibility | `nex-ag` reads health, readiness, metrics, logs, audit, and policy status through service APIs. |
| Auth authority | `nex-oa` is NeX Open Auth, not operations administration; it owns identity and service-auth trust decisions. |

## Frozen Service Role Decisions

| Service | Freeze Now Owner | Explicit Non-Owner |
| --- | --- | --- |
| `nex-oa` | User identity, login, sessions, tokens, API keys, service accounts, service tokens, JWKS/signing keys, permission claims, auth audit/debug metadata. | Document visibility rules, retrieval ranking, model serving, provider lifecycle, admin dashboard UX. |
| `nex-ag` | Admin & governance dashboard, service registry view, readiness snapshots, logs, audit trails, policy setting surface, monitoring, operations evidence. | Identity issuing, source document storage, model inference execution, end-user chat workspace. |
| `nex-cx` | Content repository, original assets, extraction artifacts, normalized text/Markdown, chunk policy application, chunk adjacency, BM25 terms, embedding vectors, graph extension points, permission-filtered retrieval, evidence package. | User-facing chat session, prompt/template orchestration, final answer formatting, provider runtime management, auth token issuing. |
| `nex-ae-web` | Korean-default user workspace UI, chat/document group navigation, upload UX, prompt composer, result preview, artifact download shortcuts. | Business data authority, provider routing, auth/session issuance, platform governance policy. |
| `nex-ae-api` | Workspace API, chat document state, interaction/activity history, intent and mode selection, retrieval request orchestration, prompt package composition, template selection, final answer formatting, artifact metadata and export coordination. | Raw corpus storage, BM25/vector indexes, provider hosting, identity issuing, global operations policy. |
| `nex-mo` | Provider registry, capability aliases, embedding/reranker/generation provider contracts, provider health/readiness, provider metrics, vLLM metric snapshots, provider resource telemetry, admission/routing policy. | BM25, hybrid retrieval ranking, source document lifecycle, business templates, user chat UX, identity authority. |

## Canonical Call Chains

| Scenario | MVP Call Chain | Boundary Rule |
| --- | --- | --- |
| Login/session | Browser -> `nex-ae-web` -> `nex-ae-api` -> `nex-oa` | AE adapts UX; OA issues and validates identity. |
| Service authentication | Service -> `nex-oa` service-token/JWKS path -> target service | Every service validates explicit service claims. |
| Upload and ingestion | Browser -> AE -> `nex-cx` -> `nex-mo` embedding API | AE owns workspace UX; CX owns content lifecycle; MO owns model execution. |
| Search | Browser -> AE -> `nex-cx` search -> `nex-mo` embedding/reranker APIs | CX owns retrieval and evidence package. |
| Direct generation | Browser -> AE -> `nex-cx` retrieval package -> AE generation policy/template -> `nex-cx` generation API -> `nex-mo` generation API -> AE artifact | AE owns user intent and final composition; CX owns document-grounded generation execution record and evidence lineage. |
| Summary | Browser -> AE -> `nex-cx` document/evidence package -> AE summary policy -> `nex-cx` generation API -> `nex-mo` generation API | Summary is generation with a different prompt/template mode. |
| Generated artifact download | Browser -> AE artifact API | AE owns generated artifact metadata; CX stores generated output only if explicitly re-ingested as source content. |
| Operations dashboard | `nex-ag` -> service `/health`, `/ready`, `/version`, admin APIs | AG observes and governs through service APIs; it does not read service databases. |

## Cross-Service Data Authority

| Data Object | Authority | Read Consumers | Write Rule |
| --- | --- | --- | --- |
| User account, session, token, service principal | `nex-oa` | All services through claims/JWKS/introspection | Only OA writes. |
| Document group, chat document, interaction, activity | `nex-ae-api` | AE web, AG summary views | Only AE writes. |
| Uploaded source asset and extracted artifact | `nex-cx` | AE, AG | Only CX writes after AE upload handoff. |
| Chunk, BM25 term, vector, graph edge | `nex-cx` | AE, AG | Only CX writes; MO returns vectors/scores but does not store corpus indexes. |
| Retrieval context package and no-answer metadata | `nex-cx` | AE | CX writes package evidence; AE can persist run linkage. |
| Provider-facing prompt package and document-grounded generation execution record | `nex-cx` | AE, AG | CX connects evidence, prompt package, MO request metadata, structured draft, and citation lineage. |
| Structured draft, citation claims, and validation metadata | `nex-cx` | AE, AG | CX validates generated sections, blocks, evidence anchors, citations, and template completeness before AE renders artifacts. |
| User-facing generation request, answer presentation, artifact metadata, and rendered artifact files | `nex-ae-api` | AE web, AG | AE writes chat/workspace records, final formatting, artifact records, render jobs, file metadata, preview/download links, and artifact lineage refs. |
| Provider route, model alias, provider metric | `nex-mo` | CX, AE, AG | Only MO writes provider registry and runtime telemetry. |
| Admin policy setting and audit event | `nex-ag` plus service-local emitters | Administrators and operators | AG owns governance view; each service emits local audit/log events. |

## Generation Boundary Decision

Several source documents place generation orchestration inside `nex-cx`. That
worked as a useful monolithic PCX experiment, but the platform boundary should
split it more deliberately.

Freeze candidate:

- `nex-cx` owns retrieval context, evidence quality, citation anchors,
  permission filtering, source context expansion, no-answer metadata,
  provider-facing prompt package, and document-grounded generation execution
  record.
- `nex-ae-api` owns user intent, explicit execution mode, prompt contract,
  template choice, user-facing system prompt policy, final answer formatting,
  generated artifact metadata, and user-visible generation history.
- `nex-mo` owns generation provider execution, provider runtime metadata,
  timeout/cancel propagation, usage metadata, and model capability aliases.

Consequence:

- A `nex-cx` endpoint named `/api/v1/generations` can be the default MVP route
  for document-grounded generation, but it must not own final chat state,
  artifact links, or user-facing formatting.
- Direct `nex-ae-api` to `nex-mo` generation is not the default MVP route. It
  requires a later explicit policy and contract.
- The first frozen contract between CX and AE should be the retrieval context package, not a broad structured draft framework.

## Permission Boundary Decision

| Concern | Owner | Rule |
| --- | --- | --- |
| Identity proof | `nex-oa` | OA signs user and service claims. |
| Business visibility metadata | `nex-cx` | CX stores uploader, collection, classification, group scope, and document visibility metadata. |
| Retrieval permission filtering | `nex-cx` | CX applies visibility filters using OA claims before ranking/evidence return. |
| Workspace-level affordance | `nex-ae-web`, `nex-ae-api` | AE shows available scopes and preserves selected search/generation scope. |
| Governance policy UI | `nex-ag` | AG displays and changes policy through service APIs with audit. |

## Freeze Now

| Decision | Rationale |
| --- | --- |
| `nex-oa` means NeX Open Auth. | Avoids the old OA operations/administration naming conflict. |
| `nex-ag` owns admin & governance. | Keeps operations UI, audit, policy, and monitoring in one service. |
| `nex-cx` owns content and retrieval data. | Prevents AE/MO from becoming data repositories. |
| `nex-ae-api` owns user-facing orchestration. | Keeps agent behavior close to chat UX, intent, prompt, template, and artifact experience. |
| `nex-mo` owns model-provider abstraction. | Lets embedding, reranker, generation, health, metrics, and resource telemetry evolve independently. |
| AG and AE do not call provider runtime endpoints directly. | Keeps provider ports private and routing auditable through MO. |
| No cross-service database joins. | Keeps service ownership testable and deployable. |

## Freeze Candidates

| Candidate | Next Decision Needed |
| --- | --- |
| CX retrieval context package schema | Define minimum fields for chunks, scores, source anchors, permission snapshot, no-answer status, and package hash. |
| AE-to-CX generation request package | Define prompt version, template version, execution mode, retrieval package reference, output contract, quality policy, and bounded generation parameters. |
| CX-to-MO generation provider contract | Define alias, workload, provider-facing prompt package hash, response format, admission, streaming/cancel, usage, and runtime metadata. |
| CX generation execution record | Define generation request hash, retrieval package hash, prompt package hash, MO call metadata, structured draft status, citation status, and retry lineage. |
| Structured draft and citation schema | Define generated section/block shape, citation claim shape, evidence anchor validation, completeness status, and AE safe read view. |
| AE artifact rendering handoff contract | Define artifact records, versions, render jobs, files, preview/download links, rollback pointer, and CX lineage refs. |
| MO provider capability aliases | Define stable capability names for embedding, reranking, generation, and future speech providers. |
| AG policy write surface | Decide which policy changes AG can write in MVP versus read-only observe. |
| OA claim catalog | Define MVP user claims, service scopes, permission claims, token TTLs, and rotation minimum. |

## Boundary Conflicts

| Conflict | Handling |
| --- | --- |
| `NP-SRC-07` file name says OA operations/administration. | Use only identity/auth/service-auth content for OA; move operations administration concerns to AG. |
| `NP-SRC-09` includes CX generation, prompt, structured draft, and artifact areas. | Keep CX retrieval/evidence/content lifecycle and document-grounded generation execution record; keep final user-facing chat/artifact ownership in AE. |
| `NP-SRC-11` contains language that AE should not call MO for document generation. | Reconciled in [Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md): AE calls CX for document-grounded generation, and CX calls MO stable API. |
| `NP-SRC-08` contains service lifecycle and host control scope. | Keep AG observation/readiness/audit in MVP; defer host start/stop/restart control unless operational launch requires it. |
| Full SRS and 2-week MVP scope differ. | Use `NP-SRC-13` and this boundary record as the first scope gate; use full SRS only as completeness cross-check. |

## First Contract Tests To Derive

Every service-specific SRS should derive tests for:

- A service rejects writes to data it does not own.
- AG obtains status through APIs rather than direct database access.
- AE search/generation requests carry OA claims to CX.
- CX applies permission filtering before returning evidence.
- AE document generation uses a CX retrieval context package and a CX generation API before MO provider execution.
- MO accepts provider requests by alias/capability, not by raw provider URL.
- OA service-token scopes distinguish `cx:search`, `cx:ingest`,
  `mo:embedding`, `mo:reranking`, `mo:generation`, and admin read/write scopes.
- Generated artifacts remain AE-owned unless explicitly re-ingested into CX.

## Next Inputs

This record should feed:

- NeX-Platform MVP SRS v0.1 service owner sections.
- CX-to-AE retrieval context package contract.
- AE-to-CX generation request package contract.
- CX-to-MO generation provider contract.
- CX generation execution record and lineage contract.
- Structured draft and citation schema contract.
- AE artifact rendering handoff contract.
- OA claim and service scope catalog.
- AG read-only operations dashboard scope.
