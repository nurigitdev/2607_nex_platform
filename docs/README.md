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
| [`Slice 0001`](slices/0001_service_skeleton_bootstrap.md) | `S1-001` Repository and service skeleton bootstrap. |
| [`Slice 0002`](slices/0002_single_pass_quality_gate.md) | `S1-002` Single-pass quality gate bootstrap. |
| [`Slice 0003`](slices/0003_contract_package_bootstrap.md) | `S1-003` Contract package bootstrap. |
| [`Slice 0004`](slices/0004_problem_json_trace_contracts.md) | `S1-004` Common problem+json and trace contract fixtures. |
| [`Slice 0005`](slices/0005_oa_service_token_mock.md) | `S1-005` OA service token mock and claim validation. |
| [`Slice 0006`](slices/0006_mo_mock_provider_registry.md) | `S1-006` MO mock provider alias registry. |
| [`Slice 0007`](slices/0007_cx_generation_facade_to_mo.md) | `S1-007` CX generation facade to MO mock. |
| [`Slice 0008`](slices/0008_ae_api_chat_interaction_stub.md) | `S1-008` AE API chat interaction stub. |
| [`Slice 0009`](slices/0009_ag_readiness_projection.md) | `S1-009` AG service readiness projection. |
| [`Slice 0010`](slices/0010_first_traceable_smoke.md) | `S1-010` First traceable smoke. |
| [`Slice 0011`](slices/0011_cx_upload_registration_ingestion_job.md) | `S2-001` CX upload registration and ingestion job shell. |
| [`Slice 0012`](slices/0012_cx_mock_text_extraction.md) | `S2-002` CX mock text extraction to Markdown. |
| [`Slice 0013`](slices/0013_cx_chunk_policy_1000_100.md) | `S2-003` CX chunk policy `1000_100` implementation. |
| [`Slice 0014`](slices/0014_mo_model_profile_catalog.md) | `S2-004` MO model profile catalog for Qwen defaults. |
| [`Slice 0015`](slices/0015_cx_mock_embedding_index.md) | `S2-005` CX mock embedding index job. |
| [`Slice 0016`](slices/0016_cx_lexical_index_tokenizer_fallback.md) | `S2-006` CX BM25 tokenizer fallback and lexical index shell. |
| [`Slice 0017`](slices/0017_cx_retrieval_context_package.md) | `S2-007` CX retrieval context package endpoint. |
| [`Slice 0018`](slices/0018_ae_retrieval_orchestration.md) | `S2-008` AE retrieval orchestration route. |
| [`Slice 0019`](slices/0019_ae_grounded_chat_retrieval_context.md) | `S2-009` AE grounded chat uses CX retrieval context. |
| [`Slice 0020`](slices/0020_grounded_traceable_mock_flow.md) | `S2-010` Grounded traceable mock flow regression. |
| [`Slice 0021`](slices/0021_persistent_schema_foundation.md) | `S3-001` Persistent schema foundation for content, summaries, prompt registry, and prompt analytics. |
| [`Slice 0022`](slices/0022_cx_source_file_storage_policy.md) | `S3-002` CX source file metadata and local storage key policy. |
| [`Slice 0023`](slices/0023_migration_runner_smoke_guard.md) | `S3-003` Service-owned migration runner and smoke guard. |
| [`Slice 0024`](slices/0024_cx_persistent_repository_boundary.md) | `S3-004` CX persistent repository boundary for source file and content object records. |
| [`Slice 0025`](slices/0025_cx_user_scoped_duplicate_upload_guard.md) | `S3-005` CX user-scoped duplicate upload guard. |
| [`Slice 0026`](slices/0026_cx_local_source_file_materialization.md) | `S3-006` CX local source file materialization. |
| [`Slice 0027`](slices/0027_cx_document_summary_contract.md) | `S3-007` CX document summary contract and mock summarizer job. |
| [`Slice 0028`](slices/0028_cx_summary_embedding_index.md) | `S3-008` CX summary embedding index. |
| [`Slice 0029`](slices/0029_prompt_registry_seed_render_contract.md) | `S3-009` Prompt registry seed and prompt render event contract. |
| [`Slice 0030`](slices/0030_ae_prompt_analytics_intent_mock.md) | `S3-010` AE prompt analytics and mock intent classification. |
| [`Slice 0031`](slices/0031_ae_workspace_state_api_foundation.md) | `S4-001` AE workspace state API foundation. |
| [`Slice 0032`](slices/0032_ae_upload_handoff_facade_to_cx.md) | `S4-002` AE upload handoff facade to CX. |
| [`Slice 0033`](slices/0033_ae_document_library_summary_search_facade.md) | `S4-003` AE document library and summary search facade. |
| [`Slice 0034`](slices/0034_generation_compatibility_rule_contract.md) | `S4-004` Generation compatibility rule contract. |
| [`Slice 0035`](slices/0035_cx_grounded_generation_request_validation.md) | `S4-005` CX grounded generation request validation. |

Each implementation slice should leave behind the smallest useful evidence:
quality output, contract validation output, API smoke output, UI screenshot, or
documentation-only checks, depending on what changed.
