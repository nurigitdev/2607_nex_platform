# NeX-Platform Documentation Workspace

Status: Draft bootstrap for Slice 418.

This workspace captures the minimum documentation framework needed to turn the
NeX-PCX pre-CX experiment into actionable NeX-Platform planning material.
NeX-PCX source code direct reuse is not the primary goal. The primary goal is to
reuse the validated requirements, implementation lessons, operational evidence,
and slice history as design input for a smaller, buildable platform baseline.

## Reading Order

1. [Documentation Framework](00_documentation_framework.md)
2. [Service Boundary](01_service_boundary.md)
3. [MVP SRS Skeleton](02_mvp_srs_skeleton.md)
4. [Design System Skeleton](03_design_system_skeleton.md)
5. [Development Environment Skeleton](04_development_environment_skeleton.md)
6. [Testing Strategy Skeleton](05_testing_strategy_skeleton.md)
7. [Common Modules Skeleton](06_common_modules_skeleton.md)
8. [PCX Lessons Learned Seed](07_pcx_lessons_learned_seed.md)
9. [Source Document Review Matrix](08_source_document_review_matrix.md)
10. [Source Material Inventory](09_source_material_inventory.md)
11. [2-Week MVP Capability Map](10_2week_mvp_capability_map.md)
12. [Common Contract Freeze Candidate Map](11_common_contract_freeze_candidate_map.md)
13. [Service Boundary Decision Record](12_service_boundary_decision_record.md)
14. [AE Agent Orchestration Contract](13_ae_agent_orchestration_contract.md)
15. [CX-to-AE Retrieval Context Package Contract](14_cx_ae_retrieval_context_package_contract.md)
16. [Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md)
17. [AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md)
18. [CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md)
19. [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
20. [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md)
21. [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
22. [Generation Progress Event Contract](21_generation_progress_event_contract.md)
23. [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)
24. [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)
25. [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md)
26. [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md)
27. [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md)
28. [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md)
29. [Generation E2E Acceptance + Contract Test Plan](28_generation_e2e_acceptance_contract_test_plan.md)
30. [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md)
31. [Service-Specific Requirement Partition](30_service_specific_requirement_partition.md)
32. [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md)
33. [Platform Development Environment Freeze](32_platform_development_environment_freeze.md)
34. [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md)
35. [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md)
36. [Design System v0.1 Expansion](35_design_system_v0_1_expansion.md)
37. [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md)

## Platform Services

The current target service split is:

| Service | Role |
| --- | --- |
| `nex-cx` | Content experience repository: source files, extracted text, chunks, embeddings, BM25, graph, and retrieval APIs. |
| `nex-ae-web` | User-facing workspace UI/UX for chat, search, generation, summaries, artifacts, and downloads. |
| `nex-ae-api` | Agent execution backend for intent routing, retrieval orchestration, generation orchestration, formatting, and artifact creation. |
| `nex-mo` | Model operations service for embedding, reranker, generation provider connectivity and monitoring. |
| `nex-oa` | NeX Open Auth: user auth, service auth, token/session/API key management, permission claims, and trust boundaries. |
| `nex-ag` | Admin & governance service for operations, logs, policies, monitoring, readiness, and audit views. |

## Source Inputs

This framework is designed to absorb four source streams:

| Source | How It Will Be Used |
| --- | --- |
| NeX-PCX SRS | Seed requirements and requirement naming patterns. |
| NeX-PCX slice/commit history | Evidence for what was actually implemented, tested, or deferred. |
| 400,000-token platform design document | Broad architecture ideas to distill through the review matrix. |
| Reduced 2-week MVP document | Scope constraint for the first buildable platform baseline. |

## Immediate Output

Slice 418 created the skeleton and review method. Slice 419 registered the
uploaded source material inventory and seeded the review matrix. Slice 420
distilled the 2-week barebone SRS into a service-owned MVP capability map.
Slice 421 distilled canonical terminology, state, API, error, job, logging, and
trace contracts into freeze candidates. Slice 422 reconciled the service-specific
source documents into a boundary decision record and ownership freeze candidate.
Slice 423 defined `nex-ae-api` as the bounded user-facing agent orchestrator for
intent, retrieval, prompt/template packaging, generation calls, artifact links,
and chat workspace responses. Slice 424 froze the first CX-to-AE retrieval
context package direction: AE requests corpus-grounded evidence from CX, CX
returns permission-filtered evidence/no-answer metadata, and AE owns the next
prompt/template/generation hand-off. Slice 425 reconciled generation routing so
document-grounded generation is AE-orchestrated but CX-mediated before MO
provider execution. Slice 426 froze the first AE-to-CX generation request
package so AE can send intent, template, output, quality, and retrieval package
references to CX without leaking provider runtime ownership. Slice 427 froze the
first CX-to-MO generation provider contract so CX can call MO by stable alias
while MO owns admission, routing, provider execution, streaming/cancel, and
usage metadata. Slice 428 froze the CX generation execution record and lineage
contract so retrieval packages, prompt package hashes, MO calls, structured
draft validation, citation validation, and safe AE/AG read views remain tied
together. Slice 429 froze the structured draft and citation schema contract so
CX can validate sections, blocks, citation claims, evidence anchors, and
template completeness before AE renders artifacts. Slice 430 froze the AE
artifact rendering handoff contract so validated CX drafts can become AE-owned
artifact records, render jobs, files, previews, downloads, and chat links
without losing generation lineage. Slice 431 froze the generation progress event
contract so AE, CX, MO, and AG can expose the same stage, event, status, and
redacted metadata timeline for long-running generation. Slice 432 froze the
generation failure, repair, and retry policy so failed or incomplete generation
can recover through retry, repair, regenerate, sectional retry, or warning
acceptance without losing lineage. Slice 433 froze chat workspace artifact link
requirements so generated artifacts appear as versioned preview/download cards
inside AE chat while keeping source, quality, progress, and recovery lineage
visible. Slice 434 froze the prompt/template/output compatibility matrix so AE
and CX can reject mismatched generation modes, templates, prompt contracts,
output schemas, target formats, and provider capabilities before a provider
call. Slice 435 froze the AG generation and artifact audit dashboard
requirements so operations can inspect generation timeline, artifact lineage,
citations, compatibility, downloads, provider usage, and recovery events through
service APIs. Slice 436 seeded the generation JSON Schema catalog so AE, CX, MO,
and AG can validate request, response, event, lineage, artifact, compatibility,
and audit payloads before endpoint implementation. Slice 437 seeded the
generation OpenAPI endpoint surface so AE, CX, MO, OA, and AG have a concrete
service-owned route map for generation orchestration, artifact handling,
provider execution, and governance reads. Slice 438 froze the generation E2E
acceptance and contract test plan so retrieval packages, generation execution,
structured drafts, artifacts, progress events, recovery, compatibility, and AG
audit can be verified as one mock-first MVP flow. Slice 439 assembled the first
NeX-Platform MVP SRS v0.1 draft across OA, CX, MO, AE API, AE web, AG,
cross-service requirements, acceptance criteria, non-functional requirements,
deferrals, and open decisions. Slice 440 partitioned the MVP SRS into
service-owned requirement IDs, interfaces, dependencies, priorities, shared
platform requirements, and cross-service dependency order. Slice 441 seeded the
cross-service traceability matrix from source material and PCX lessons to
requirement IDs, service owners, contracts, tests, evidence artifacts, and
coverage gaps. Slice 442 froze the first development environment assumptions:
monorepo-style workspace, service-owned packages and databases, local mock by
default, live provider opt-in, profile-specific configuration, and setup
guardrails. Slice 443 froze the common schema and contract package layout for
versioned JSON Schema, OpenAPI files, examples, fixtures, ownership rules,
versioning policy, and contract-test hooks. Slice 444 detailed the MVP testing
strategy across single-pass quality gate, statement/branch coverage, contract
fixtures, mock E2E, live smoke, UI evidence, release evidence, and docs-only
slice rules. Slice 445 expanded the design system into MVP-ready principles,
tokens, layouts, components, status badge rules, Korean/English copy guidance,
accessibility requirements, UI evidence, and anti-patterns. Slice 446 assembled
the implementation roadmap and first sprint backlog so the MVP can move from
documentation into a mock-first service skeleton, contract package, OA claim
check, MO mock provider, CX facade, AE interaction stub, and AG readiness path.
Later slices should fill the skeleton with source-backed decisions instead of
copying large documents wholesale.
