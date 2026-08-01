# Source Material Inventory

Status: Draft seed for Slice 419.

This inventory registers the 15 source documents uploaded to
`artifacts/nex-platform/source-materials/`. The raw source files remain outside
the committed documentation set unless the user explicitly approves committing
them. The committed docs should reference source IDs, hashes, and distilled
decisions rather than copying large source material wholesale.

## Intake Summary

| Field | Value |
| --- | --- |
| Source directory | `artifacts/nex-platform/source-materials/` |
| Uploaded source files | 15 Markdown files |
| Total line count | 24,342 lines |
| Commit policy | Do not commit raw source files by default |
| Review method | Inventory, distill, map, decide, normalize, trace |
| First scope filter | `NP-SRC-13` 2-week barebone SRS |
| Broad cross-check | `NP-SRC-01` full platform SRS |

## Registered Files

| Source ID | File | Lines | Bytes | SHA-256 Prefix | Primary Service Lane | Review Priority |
| --- | --- | ---: | ---: | --- | --- | --- |
| `NP-SRC-01` | `01_260723_NeX_Platform_v1.11_SRS.md` | 3,464 | 127,156 | `6d8af1cd9f8e` | Shared SRS | P3 broad cross-check |
| `NP-SRC-02` | `02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md` | 1,211 | 20,423 | `76ec309c9e6c` | Shared contract | P1 contract |
| `NP-SRC-03` | `03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md` | 2,160 | 41,031 | `29d6523ee4a6` | Shared foundation | P1 contract |
| `NP-SRC-04` | `04_260723_NeX_Platform_Initial_Minimal_Baseline_v0.7.md` | 1,677 | 33,839 | `9fd35ca830b6` | Shared baseline | P1 MVP |
| `NP-SRC-05` | `05_260723_NeX_Platform_Service_Lifecycle_Host_Control_Design_v1.2.md` | 1,407 | 26,501 | `ee9e9082c4aa` | Lifecycle/operations | P3 deferred |
| `NP-SRC-06` | `06_260723_NeX_Platform_Installation_Bootstrap_License_Security_Baseline_Design_v1.0.md` | 1,153 | 16,843 | `57017da93cff` | Installation/security | P3 deferred |
| `NP-SRC-07` | `07_260723_NeX_OA_Operations_Administration_Design_v1.2.md` | 1,739 | 37,145 | `95d3fa9a5774` | `nex-oa` identity boundary | P1 conflict review |
| `NP-SRC-08` | `08_260723_NeX_AG_Operations_Administration_Design_v1.6.md` | 1,692 | 41,146 | `80587282bd8f` | `nex-ag` admin & governance | P1 MVP |
| `NP-SRC-09` | `09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md` | 2,161 | 36,545 | `704d8409db7e` | `nex-cx` content lifecycle | P1 MVP |
| `NP-SRC-10` | `10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md` | 2,090 | 41,681 | `04d334307f69` | `nex-ae-web`, `nex-ae-api` | P1 MVP |
| `NP-SRC-11` | `11_260723_NeX_MO_Model_Operations_Design_v1.3.md` | 2,007 | 37,651 | `f7c614ce29ad` | `nex-mo` model operations | P1 MVP |
| `NP-SRC-12` | `12_260723_NeX_Platform_v2.0_Communication_Intelligence_Customer_Timeline_Concept_v0.1.md` | 718 | 13,332 | `a5264c70303a` | v2.0 roadmap | P4 deferred |
| `NP-SRC-13` | `13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md` | 1,258 | 23,868 | `5fd6b3492216` | 2-week MVP | P0 scope gate |
| `NP-SRC-14` | `14_260724_NeX_Platform_Common_Functions_Definition_v1.1.md` | 809 | 12,123 | `fa0ba6ca241e` | Shared functions | P2 reconcile |
| `NP-SRC-15` | `15_260724_NeX_Platform_Development_Environment_Directory_Structure_v1.1.md` | 796 | 12,763 | `0d7334048ed3` | Development environment | P1 MVP |

## Priority Lanes

| Priority | Documents | Reason |
| --- | --- | --- |
| P0 scope gate | `NP-SRC-13` | The reduced 2-week MVP document should keep the first NeX-Platform baseline small. Distilled in [2-Week MVP Capability Map](../../10_2week_mvp_capability_map.md). |
| P1 MVP/contract | `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-04`, `NP-SRC-07`, `NP-SRC-08`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11`, `NP-SRC-15` | These define the minimum service spine, contracts, service responsibilities, and development setup. `NP-SRC-02` and `NP-SRC-03` are distilled in [Common Contract Freeze Candidate Map](../../11_common_contract_freeze_candidate_map.md). `NP-SRC-07` through `NP-SRC-11` are distilled in [Service Boundary Decision Record](../../12_service_boundary_decision_record.md). |
| P2 reconcile | `NP-SRC-14` | Common functions must be reconciled after service ownership is fixed. |
| P3 deferred hardening | `NP-SRC-01`, `NP-SRC-05`, `NP-SRC-06` | These are important but broad enough to bloat the first baseline if read too early. |
| P4 roadmap | `NP-SRC-12` | v2.0 communication intelligence should remain a future extension unless a current MVP hook is required. |

## Initial Conflict Notes

| Source | Note | Handling |
| --- | --- | --- |
| `NP-SRC-07` | The file name uses `NeX_OA_Operations_Administration`, but the user-confirmed boundary defines `nex-oa` as NeX Open Auth. | Review identity/auth content first and move operations/admin content to `nex-ag` if needed. |
| `NP-SRC-01` | Full SRS likely duplicates many smaller focused documents. | Use it after P0/P1 review as a completeness cross-check. |
| `NP-SRC-12` | v2.0 communication/customer timeline scope can pull the MVP away from document intelligence. | Keep as roadmap/deferred unless it reveals a required extension point. |
| `NP-SRC-10` | AE workspace material includes broad future agent capability. | Freeze bounded MVP agent orchestration in [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md); defer autonomous multi-step domain agents. |
| `NP-SRC-09` | CX material includes broad search, generation, structured draft, and artifact scope. | Freeze the CX-to-AE retrieval/evidence package in [CX-to-AE Retrieval Context Package Contract](../../14_cx_ae_retrieval_context_package_contract.md); keep final user-facing generation orchestration in AE. |
| `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11` | Source documents state that AE should not call MO directly for document generation. | Reconcile direct-call wording in [Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md): AE orchestrates, CX mediates document-grounded generation, MO executes providers. |
| `NP-SRC-02`, `NP-SRC-09`, `NP-SRC-10` | Source documents repeat a compact NeX-CX Generation Request schema. | Freeze the expanded AE-to-CX request package in [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md). |
| `NP-SRC-11` | MO material defines stable generation API, alias resolution, admission, routing, streaming, cancel, and usage metadata. | Freeze the CX-to-MO provider-facing generation contract in [CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md). |
| `NP-SRC-02`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11` | Source documents connect generation request, evidence, prompt package hash, structured draft, citation, and MO usage metadata. | Freeze the CX execution and lineage record in [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md). |
| `NP-SRC-02`, `NP-SRC-09`, `NP-SRC-10` | Source documents require generated answers and documents to remain source-grounded, template-aware, and renderable. | Freeze structured draft sections, blocks, citation claims, validation statuses, and safe read shape in [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md). |
| `NP-SRC-02`, `NP-SRC-10`, `NP-SRC-13` | Source documents and PCX lessons require generated documents to become previewable/downloadable workspace artifacts without moving corpus ownership out of CX. | Freeze AE artifact records, versions, render jobs, files, links, and source refs in [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md). |
| `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11` | Long-running generation needs consistent status, stage, progress, streaming, and redacted timeline events across AE, CX, MO, and AG. | Freeze generation progress event envelope and stage/event taxonomy in [Generation Progress Event Contract](21_generation_progress_event_contract.md). |
| `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11` | Failed or incomplete generation needs explicit retry, repair, regenerate, sectional retry, and warning acceptance rules. | Freeze recovery action taxonomy, failure classes, lineage fields, and policy hashes in [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md). |
| `NP-SRC-02`, `NP-SRC-10`, `NP-SRC-13` | Generated artifacts should be visible in chat as previewable/downloadable, versioned, source-aware workspace objects. | Freeze chat artifact card, link, source drilldown, recovery action, localization, and accessibility requirements in [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md). |
| `NP-SRC-02`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-13` | Template selection, prompt version, output schema, artifact intent, and provider capability can drift unless compatibility is explicit. | Freeze valid generation combinations and mismatch handling in [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md). |
| `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-08`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11` | Operators need generation and artifact evidence without violating service ownership or leaking prompts/provider secrets. | Freeze AG read-only dashboard, audit projection, filter, redaction, and operator note requirements in [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md). |
| `NP-SRC-02`, `NP-SRC-03` | Generation contracts need implementation-ready schema names and validation rules before OpenAPI and contract tests. | Seed the generation JSON Schema catalog and shared definitions in [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md). |
| `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11` | Generation implementation needs service-owned endpoint names, headers, idempotency, streaming/polling, and error codes before code begins. | Seed the generation OpenAPI route surface in [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md). |
| `NP-SRC-02`, `NP-SRC-03`, PCX slice history | The generation step needs a mock-first acceptance spine before live provider or UI work starts. | Freeze generation E2E scenarios, contract test matrix, mock provider requirements, and evidence criteria in [Generation E2E Acceptance + Contract Test Plan](../../28_generation_e2e_acceptance_contract_test_plan.md). |
| `NP-SRC-13`, `NP-SRC-02`, `NP-SRC-03`, PCX slice history | The distilled decisions need one buildable MVP SRS before service-specific requirement partitioning. | Assemble the first MVP SRS in [NeX-Platform MVP SRS v0.1 Assembly](../../29_nex_platform_mvp_srs_v0_1_assembly.md). |
| MVP SRS assembly and service boundary records | Implementation needs stable service-owned requirement IDs before backlog slicing. | Partition the MVP SRS by service in [Service-Specific Requirement Partition](../../30_service_specific_requirement_partition.md). |
| Source inventory, MVP SRS, service partition, PCX lessons | Requirements need traceability into contracts, tests, and evidence before implementation starts. | Seed source-to-requirement-to-test traceability in [Cross-Service Traceability Matrix](../../31_cross_service_traceability_matrix.md). |
| `NP-SRC-15`, PCX dev/test/live operations lessons | Implementation needs a frozen local/test/live development profile before repository bootstrap. | Freeze environment profiles, database naming, provider modes, and setup guardrails in [Platform Development Environment Freeze](../../32_platform_development_environment_freeze.md). |
| Common contracts, JSON Schema seed, OpenAPI seed | Services need a shared contract package layout before schema/OpenAPI implementation starts. | Freeze schema, OpenAPI, examples, fixtures, ownership, and versioning policy in [Common Schema + Contract Package Layout](../../33_common_schema_contract_package_layout.md). |
| PCX quality gate and smoke evidence lessons | MVP implementation needs a concrete testing policy before CI and service bootstrap work begins. | Freeze single-pass quality gate, branch coverage, contract tests, mock E2E, live smoke, UI evidence, and docs-only rules in [Testing Strategy v0.1 Detail](../../34_testing_strategy_v0_1_detail.md). |
| `NP-SRC-10`, `NP-SRC-08`, PCX UI lessons | AE and AG need a shared UI standard before chat workspace and admin dashboard implementation. | Expand MVP design principles, tokens, components, status rules, copy, accessibility, and screenshot evidence in [Design System v0.1 Expansion](../../35_design_system_v0_1_expansion.md). |
| MVP SRS, service partition, environment, contract layout, testing, design system | The documentation set needs a concrete first implementation roadmap before Slice 447+ code work starts. | Assemble the 2-week roadmap, Sprint 1 backlog, evidence list, and stop conditions in [Implementation Roadmap + First Sprint Backlog](../../36_implementation_roadmap_first_sprint_backlog.md). |

## Next Review Sequence

1. Completed: Distill `NP-SRC-13` into a small MVP capability map.
2. Completed: Reconcile `NP-SRC-02` and `NP-SRC-03` into common contract and foundation rules.
3. Completed: Map `NP-SRC-07` through `NP-SRC-11` to the user-confirmed service boundaries.
4. Completed: Freeze bounded `nex-ae-api` agent orchestration from `NP-SRC-10`.
5. Completed: Freeze CX-to-AE retrieval context package direction from `NP-SRC-09`.
6. Completed: Reconcile document-grounded generation routing through CX before MO.
7. Completed: Freeze AE-to-CX generation request package from `NP-SRC-02`,
   `NP-SRC-09`, and `NP-SRC-10`.
8. Completed: Freeze CX-to-MO generation provider contract from `NP-SRC-11`.
9. Completed: Freeze CX generation execution and lineage record across request,
   evidence, prompt package, MO call, draft, and validation refs.
10. Completed: Freeze structured draft and citation schema across generated
    sections, blocks, citation claims, evidence anchors, and validation status.
11. Completed: Freeze AE artifact rendering handoff across artifact records,
    versions, render jobs, files, preview/download links, and CX source refs.
12. Completed: Freeze generation progress event contract across event envelope,
    stage taxonomy, streaming/polling, redaction, and AG projection rules.
13. Completed: Freeze generation failure and repair/retry policy across
    failure classes, recovery actions, lineage, policy hashes, and UX behavior.
14. Completed: Freeze chat workspace artifact link requirements across artifact
    cards, source drilldown, quality badges, actions, and localization.
15. Completed: Freeze prompt/template/output compatibility across execution
    modes, templates, prompt contracts, output schemas, artifact intents,
    formats, quality policies, and provider capabilities.
16. Completed: Freeze AG generation and artifact audit dashboard requirements
    across timeline, artifact lineage, citations, compatibility, downloads,
    provider usage, redaction, and operator notes.
17. Completed: Seed generation JSON Schema catalog, shared definitions,
    validation posture, and contract-test derivation points.
18. Completed: Seed generation OpenAPI endpoint surface across AE, CX, MO, OA,
    and AG with headers, idempotency, streaming/polling, errors, and tests.
19. Completed: Freeze generation E2E acceptance and contract test plan across
    mock provider scenarios, service boundary tests, recovery branches, artifact
    links, and AG audit redaction.
20. Completed: Assemble NeX-Platform MVP SRS v0.1 across service requirements,
    vertical acceptance, non-functional requirements, deferrals, and open items.
21. Completed: Partition MVP SRS requirements into service-owned ID families,
    priorities, interfaces, dependencies, and cross-service dependency order.
22. Completed: Seed cross-service traceability from source material and PCX
    lessons to requirements, contracts, tests, evidence, and coverage gaps.
23. Completed: Freeze development environment assumptions across workspace
    layout, runtime baseline, profiles, service DBs, provider modes, and setup
    guardrails.
24. Completed: Freeze common schema and contract package layout across schemas,
    OpenAPI, examples, fixtures, ownership, versioning, and test hooks.
25. Completed: Detail MVP testing strategy across quality gate, branch coverage,
    contract fixtures, mock E2E, live smoke, UI evidence, release evidence, and
    docs-only rules.
26. Completed: Expand MVP design system across principles, tokens, layouts,
    component states, status badges, copy, accessibility, evidence, and
    anti-patterns.
27. Completed: Assemble implementation roadmap and first sprint backlog across
    service skeleton, quality gate, contract package, OA claim check, MO mock,
    CX facade, AE interaction, AG readiness, evidence, and stop conditions.
28. Use `NP-SRC-01` as a final cross-check for missing requirements.
29. Keep `NP-SRC-05`, `NP-SRC-06`, and `NP-SRC-12` mostly deferred unless they reveal an MVP blocker.
