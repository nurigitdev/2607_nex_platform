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
| [`Slice 0036`](slices/0036_cx_structured_draft_citation_mock_validation.md) | `S4-006` CX structured draft and citation mock validation. |
| [`Slice 0037`](slices/0037_generation_progress_event_contract.md) | `S4-007` Generation progress event contract and CX polling timeline. |
| [`Slice 0038`](slices/0038_ae_artifact_handoff_metadata.md) | `S4-008` AE artifact handoff metadata from validated CX draft lineage. |
| [`Slice 0039`](slices/0039_ag_generation_audit_projection.md) | `S4-009` AG generation audit projection over CX events and AE handoffs. |
| [`Slice 0040`](slices/0040_ae_web_workspace_shell_integration.md) | `S4-010` AE web MVP workspace shell integration. |
| [`Slice 0041`](slices/0041_ae_artifact_record_family_foundation.md) | `S5-001` AE artifact record family foundation. |
| [`Slice 0042`](slices/0042_ae_markdown_artifact_renderer_mvp.md) | `S5-002` AE Markdown artifact renderer MVP. |
| [`Slice 0043`](slices/0043_ae_artifact_file_preview_download_metadata.md) | `S5-003` AE artifact file preview and download metadata. |
| [`Slice 0044`](slices/0044_ae_chat_artifact_link_contract.md) | `S5-004` AE chat artifact link contract. |
| [`Slice 0045`](slices/0045_ae_web_artifact_card_integration.md) | `S5-005` AE web artifact card integration. |
| [`Slice 0046`](slices/0046_generation_recovery_policy_contract.md) | `S5-006` Generation recovery policy contract. |
| [`Slice 0047`](slices/0047_cx_generation_failure_lineage_stub.md) | `S5-007` CX generation failure record and recovery lineage stub. |
| [`Slice 0048`](slices/0048_ae_generation_recovery_request_api.md) | `S5-008` AE generation recovery request API. |
| [`Slice 0049`](slices/0049_ag_generation_recovery_audit_projection.md) | `S5-009` AG generation recovery audit projection. |
| [`Slice 0050`](slices/0050_generation_recovery_mock_flow.md) | `S5-010` Generation recovery mock flow regression. |
| [`Slice 0051`](slices/0051_dgx_live_provider_preflight_generation_catalog.md) | `S6-001` DGX live provider preflight and pluggable generation model catalog. |
| [`Slice 0052`](slices/0052_remote_provider_http_client_preflight_shapes.md) | `S6-002` Remote provider HTTP client foundation and live preflight request shapes. |
| [`Slice 0053`](slices/0053_mo_remote_embedding_execution_adapter.md) | `S6-003` MO remote embedding execution adapter. |
| [`Slice 0054`](slices/0054_mo_remote_reranker_execution_adapter.md) | `S6-004` MO remote reranker execution adapter. |
| [`Slice 0055`](slices/0055_mo_vllm_generation_execution_adapter.md) | `S6-005` MO vLLM generation execution adapter. |
| [`Slice 0056`](slices/0056_provider_failure_taxonomy_retry_degrade_policy.md) | `S6-006` Provider failure taxonomy and retry/degrade policy. |
| [`Slice 0057`](slices/0057_mo_provider_runtime_telemetry_snapshot.md) | `S6-007` MO provider runtime telemetry snapshot. |
| [`Slice 0058`](slices/0058_ag_mo_provider_readiness_projection.md) | `S6-008` AG MO provider readiness projection. |
| [`Slice 0059`](slices/0059_protected_live_smoke_evidence_writer.md) | `S6-009` Protected live smoke evidence writer. |
| [`Slice 0060`](slices/0060_cx_mo_remote_mode_regression_bridge.md) | `S6-010` CX-to-MO remote-mode regression bridge. |
| [`Slice 0061`](slices/0061_local_live_provider_config_guard.md) | `S6-011` Local live provider config guard and Qwen3 reranker 0.6B update. |
| [`Slice 0062`](slices/0062_protected_dgx_live_preflight_profile.md) | `S6-012` Protected DGX live preflight execution profile. |
| [`Slice 0063`](slices/0063_protected_dgx_live_smoke_evidence_execution.md) | `S6-013` Protected DGX live smoke evidence execution. |
| [`Slice 0064`](slices/0064_compatible_provider_contract_freeze.md) | `S6-014` OpenAI-compatible embedding and NeX-compatible reranker provider contract freeze. |
| [`Slice 0065`](slices/0065_compatible_provider_skeleton.md) | `S6-015` Mock-first compatible provider source skeleton. |
| [`Slice 0066`](slices/0066_compatible_provider_dgx_live_smoke.md) | `S6-016` Direct vLLM compatible provider DGX live smoke and BF16 serving evidence policy. |
| [`Slice 0067`](slices/0067_dgx_vllm_profile_split.md) | `S6-017` Protected DGX vLLM profile and legacy PCX profile split. |
| [`Slice 0068`](slices/0068_mo_direct_vllm_execution_regression.md) | `S6-018` MO direct vLLM execution profile regression. |
| [`Slice 0069`](slices/0069_cx_retrieval_rerank_bridge_to_mo_vllm.md) | `S6-019` CX retrieval rerank bridge to MO direct vLLM mode. |
| [`Slice 0070`](slices/0070_compatible_only_profile_guardrail.md) | `S6-020` Compatible-only DGX profile guardrail and legacy PCX quarantine. |
| [`Slice 0071`](slices/0071_cx_real_file_upload_boundary_hardening.md) | `S7-001` CX real file upload boundary hardening. |
| [`Slice 0072`](slices/0072_cx_text_extraction_adapter_foundation.md) | `S7-002` CX text extraction adapter foundation. |
| [`Slice 0073`](slices/0073_cx_document_processing_pipeline_job.md) | `S7-003` CX document processing pipeline job. |
| [`Slice 0074`](slices/0074_retrieval_quality_policy_v1.md) | `S7-004` Retrieval quality policy v1. |
| [`Slice 0075`](slices/0075_protected_live_rag_smoke_evidence.md) | `S7-005` Protected live RAG smoke evidence. |
| [`Slice 0076`](slices/0076_ag_retrieval_policy_registry.md) | `S8-001` AG retrieval policy read-only registry. |
| [`Slice 0077`](slices/0077_cx_tokenizer_profile_alignment.md) | `S8-002` CX tokenizer profile and query alignment. |
| [`Slice 0078`](slices/0078_weighted_rrf_hybrid_retrieval.md) | `S8-003` Weighted RRF vector/BM25 hybrid retrieval. |
| [`Slice 0079`](slices/0079_cx_active_retrieval_policy_application.md) | `S8-004` CX active retrieval policy application. |
| [`Slice 0080`](slices/0080_rag_workflow_evidence_pack.md) | `S8-005` RAG workflow evidence pack. |
| [`Slice 0081`](slices/0081_db_connection_readiness_foundation.md) | `S9-001` DB connection readiness foundation and optional CX vector database routing. |
| [`Slice 0082`](slices/0082_service_migration_profile_alembic_foundation.md) | `S9-002` Service migration dev/test profile and Alembic config foundation. |
| [`Slice 0083`](slices/0083_shared_service_job_queue_foundation.md) | `S9-003` Shared common job queue interface and service job table foundation. |
| [`Slice 0084`](slices/0084_cx_processing_pipeline_jobqueue_bridge.md) | `S9-004` CX document processing pipeline bridge to the common JobQueue port. |
| [`Slice 0085`](slices/0085_operational_event_log_foundation.md) | `S9-005` Shared operational event/log foundation and AG read-only projection. |
| [`Slice 0086`](slices/0086_db_runtime_pool_session_unit_of_work_foundation.md) | `S9-006` DB runtime pool/session/unit-of-work foundation for DB-intensive services. |
| [`Slice 0087`](slices/0087_sqlalchemy_jobqueue_adapter_postgres_smoke.md) | `S9-007` Persistent SQLAlchemy JobQueue adapter with SQLite regression and guarded PostgreSQL smoke. |
| [`Slice 0088`](slices/0088_sqlalchemy_operational_event_store_postgres_smoke.md) | `S9-008` Persistent SQLAlchemy OperationalEventStore with SQLite regression and guarded PostgreSQL smoke. |
| [`Slice 0089`](slices/0089_ag_jobqueue_operations_projection.md) | `S9-009` AG read-only JobQueue operations projection. |
| [`Slice 0090`](slices/0090_cross_service_db_operations_smoke_pack.md) | `S9-010` Cross-service PostgreSQL DB operations smoke pack. |
| [`Slice 0091`](slices/0091_service_runtime_persistence_bootstrap.md) | `S10-001` Service runtime persistence bootstrap for memory/postgres mode selection. |
| [`Slice 0092`](slices/0092_cx_processing_postgres_jobqueue_runtime_smoke.md) | `S10-002` CX processing route PostgreSQL-backed JobQueue runtime smoke. |
| [`Slice 0093`](slices/0093_shared_operational_event_emitter.md) | `S10-003` Shared operational event emitter for route and worker write-through. |
| [`Slice 0094`](slices/0094_cx_processing_operational_events.md) | `S10-004` CX processing lifecycle operational events. |
| [`Slice 0095`](slices/0095_cx_processing_postgres_operational_event_smoke.md) | `S10-005` CX processing route PostgreSQL-backed OperationalEvent smoke. |
| [`Slice 0096`](slices/0096_ag_operations_source_registry.md) | `S10-006` AG operations source registry for jobs and events. |
| [`Slice 0097`](slices/0097_ag_unified_operations_projection.md) | `S10-007` AG unified operations projection over jobs and events. |
| [`Slice 0098`](slices/0098_service_operational_event_taxonomy_registry.md) | `S10-008` Service operational event taxonomy registry. |
| [`Slice 0099`](slices/0099_ag_runtime_db_backed_operations_wiring.md) | `S10-009` AG runtime DB-backed operations source wiring. |
| [`Slice 0100`](slices/0100_ag_cross_service_observability_smoke.md) | `S10-010` AG cross-service DB-backed observability smoke. |
| [`Slice 0101`](slices/0101_ag_operations_query_contract_hardening.md) | `S11-001` AG operations query contract hardening. |
| [`Slice 0102`](slices/0102_ag_operation_source_readiness_projection.md) | `S11-002` AG operation source readiness projection. |
| [`Slice 0103`](slices/0103_ag_operational_event_detail_search.md) | `S11-003` AG operational event detail and log search API. |
| [`Slice 0104`](slices/0104_ag_job_detail_lifecycle_timeline.md) | `S11-004` AG job detail and lifecycle timeline API. |
| [`Slice 0105`](slices/0105_ag_cross_service_trace_timeline.md) | `S11-005` AG cross-service trace timeline projection. |
| [`Slice 0106`](slices/0106_ag_operations_contract_examples_freeze.md) | `S11-006` AG operations contract/examples freeze. |
| [`Slice 0107`](slices/0107_ag_operations_rollup_metrics_projection.md) | `S11-007` AG operations rollup metrics projection. |
| [`Slice 0108`](slices/0108_ag_operations_dashboard_snapshot_projection.md) | `S11-008` AG operations dashboard snapshot projection. |
| [`Slice 0109`](slices/0109_ag_operations_issue_candidate_projection.md) | `S11-009` AG operations issue candidate projection. |
| [`Slice 0110`](slices/0110_ag_operations_dashboard_smoke_evidence_pack.md) | `S11-010` AG operations dashboard smoke evidence pack. |
| [`Slice 0111`](slices/0111_worker_heartbeat_contract_foundation.md) | `S12-001` Worker heartbeat contract foundation for service worker liveness. |
| [`Slice 0112`](slices/0112_worker_heartbeat_persistence_foundation.md) | `S12-002` Worker heartbeat persistence foundation with SQLite regression. |
| [`Slice 0113`](slices/0113_ag_worker_runtime_projection.md) | `S12-003` AG worker runtime projection over heartbeat stores. |
| [`Slice 0114`](slices/0114_worker_stuck_job_issue_candidates.md) | `S12-004` Worker heartbeat based stuck job issue candidate rules. |
| [`Slice 0115`](slices/0115_worker_heartbeat_emitter_runtime_helper.md) | `S12-005` Worker heartbeat emitter/runtime helper for service workers. |
| [`Slice 0116`](slices/0116_cx_processing_worker_heartbeat_integration.md) | `S12-006` CX processing pipeline worker heartbeat integration. |
| [`Slice 0117`](slices/0117_worker_lifecycle_operational_events.md) | `S12-007` Worker lifecycle operational events for CX processing observability. |
| [`Slice 0118`](slices/0118_ag_worker_detail_job_correlation_api.md) | `S12-008` AG worker detail API with active job and lifecycle event correlation. |
| [`Slice 0119`](slices/0119_ag_worker_observability_smoke_evidence.md) | `S12-009` AG worker observability smoke evidence for runtime and detail projections. |
| [`Slice 0120`](slices/0120_ag_worker_observability_openapi_freeze.md) | `S12-010` AG worker observability OpenAPI contract freeze. |
| [`Slice 0121`](slices/0121_postgresql_test_smoke_suite_runner.md) | `S13-001` PostgreSQL test smoke suite runner and evidence pack. |
| [`Slice 0122`](slices/0122_service_worker_runner_foundation.md) | `S13-002` Shared service worker runner foundation. |
| [`Slice 0123`](slices/0123_cx_document_processing_background_worker.md) | `S13-003` CX document processing background worker path. |
| [`Slice 0124`](slices/0124_job_retry_backoff_dead_letter_policy.md) | `S13-004` Common job retry, backoff, and dead-letter policy. |
| [`Slice 0125`](slices/0125_service_local_job_control_api_foundation.md) | `S13-005` Service-local job control API foundation. |
| [`Slice 0126`](slices/0126_ag_service_local_job_control_client_foundation.md) | `S13-006` AG service-local job control client foundation. |
| [`Slice 0127`](slices/0127_ag_job_operation_control_endpoints.md) | `S13-007` AG job operation control endpoints. |
| [`Slice 0128`](slices/0128_job_control_audit_operational_events.md) | `S13-008` Job control audit operational events. |
| [`Slice 0129`](slices/0129_dead_letter_operator_replay_policy_foundation.md) | `S13-009` Dead-letter operator replay policy foundation. |
| [`Slice 0130`](slices/0130_job_control_openapi_and_smoke_evidence.md) | `S13-010` Job control OpenAPI and smoke evidence. |
| [`Slice 0131`](slices/0131_service_local_dead_letter_replay_api.md) | `S14-001` Service-local dead-letter replay API. |
| [`Slice 0132`](slices/0132_ag_dead_letter_replay_dispatch_endpoint.md) | `S14-002` AG dead-letter replay dispatch endpoint. |
| [`Slice 0133`](slices/0133_replay_openapi_and_smoke_evidence.md) | `S14-003` Replay OpenAPI and smoke evidence. |
| [`Slice 0134`](slices/0134_dead_letter_replay_issue_dashboard_surfacing.md) | `S14-004` Dead-letter replay issue/dashboard surfacing. |
| [`Slice 0135`](slices/0135_replay_postgresql_smoke_evidence.md) | `S14-005` Replay PostgreSQL smoke evidence. |
| [`Slice 0136`](slices/0136_structured_service_log_contract_foundation.md) | `S14-006` Structured service log contract foundation. |
| [`Slice 0137`](slices/0137_service_log_persistence_foundation.md) | `S14-007` Service-local structured log persistence foundation. |
| [`Slice 0138`](slices/0138_service_log_emitter_runtime_integration.md) | `S14-008` Service log emitter and worker runtime integration. |
| [`Slice 0139`](slices/0139_ag_structured_service_log_projection.md) | `S14-009` AG structured service log projection and search API. |
| [`Slice 0140`](slices/0140_service_log_openapi_smoke_evidence.md) | `S14-010` Structured service log OpenAPI and smoke evidence. |
| [`Slice 0141`](slices/0141_service_log_postgresql_smoke_evidence.md) | `S15-001` Service log PostgreSQL smoke evidence. |
| [`Slice 0142`](slices/0142_service_log_issue_candidate_rules.md) | `S15-002` Service log issue candidate rules. |
| [`Slice 0143`](slices/0143_trace_timeline_service_log_correlation.md) | `S15-003` Trace timeline service log correlation. |
| [`Slice 0144`](slices/0144_service_log_rollup_metrics_projection.md) | `S15-004` Service log rollup metrics projection. |
| [`Slice 0145`](slices/0145_service_log_query_retention_policy_contract.md) | `S15-005` Service log query and retention policy contract. |
| [`Slice 0146`](slices/0146_service_log_retention_dry_run_projection.md) | `S15-006` Service log retention dry-run projection. |
| [`Slice 0147`](slices/0147_service_log_retention_execution_audit_contract.md) | `S15-007` Service log retention execution and audit contract. |
| [`Slice 0148`](slices/0148_service_log_retention_purge_capability_foundation.md) | `S15-008` Service log retention purge capability foundation. |
| [`Slice 0149`](slices/0149_service_log_retention_control_api_and_ag_dispatch_guardrail.md) | `S15-009` Service log retention control API and AG dispatch guardrail. |
| [`Slice 0150`](slices/0150_service_log_retention_openapi_and_smoke_evidence.md) | `S15-010` Service log retention OpenAPI and smoke evidence. |
| [`Slice 0151`](slices/0151_service_log_retention_postgresql_smoke_evidence.md) | `S16-001` Service log retention PostgreSQL smoke evidence. |
| [`Slice 0152`](slices/0152_service_log_retention_http_postgresql_smoke_evidence.md) | `S16-002` Service log retention HTTP PostgreSQL smoke evidence. |
| [`Slice 0153`](slices/0153_ag_retention_dispatch_postgresql_smoke_evidence.md) | `S16-003` AG retention dispatch PostgreSQL smoke evidence. |
| [`Slice 0154`](slices/0154_database_url_compatibility_postgresql_smoke_hardening.md) | `S16-004` Database URL compatibility and PostgreSQL smoke evidence hardening. |
| [`Slice 0155`](slices/0155_retention_history_scope_reconciliation.md) | `S16-005` Retention history scope reconciliation checkpoint. |
| [`Slice 0156`](slices/0156_service_log_retention_execution_history_contract_schema.md) | `S16-006` Service log retention execution history contract schema. |
| [`Slice 0157`](slices/0157_service_local_retention_history_store_and_query_api.md) | `S16-007` Service-local retention history store and query API. |
| [`Slice 0158`](slices/0158_ag_retention_history_projection.md) | `S16-008` AG retention history projection. |
| [`Slice 0159`](slices/0159_ag_retention_history_postgresql_smoke_evidence.md) | `S16-009` AG retention history PostgreSQL smoke evidence. |
| [`Slice 0160`](slices/0160_ag_operations_debug_smoke_closure.md) | `S16-010` AG operations debug smoke closure. |
| [`Slice 0161`](slices/0161_cx_persistence_gap_audit_refactoring_checkpoint.md) | `S17-001` CX persistence gap audit and refactoring checkpoint. |
| [`Slice 0162`](slices/0162_sqlalchemy_cx_content_repository_foundation.md) | `S17-002` SQLAlchemy CX content repository foundation. |
| [`Slice 0163`](slices/0163_cx_sqlalchemy_upload_duplicate_regression.md) | `S17-003` CX SQLAlchemy upload duplicate regression. |
| [`Slice 0164`](slices/0164_cx_extraction_artifact_persistence_adapter.md) | `S17-004` CX extraction artifact persistence adapter. |
| [`Slice 0165`](slices/0165_cx_chunk_set_chunk_persistence_adapter.md) | `S17-005` CX chunk set/chunk persistence adapter. |
| [`Slice 0166`](slices/0166_cx_lexical_index_persistence_adapter.md) | `S17-006` CX lexical index persistence adapter. |
| [`Slice 0167`](slices/0167_cx_chunk_embedding_persistence_adapter.md) | `S17-007` CX chunk embedding metadata persistence adapter. |
| [`Slice 0168`](slices/0168_cx_document_summary_persistence_adapter.md) | `S17-008` CX document summary metadata persistence adapter. |
| [`Slice 0169`](slices/0169_cx_summary_embedding_persistence_adapter.md) | `S17-009` CX summary embedding metadata persistence adapter. |
| [`Slice 0170`](slices/0170_cx_retrieval_processing_schema_checkpoint.md) | `S17-010` CX retrieval/processing persistence schema checkpoint. |
| [`Slice 0171`](slices/0171_cx_retrieval_runtime_persistence_decision.md) | `S18-001` CX retrieval runtime persistence decision. |
| [`Slice 0172`](slices/0172_cx_retrieval_package_schema_migration.md) | `S18-002` CX retrieval package PostgreSQL schema migration. |
| [`Slice 0173`](slices/0173_cx_retrieval_package_repository_adapter.md) | `S18-003` CX retrieval package repository adapter. |
| [`Slice 0174`](slices/0174_cx_retrieval_package_write_through.md) | `S18-004` CX retrieval package store write-through. |
| [`Slice 0175`](slices/0175_cx_retrieval_postgresql_smoke_evidence.md) | `S18-005` CX retrieval PostgreSQL smoke evidence. |
| [`Slice 0176`](slices/0176_ag_retrieval_package_operations_projection.md) | `S18-006` AG retrieval package operations projection. |
| [`Slice 0177`](slices/0177_ag_retrieval_package_detail_debug_projection.md) | `S18-007` AG retrieval package detail/debug projection. |
| [`Slice 0178`](slices/0178_ag_trace_timeline_retrieval_package_correlation.md) | `S18-008` AG trace timeline retrieval package correlation. |
| [`Slice 0179`](slices/0179_ag_retrieval_package_postgresql_smoke_evidence.md) | `S18-009` AG retrieval package PostgreSQL smoke evidence. |
| [`Slice 0180`](slices/0180_retrieval_observability_contract_examples_closure.md) | `S18-010` Retrieval observability contract examples closure. |
| [`Slice 0181`](slices/0181_cx_processing_run_persistence_decision_checkpoint.md) | `S19-001` CX processing run persistence decision checkpoint. |
| [`Slice 0182`](slices/0182_cx_processing_run_step_schema_migration.md) | `S19-002` CX processing run/step PostgreSQL schema migration. |
| [`Slice 0183`](slices/0183_cx_processing_run_repository_adapter.md) | `S19-003` CX processing run repository adapter. |
| [`Slice 0184`](slices/0184_cx_processing_run_write_through_integration.md) | `S19-004` CX processing run write-through integration. |
| [`Slice 0185`](slices/0185_cx_processing_postgresql_smoke_evidence.md) | `S19-005` CX processing run PostgreSQL smoke evidence. |
| [`Slice 0186`](slices/0186_cx_processing_persisted_read_model_query_foundation.md) | `S19-006` CX processing persisted read-model query foundation. |
| [`Slice 0187`](slices/0187_cx_processing_run_service_api_persisted_wiring.md) | `S19-007` CX processing run service API persisted wiring. |
| [`Slice 0188`](slices/0188_cx_processing_service_api_postgresql_smoke_evidence.md) | `S19-008` CX processing service API PostgreSQL smoke evidence. |
| [`Slice 0189`](slices/0189_cx_processing_run_operations_projection_contract.md) | `S19-009` CX processing run operations projection contract. |
| [`Slice 0190`](slices/0190_ag_cx_processing_operations_projection_postgres_smoke.md) | `S19-010` AG CX processing operations projection PostgreSQL smoke. |
| [`Slice 0191`](slices/0191_cx_processing_operations_dashboard_integration.md) | `S20-001` CX processing operations dashboard integration. |
| [`Slice 0192`](slices/0192_cx_source_ownership_boundary_decision.md) | `S20-002` CX source ownership boundary decision. |
| [`Slice 0193`](slices/0193_nex_oa_subject_registry_foundation.md) | `S20-003` NeX-OA subject registry foundation. |
| [`Slice 0194`](slices/0194_cx_source_ownership_schema_migration.md) | `S20-004` CX source ownership schema migration. |
| [`Slice 0195`](slices/0195_cx_owner_scoped_repository_api_wiring.md) | `S20-005` CX owner-scoped repository API wiring. |
| [`Slice 0196`](slices/0196_ae_upload_ownership_propagation_contract.md) | `S20-006` AE upload ownership propagation contract. |
| [`Slice 0197`](slices/0197_cx_upload_canonical_ownership_intake.md) | `S20-007` CX upload canonical ownership intake. |
| [`Slice 0198`](slices/0198_oa_subject_registry_resolver_client.md) | `S20-008` OA subject registry resolver client. |
| [`Slice 0199`](slices/0199_ae_upload_ownership_resolver_wiring.md) | `S20-009` AE upload ownership resolver wiring. |
| [`Slice 0200`](slices/0200_cx_upload_ownership_resolver_guardrail_smoke.md) | `S20-010` CX upload ownership resolver guardrail smoke. |
| [`Slice 0201`](slices/0201_cx_owner_scoped_document_library_projection.md) | `S21-001` CX owner-scoped document library projection. |
| [`Slice 0202`](slices/0202_cx_document_library_service_api_wiring.md) | `S21-002` CX document library service API wiring. |
| [`Slice 0203`](slices/0203_cx_document_library_postgresql_smoke_evidence.md) | `S21-003` CX document library PostgreSQL smoke evidence. |
| [`Slice 0204`](slices/0204_cx_upload_duplicate_upsert_postgresql_smoke_hardening.md) | `S21-004` CX upload duplicate/upsert PostgreSQL smoke hardening. |
| [`Slice 0205`](slices/0205_cx_document_library_smoke_evidence_observability_hardening.md) | `S21-005` CX document library smoke evidence observability hardening. |
| [`Slice 0206`](slices/0206_cx_document_detail_boundary_audit_projection_foundation.md) | `S21-006` CX document detail boundary audit and projection foundation. |
| [`Slice 0207`](slices/0207_cx_document_detail_service_api_wiring.md) | `S21-007` CX document detail service API wiring. |
| [`Slice 0208`](slices/0208_cx_document_detail_postgresql_smoke_evidence.md) | `S21-008` CX document detail PostgreSQL smoke evidence. |
| [`Slice 0209`](slices/0209_ae_to_cx_document_detail_owner_scope_propagation.md) | `S21-009` AE to CX document detail owner-scope propagation. |
| [`Slice 0210`](slices/0210_cx_document_detail_contract_schema_hardening.md) | `S21-010` CX document detail contract/schema hardening. |
| [`Slice 0211`](slices/0211_ae_document_detail_facade_api_wiring.md) | `S22-001` AE document detail facade API wiring. |
| [`Slice 0212`](slices/0212_ae_document_detail_contract_schema_hardening.md) | `S22-002` AE document detail contract/schema hardening. |
| [`Slice 0213`](slices/0213_ae_document_detail_ui_read_model_boundary_decision.md) | `S22-003` AE document detail UI/read-model boundary decision. |
| [`Slice 0214`](slices/0214_ae_document_detail_postgresql_smoke_evidence.md) | `S22-004` AE document detail PostgreSQL smoke evidence. |
| [`Slice 0215`](slices/0215_ae_web_document_surface_audit_refactoring_checkpoint.md) | `S22-005` AE Web document surface audit and refactoring checkpoint. |
| [`Slice 0216`](slices/0216_ae_web_document_detail_client_adapter_foundation.md) | `S22-006` AE Web document detail client adapter foundation. |
| [`Slice 0217`](slices/0217_ae_web_upload_surface_owner_scope_alignment.md) | `S22-007` AE Web upload surface audit and owner-scope alignment. |
| [`Slice 0218`](slices/0218_ae_web_document_scope_retrieval_propagation.md) | `S22-008` AE Web document scope propagation to chat/retrieval surface. |
| [`Slice 0219`](slices/0219_ae_web_upload_client_adapter_foundation.md) | `S22-009` AE Web upload client adapter foundation. |
| [`Slice 0220`](slices/0220_ae_web_retrieval_context_client_adapter_foundation.md) | `S22-010` AE Web retrieval context client adapter foundation. |
| [`Slice 0221`](slices/0221_ae_web_runtime_client_composition_registry.md) | `S23-001` AE Web runtime client composition registry. |
| [`Slice 0222`](slices/0222_ae_web_safe_runtime_config_loader.md) | `S23-002` AE Web safe runtime config loader. |
| [`Slice 0223`](slices/0223_ae_web_fetch_mode_static_regression_harness.md) | `S23-003` AE Web fetch-mode static regression harness. |
| [`Slice 0224`](slices/0224_ae_web_operation_state_model_foundation.md) | `S23-004` AE Web operation state model foundation. |
| [`Slice 0225`](slices/0225_ae_web_error_retry_ux_wiring.md) | `S23-005` AE Web error/retry UX wiring. |
| [`Slice 0226`](slices/0226_ae_web_runtime_diagnostics_surface.md) | `S23-006` AE Web runtime diagnostics surface. |
| [`Slice 0227`](slices/0227_ae_web_static_browser_smoke_evidence_runner.md) | `S23-007` AE Web static browser smoke evidence runner. |
| [`Slice 0228`](slices/0228_ae_web_fetch_mode_protected_smoke_boundary.md) | `S23-008` AE Web fetch-mode protected smoke boundary. |
| [`Slice 0229`](slices/0229_ae_web_fetch_mode_postgresql_smoke_evidence_execution.md) | `S23-009` AE Web fetch-mode PostgreSQL smoke evidence execution. |
| [`Slice 0230`](slices/0230_ae_web_fetch_mode_smoke_evidence_contract_closure.md) | `S23-010` AE Web fetch-mode smoke evidence contract closure. |
| [`Slice 0231`](slices/0231_ae_web_authenticated_runtime_boundary_audit.md) | `S24-001` AE Web authenticated runtime boundary audit. |
| [`Slice 0232`](slices/0232_oa_user_session_token_contract_foundation.md) | `S24-002` OA user session/token contract foundation. |
| [`Slice 0233`](slices/0233_ae_api_browser_user_auth_guard_foundation.md) | `S24-003` AE API browser-user auth guard foundation. |
| [`Slice 0234`](slices/0234_ae_web_session_client_login_state_model.md) | `S24-004` AE Web session client and login state model. |
| [`Slice 0235`](slices/0235_ae_web_authenticated_runtime_composition_gate.md) | `S24-005` AE Web authenticated runtime composition gate. |
| [`Slice 0236`](slices/0236_ae_api_auth_session_facade_routes.md) | `S24-006` AE API auth session facade routes. |
| [`Slice 0237`](slices/0237_ae_web_session_bootstrap_login_state_wiring.md) | `S24-007` AE Web session bootstrap and login-state wiring. |
| [`Slice 0238`](slices/0238_ae_api_authenticated_fetch_route_guard_wiring.md) | `S24-008` AE API authenticated fetch route-guard wiring. |
| [`Slice 0239`](slices/0239_authenticated_fetch_mode_postgresql_smoke_evidence.md) | `S24-009` Authenticated fetch-mode PostgreSQL smoke evidence. |
| [`Slice 0240`](slices/0240_ae_web_authenticated_fetch_mode_closure.md) | `S24-010` AE Web authenticated fetch-mode closure. |
| [`Slice 0241`](slices/0241_oa_identity_auth_boundary_audit.md) | `S25-001` OA identity/auth boundary audit. |
| [`Slice 0242`](slices/0242_oa_tenant_membership_persistence_foundation.md) | `S25-002` OA tenant membership persistence foundation. |
| [`Slice 0243`](slices/0243_oa_session_issuance_api_foundation.md) | `S25-003` OA session issuance API foundation. |
| [`Slice 0244`](slices/0244_oa_session_postgresql_smoke_evidence.md) | `S25-004` OA session PostgreSQL smoke evidence. |
| [`Slice 0245`](slices/0245_oa_ae_session_credential_delivery_boundary_decision.md) | `S25-005` OA-AE session credential delivery boundary decision. |
| [`Slice 0246`](slices/0246_oa_session_introspection_api_foundation.md) | `S25-006` OA session introspection API foundation. |
| [`Slice 0247`](slices/0247_oa_session_revocation_api_foundation.md) | `S25-007` OA session revocation API foundation. |
| [`Slice 0248`](slices/0248_ae_oa_session_client_adapter_foundation.md) | `S25-008` AE OA session client adapter foundation. |
| [`Slice 0249`](slices/0249_ae_auth_session_facade_oa_backed_cookie_wiring.md) | `S25-009` AE auth session facade OA-backed cookie wiring. |
| [`Slice 0250`](slices/0250_oa_backed_ae_auth_postgresql_smoke_evidence.md) | `S25-010` OA-backed AE auth PostgreSQL smoke evidence. |
| [`Slice 0251`](slices/0251_oa_user_bootstrap_login_boundary_audit.md) | `S26-001` OA user bootstrap/login boundary audit. |
| [`Slice 0252`](slices/0252_oa_local_credential_registry_foundation.md) | `S26-002` OA local credential registry foundation. |
| [`Slice 0253`](slices/0253_oa_user_login_api_foundation.md) | `S26-003` OA user login API foundation. |
| [`Slice 0254`](slices/0254_oa_user_login_postgresql_smoke_evidence.md) | `S26-004` OA user login PostgreSQL smoke evidence. |
| [`Slice 0255`](slices/0255_ae_oa_credential_login_client_adapter_foundation.md) | `S26-005` AE OA credential-login client adapter foundation. |
| [`Slice 0256`](slices/0256_ae_auth_session_facade_credential_login_wiring.md) | `S26-006` AE auth session facade credential-login wiring. |
| [`Slice 0257`](slices/0257_ae_credential_login_postgresql_smoke_evidence.md) | `S26-007` AE credential-login PostgreSQL smoke evidence. |
| [`Slice 0258`](slices/0258_ae_web_credential_login_surface_wiring.md) | `S26-008` AE Web credential-login surface wiring. |
| [`Slice 0259`](slices/0259_ae_web_authenticated_session_state_route_guard.md) | `S26-009` AE Web authenticated session state route guard. |
| [`Slice 0260`](slices/0260_ae_web_credential_login_postgresql_smoke_evidence.md) | `S26-010` AE Web credential-login PostgreSQL smoke evidence. |
| [`Slice 0261`](slices/0261_ae_web_credential_login_browser_harness_foundation.md) | `S27-001` AE Web credential-login browser harness foundation. |
| [`Slice 0262`](slices/0262_ae_web_credential_login_browser_smoke_boundary.md) | `S27-002` AE Web credential-login browser smoke boundary. |
| [`Slice 0263`](slices/0263_ae_web_credential_login_browser_harness_smoke.md) | `S27-003` AE Web credential-login browser harness smoke. |
| [`Slice 0264`](slices/0264_ae_web_credential_login_browser_execution_readiness.md) | `S27-004` AE Web credential-login browser execution readiness. |
| [`Slice 0265`](slices/0265_ae_web_credential_login_browser_live_smoke_execution.md) | `S27-005` AE Web credential-login browser live smoke execution. |
| [`Slice 0266`](slices/0266_ae_web_credential_login_browser_postgres_evidence_hardening.md) | `S27-006` AE Web credential-login browser PostgreSQL evidence hardening. |
| [`Slice 0267`](slices/0267_ae_web_credential_login_browser_operator_profile.md) | `S27-007` AE Web credential-login browser operator profile. |
| [`Slice 0268`](slices/0268_ae_web_same_origin_runtime_boundary.md) | `S27-008` AE Web same-origin runtime boundary. |
| [`Slice 0269`](slices/0269_ae_web_playwright_readiness_foundation.md) | `S27-009` AE Web Playwright readiness foundation. |
| [`Slice 0270`](slices/0270_ae_web_credential_login_playwright_postgresql_smoke.md) | `S27-010` AE Web credential-login Playwright PostgreSQL smoke. |
| [`Slice 0271`](slices/0271_ae_web_post_login_document_workflow_audit.md) | `S28-001` AE Web post-login document workflow audit. |
| [`Slice 0272`](slices/0272_ae_web_authenticated_upload_metadata_surface_hardening.md) | `S28-002` AE Web authenticated upload metadata surface hardening. |
| [`Slice 0273`](slices/0273_ae_web_authenticated_upload_fetch_wiring.md) | `S28-003` AE Web authenticated upload fetch wiring. |
| [`Slice 0274`](slices/0274_ae_web_authenticated_upload_playwright_postgresql_smoke.md) | `S28-004` AE Web authenticated upload Playwright PostgreSQL smoke. |
| [`Slice 0275`](slices/0275_cx_source_file_materialization_boundary_audit.md) | `S28-005` CX source-file materialization boundary audit. |
| [`Slice 0276`](slices/0276_cx_source_file_byte_materialization_api_hardening.md) | `S28-006` CX source-file byte materialization API hardening. |
| [`Slice 0277`](slices/0277_ae_multipart_upload_facade_contract.md) | `S28-007` AE multipart upload facade contract. |
| [`Slice 0278`](slices/0278_ae_web_formdata_upload_wiring.md) | `S28-008` AE Web FormData upload wiring. |
| [`Slice 0279`](slices/0279_ae_web_source_file_upload_playwright_postgresql_smoke.md) | `S28-009` AE Web source-file upload Playwright PostgreSQL smoke. |
| [`Slice 0280`](slices/0280_cx_uploaded_source_extraction_readiness_audit.md) | `S28-010` CX uploaded source extraction readiness audit. |
| [`Slice 0281`](slices/0281_cx_source_file_reader_fallback_audit.md) | `S29-001` CX source-file reader fallback audit. |
| [`Slice 0282`](slices/0282_cx_extraction_materialized_source_fallback.md) | `S29-002` CX extraction materialized-source fallback implementation. |
| [`Slice 0283`](slices/0283_cx_uploaded_source_extraction_postgresql_smoke.md) | `S29-003` CX uploaded source extraction PostgreSQL smoke evidence. |
| [`Slice 0284`](slices/0284_cx_extractor_backend_gap_audit.md) | `S29-004` CX extractor backend gap audit and refactoring checkpoint. |
| [`Slice 0285`](slices/0285_cx_pdf_extraction_adapter_foundation.md) | `S29-005` CX PDF extraction adapter foundation. |
| [`Slice 0286`](slices/0286_cx_docx_extraction_adapter_foundation.md) | `S29-006` CX DOCX extraction adapter foundation. |
| [`Slice 0287`](slices/0287_cx_office_extraction_adapter_foundation.md) | `S29-007` CX PPTX/XLSX Office extraction adapter foundation. |
| [`Slice 0288`](slices/0288_cx_real_document_extraction_postgresql_smoke.md) | `S29-008` CX real document extraction PostgreSQL smoke evidence. |
| [`Slice 0289`](slices/0289_cx_extracted_markdown_normalization_contract.md) | `S29-009` CX extracted Markdown normalization and contract hardening. |
| [`Slice 0290`](slices/0290_cx_real_document_processing_pipeline_postgresql_smoke.md) | `S29-010` CX real document processing pipeline PostgreSQL smoke evidence. |
| [`Slice 0291`](slices/0291_protected_remote_provider_live_smoke_evidence.md) | `S30-001` Protected remote provider live smoke evidence. |
| [`Slice 0292`](slices/0292_openai_compatible_provider_config_profile_hardening.md) | `S30-002` OpenAI-compatible provider config/profile hardening. |
| [`Slice 0293`](slices/0293_cx_processing_pipeline_remote_embedding_postgresql_smoke.md) | `S30-003` CX processing pipeline remote embedding PostgreSQL smoke evidence. |
| [`Slice 0294`](slices/0294_cx_retrieval_remote_reranker_postgresql_smoke.md) | `S30-004` CX retrieval remote reranker PostgreSQL smoke evidence. |
| [`Slice 0295`](slices/0295_protected_live_rag_postgresql_smoke.md) | `S30-005` Protected live RAG PostgreSQL smoke evidence. |
| [`Slice 0296`](slices/0296_protected_live_rag_failure_diagnostics.md) | `S30-006` Protected live RAG failure diagnostics hardening. |
| [`Slice 0297`](slices/0297_live_rag_score_calibration_checkpoint.md) | `S30-007` Live RAG score calibration evidence checkpoint. |
| [`Slice 0298`](slices/0298_remote_provider_live_timeout_profile.md) | `S30-008` Remote provider live timeout profile hardening. |
| [`Slice 0299`](slices/0299_live_rag_score_calibration_ag_observability.md) | `S30-009` Live RAG score calibration AG observability surface. |
| [`Slice 0300`](slices/0300_retrieval_threshold_decision_checkpoint.md) | `S30-010` Retrieval threshold decision checkpoint. |
| [`Slice 0301`](slices/0301_retrieval_calibration_sample_rollup_query.md) | `S31-001` Retrieval calibration sample rollup/query foundation. |
| [`Slice 0302`](slices/0302_protected_live_rag_score_sample_collection_smoke.md) | `S31-002` Protected live RAG score sample collection smoke. |
| [`Slice 0303`](slices/0303_retrieval_threshold_decision_ag_projection.md) | `S31-003` Retrieval threshold decision AG projection. |

Each implementation slice should leave behind the smallest useful evidence:
quality output, contract validation output, API smoke output, UI screenshot, or
documentation-only checks, depending on what changed.
