# NeX-Platform Working Documentation

Status: Working-document baseline for Slice 0000.

This repository starts from the documentation needed to build the first
NeX-Platform MVP, not from the full planning archive. The current committed
documents are intentionally focused on what the implementation team should use
day to day: MVP scope, service ownership, traceability, environment rules,
contract layout, testing strategy, design system guidance, and the first sprint
backlog.

Older planning slice references such as `Slice 418` through `Slice 446` remain
useful provenance. New work in this repository uses the zero-padded
`Slice 0000` numbering system.

## Slice Numbering

| Range | Meaning |
| --- | --- |
| `Slice 0000` | Documentation baseline, working-doc selection, and numbering policy. |
| `Slice 0001+` | Implementation or documentation slices in this repository. |
| `Slice 418-446` | Legacy planning provenance from the source planning workspace. |

Slice IDs should be written as four digits, for example `Slice 0001`. A slice
should stay small enough to review and should reference the relevant requirement
IDs, contracts, and evidence artifacts.

## Canonical Start Package

Documents `29` through `36` are the canonical MVP start package for this
repository. They absorb the most important decisions from the earlier planning
documents and show the current build direction directly.

| Doc | Role |
| --- | --- |
| [29 MVP SRS v0.1](29_nex_platform_mvp_srs_v0_1_assembly.md) | Defines MVP purpose, scope, service requirements, acceptance, NFRs, deferrals, and open decisions. |
| [30 Service-Specific Requirement Partition](30_service_specific_requirement_partition.md) | Splits requirements by service owner and preserves dependency order. |
| [31 Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md) | Connects source basis, requirement IDs, contracts, tests, and evidence. |
| [32 Platform Development Environment Freeze](32_platform_development_environment_freeze.md) | Freezes monorepo-style layout, profiles, database naming, config families, and mock/live rules. |
| [33 Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md) | Defines where schemas, OpenAPI files, examples, and contract fixtures live. |
| [34 Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md) | Defines quality gates, test layers, contract fixtures, mock E2E, UI evidence, and docs-only slice checks. |
| [35 Design System v0.1 Expansion](35_design_system_v0_1_expansion.md) | Defines MVP UI principles, tokens, layouts, components, status rules, i18n, and accessibility. |
| [36 Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md) | Converts the documentation set into the first implementation sequence. |

Recommended first read:

1. [29 MVP SRS v0.1](29_nex_platform_mvp_srs_v0_1_assembly.md)
2. [30 Service-Specific Requirement Partition](30_service_specific_requirement_partition.md)
3. [31 Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md)
4. [36 Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md)

## Supporting Working Docs

The following documents remain in the working set because they clarify the
highest-risk platform boundaries before implementation begins.

| Doc | Why It Stays In Working Docs |
| --- | --- |
| [10 2-Week MVP Capability Map](10_2week_mvp_capability_map.md) | Shows the reduced vertical flow and service capability map behind the MVP. |
| [11 Common Contract Freeze Candidate Map](11_common_contract_freeze_candidate_map.md) | Captures cross-service naming, API, job, error, state, logging, audit, and redaction rules. |
| [12 Service Boundary Decision Record](12_service_boundary_decision_record.md) | Freezes service ownership and call-chain rules. |
| [13 AE Agent Orchestration Contract](13_ae_agent_orchestration_contract.md) | Defines AE as the bounded user-facing orchestrator. |
| [14 CX-to-AE Retrieval Context Package Contract](14_cx_ae_retrieval_context_package_contract.md) | Defines retrieval package fields, no-answer behavior, permission snapshot, and evidence shape. |
| [16 AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md) | Defines the request AE sends to CX for grounded generation. |
| [17 CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md) | Defines how CX calls MO by alias/capability and how MO returns runtime metadata. |
| [28 Generation E2E Acceptance + Contract Test Plan](28_generation_e2e_acceptance_contract_test_plan.md) | Defines the mock-first generation acceptance spine and contract test matrix. |

## Reference Archive Policy

The following documents are not part of the main working-doc set for this new
repository, but they can be brought back as reference material when needed.

| Docs | Archive Role |
| --- | --- |
| `00-09` | Documentation framework, skeletons, PCX lessons, source inventory, and review matrix. Useful for provenance, less useful for daily implementation. |
| `15` | Generation routing reconciliation. Bring back if AE/CX/MO generation ownership becomes contested again. |
| `18-27` | Detailed generation contracts for execution records, structured drafts, artifact handoff, progress events, retry/repair, chat artifact links, compatibility, AG audit, schemas, and OpenAPI. Bring back when generation implementation reaches those details. |

The archive policy means "not in the daily working set", not "discarded". If a
slice needs one of these documents, reintroduce it explicitly and link it from
the active slice notes.

## Platform Services

| Service | Role |
| --- | --- |
| `nex-cx` | Content experience repository: source files, extracted text, chunks, embeddings, BM25, graph extension points, and retrieval APIs. |
| `nex-ae-web` | User-facing workspace UI/UX for chat, search, generation, summaries, artifacts, and downloads. |
| `nex-ae-api` | Agent execution backend for intent routing, retrieval orchestration, generation orchestration, formatting, and artifact creation. |
| `nex-mo` | Model operations service for embedding, reranker, generation provider connectivity, readiness, usage, and metrics. |
| `nex-oa` | NeX Open Auth: user auth, service auth, token/session/API key management, permission claims, and trust boundaries. |
| `nex-ag` | Admin and governance service for operations, logs, policies, monitoring, readiness, and audit views. |

Canonical first-call chain:

```text
Browser -> nex-ae-web -> nex-ae-api -> nex-cx -> nex-mo
```

## First Implementation Path

The first implementation slices should follow the Sprint 1 backlog in
[36 Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).

| Slice | Starting Backlog Candidate |
| --- | --- |
| `Slice 0001` | `S1-001` Repository and service skeleton bootstrap. |
| `Slice 0002` | `S1-002` Single-pass quality gate bootstrap. |
| `Slice 0003` | `S1-003` Contract package bootstrap. |
| `Slice 0004` | `S1-004` Common problem+json and trace contract fixtures. |
| `Slice 0005` | `S1-005` OA service token mock and claim validation. |
| `Slice 0006` | `S1-006` MO mock provider alias registry. |
| `Slice 0007` | `S1-007` CX generation facade to MO mock. |
| `Slice 0008` | `S1-008` AE API chat interaction stub. |
| `Slice 0009` | `S1-009` AG service readiness projection. |
| `Slice 0010` | `S1-010` First traceable smoke. |

Each implementation slice should leave behind the smallest useful evidence:
quality output, contract validation output, API smoke output, UI screenshot, or
documentation-only checks, depending on what changed.
