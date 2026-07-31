# Implementation Roadmap + First Sprint Backlog

Status: Draft seed for Slice 446.

Sources:

- [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md)
- [Service-Specific Requirement Partition](30_service_specific_requirement_partition.md)
- [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md)
- [Platform Development Environment Freeze](32_platform_development_environment_freeze.md)
- [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md)
- [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md)
- [Design System v0.1 Expansion](35_design_system_v0_1_expansion.md)

This document turns the MVP documentation set into an implementation roadmap and
first sprint backlog. It keeps the first build focused on a mock-first vertical
spine before live provider and advanced operations work.

## Roadmap Principles

| Principle | Decision |
| --- | --- |
| Vertical first | Prove one user prompt can flow through auth, AE, CX, MO mock, artifact, and AG audit. |
| Contracts before depth | Bootstrap schemas/OpenAPI/examples before adding broad feature depth. |
| Mock before live | CI and local development use mock providers first; DGX/vLLM smoke follows. |
| Service ownership | Each service owns its DB and write model from the first implementation slice. |
| Evidence always | Every feature slice should produce regression/contract/UI/smoke evidence appropriate to its change. |

## 2-Week MVP Roadmap

| Window | Goal | Primary Output |
| --- | --- | --- |
| Day 1 | Repository, service skeletons, health/ready/version, quality gate skeleton. | Services start in `local_mock`; common health checks pass. |
| Day 2 | Contract package bootstrap and schema/OpenAPI validation command. | `contracts/` layout, examples, validation tests. |
| Day 3 | OA bootstrap auth and service claim validation. | Login/service token mock path and claim validation fixtures. |
| Day 4 | MO mock provider registry and capability aliases. | Embedding/reranker/generation mock routes and readiness. |
| Day 5-6 | CX upload, extraction stub, chunk policy, index readiness stubs. | Ingestion job path and retrieval package fixture. |
| Day 7 | AE API workspace/chat/orchestration facade. | Chat document, interaction, retrieval request, generation request wrapper. |
| Day 8 | AE web shell and chat/upload/search/generation basic UX. | Korean-default UI screenshot with mock data. |
| Day 9 | CX-mediated generation with MO mock and structured draft validation. | Generation execution record and progress events. |
| Day 10 | AE artifact handoff and download metadata. | Artifact card/link and download permission path. |
| Day 11 | AG readiness and generation artifact audit read path. | Admin dashboard read-only audit detail. |
| Day 12 | Mock E2E `GEN-E2E-001` to `GEN-E2E-010`. | E2E evidence and coverage summary. |
| Day 13 | Live provider smoke and release hardening. | Redacted DGX/vLLM smoke evidence where available. |
| Day 14 | Demo, documentation cleanup, backlog re-triage. | MVP release evidence package. |

## Sprint 1 Objective

Sprint 1 should prove the platform skeleton and contracts, not the full document
intelligence depth.

```text
Start five backend service shells and one AE web shell in local_mock,
validate common contracts, perform an OA-backed service claim check,
call an MO mock generation alias through CX, and expose a traceable
health/readiness path to AG.
```

## Sprint 1 Backlog

| Backlog ID | Slice Candidate | Requirement Coverage | Done When |
| --- | --- | --- | --- |
| `S1-001` | Repository and service skeleton bootstrap | `PLAT-FR-001`, environment freeze | Workspace layout exists; service shells run health/ready/version. |
| `S1-002` | Single-pass quality gate bootstrap | Testing strategy | Quality command reports regression, statement coverage, and branch coverage. |
| `S1-003` | Contract package bootstrap | `PLAT-FR-007` | `contracts/schemas`, `openapi`, `examples`, and validation command exist. |
| `S1-004` | Common problem+json and trace contract fixtures | `PLAT-FR-003`, `PLAT-FR-004` | Positive/negative examples validate. |
| `S1-005` | OA service token mock and claim validation | `OA-FR-002`, `OA-FR-003`, `PLAT-FR-002` | Backend services can validate a test service claim. |
| `S1-006` | MO mock provider alias registry | `MO-FR-001`, `MO-FR-004` | Mock embedding/reranking/generation aliases return deterministic responses. |
| `S1-007` | CX generation facade to MO mock | `CX-FR-007`, `MO-FR-002` | CX calls MO by alias and stores safe request/response metadata. |
| `S1-008` | AE API chat interaction stub | `AEAPI-FR-001`, `AEAPI-FR-003` | AE creates chat interaction and calls CX mock path. |
| `S1-009` | AG service readiness projection | `AG-FR-001` | AG reads health/ready/version from service APIs. |
| `S1-010` | First traceable smoke | `TRACE-PLAT-001`, `TRACE-MO-001` | One trace ID appears in AE, CX, MO, and AG mock evidence. |

Sprint 1 should stop before full upload/extraction unless service skeleton,
contract validation, and mock provider call chain are stable.

## Near-Term Follow-Up Backlog

| Backlog ID | Focus | Depends On |
| --- | --- | --- |
| `S2-001` | CX upload registration and ingestion job shell | `S1-001`, `S1-002`, `S1-005` |
| `S2-002` | CX extraction stub and fixture corpus | `S2-001` |
| `S2-003` | Chunk policy and source anchor persistence | `S2-002` |
| `S2-004` | BM25 and embedding readiness stubs | `S2-003`, `S1-006` |
| `S2-005` | Retrieval context package API | `S2-004` |
| `S2-006` | AE web app shell and Korean nav | `S1-008`, design system |
| `S2-007` | AE upload/search/generation MVP screens | `S2-005`, `S2-006` |
| `S2-008` | CX structured draft/citation validation | `S1-007`, contract package |
| `S2-009` | AE artifact handoff/render/download metadata | `S2-008` |
| `S2-010` | AG generation artifact audit dashboard | `S2-009`, `S1-009` |

## First Acceptance Evidence

| Evidence | Produced By |
| --- | --- |
| Service health output | `S1-001` |
| Quality gate output | `S1-002` |
| Schema/OpenAPI validation result | `S1-003`, `S1-004` |
| OA claim validation fixture | `S1-005` |
| MO mock provider request/response | `S1-006` |
| CX-to-MO trace evidence | `S1-007` |
| AE interaction trace evidence | `S1-008` |
| AG readiness projection | `S1-009` |
| Combined trace smoke markdown | `S1-010` |

## Stop Conditions

Stop and re-plan if:

- Service ownership requires cross-service database access.
- Contract examples cannot validate without service-private fields.
- Mock provider behavior cannot cover timeout/throttle/failure branches.
- OA claim shape blocks CX permission filtering.
- AE or AG needs direct provider runtime calls to make progress.
- Quality gate becomes two slow commands instead of one combined gate.

## Next Inputs

This roadmap should feed:

- Actual implementation Slice 447+ planning.
- Repository bootstrap task list.
- Contract package bootstrap tasks.
- Sprint 1 acceptance review.
