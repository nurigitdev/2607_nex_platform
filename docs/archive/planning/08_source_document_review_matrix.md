# Source Document Review Matrix

Status: Draft bootstrap.

This matrix is the intake format for large design material. It is intended for
the existing 400,000-token platform design document, the reduced 2-week MVP
document, PCX SRS material, and NeX-PCX commit history. The goal is to distill
requirements and decisions, not to copy source text wholesale.

## Review Columns

| Column | Description |
| --- | --- |
| Source document | File name, version, or source identifier. |
| Source section | Heading, page, anchor, or commit reference. |
| Claim or requirement | Concise statement extracted from the source. |
| PCX evidence | Related PCX implementation, test, smoke evidence, screenshot, or commit. |
| Target service | `nex-cx`, `nex-ae-web`, `nex-ae-api`, `nex-mo`, `nex-oa`, `nex-ag`, or shared. |
| MVP/defer | `MVP`, `Deferred`, `Rejected`, `Duplicate`, or `Needs Review`. |
| Design impact | SRS, architecture, data model, API, UI, operations, testing, or common module. |
| Open question | What must be decided before implementation. |
| Decision | Accepted decision and rationale. |
| Owner/status | Current owner and review status. |

## Matrix Template

| Source document | Source section | Claim or requirement | PCX evidence | Target service | MVP/defer | Design impact | Open question | Decision | Owner/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 400,000-token design document | TBD | TBD | TBD | TBD | Needs Review | TBD | TBD | TBD | Open |
| 2-week MVP document | TBD | TBD | TBD | TBD | Needs Review | TBD | TBD | TBD | Open |
| PCX SRS | TBD | TBD | TBD | TBD | Needs Review | TBD | TBD | TBD | Open |
| NeX-PCX commit history | TBD | TBD | TBD | TBD | Needs Review | TBD | TBD | TBD | Open |

## Registered Source Materials

The 15 uploaded source files are registered in
[Source Material Inventory](09_source_material_inventory.md). Use the source IDs
below when adding review rows.

| Source ID | Source document | Primary lane |
| --- | --- | --- |
| `NP-SRC-01` | `01_260723_NeX_Platform_v1.11_SRS.md` | Full SRS distillation |
| `NP-SRC-02` | `02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md` | Common contract |
| `NP-SRC-03` | `03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md` | Common foundation |
| `NP-SRC-04` | `04_260723_NeX_Platform_Initial_Minimal_Baseline_v0.7.md` | Minimal baseline |
| `NP-SRC-05` | `05_260723_NeX_Platform_Service_Lifecycle_Host_Control_Design_v1.2.md` | Lifecycle and host control |
| `NP-SRC-06` | `06_260723_NeX_Platform_Installation_Bootstrap_License_Security_Baseline_Design_v1.0.md` | Installation and security |
| `NP-SRC-07` | `07_260723_NeX_OA_Operations_Administration_Design_v1.2.md` | Identity boundary review |
| `NP-SRC-08` | `08_260723_NeX_AG_Operations_Administration_Design_v1.6.md` | Admin and governance |
| `NP-SRC-09` | `09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md` | Context and knowledge lifecycle |
| `NP-SRC-10` | `10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md` | Assistant workspace |
| `NP-SRC-11` | `11_260723_NeX_MO_Model_Operations_Design_v1.3.md` | Model operations |
| `NP-SRC-12` | `12_260723_NeX_Platform_v2.0_Communication_Intelligence_Customer_Timeline_Concept_v0.1.md` | Deferred v2.0 concept |
| `NP-SRC-13` | `13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md` | 2-week MVP constraint |
| `NP-SRC-14` | `14_260724_NeX_Platform_Common_Functions_Definition_v1.1.md` | Common functions |
| `NP-SRC-15` | `15_260724_NeX_Platform_Development_Environment_Directory_Structure_v1.1.md` | Development environment |

## Seed Review Rows

| Source document | Source section | Claim or requirement | PCX evidence | Target service | MVP/defer | Design impact | Open question | Decision | Owner/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `NP-SRC-13` | Full document | The 2-week barebone SRS should constrain the first platform baseline. | NeX-PCX proved that scope grows quickly when search, generation, operations, and providers are built together. | Shared | MVP | SRS, backlog | Which PCX features are mandatory for the first usable NeX-Platform slice? | Use as the first scope filter; distilled in [2-Week MVP Capability Map](../../10_2week_mvp_capability_map.md). | Seeded |
| `NP-SRC-04` | Baseline goals and service baselines | The initial baseline should include service spine, mock scenario, readiness, and E2E acceptance. | PCX foreground/smoke/readiness slices showed the value of visible startup and validation evidence. | Shared | MVP | Architecture, testing | Should the first build use one repo or service repositories? | Keep as baseline architecture input. | Open |
| `NP-SRC-02` | Canonical terminology, states, API contract | Shared terms, states, error response, pagination, idempotency, and schema versioning should be normalized early. | PCX accumulated many API/UI slices where stable naming reduced rework. | Shared | MVP | Common module, API | Which contract fields must be frozen before service implementation? | Distilled in [Common Contract Freeze Candidate Map](../../11_common_contract_freeze_candidate_map.md). | Seeded |
| `NP-SRC-03` | Common foundation | Foundation packages should define logging, settings, job runtime, trace, database, and design system boundaries. | PCX quality gate, logging, job queue, and runtime scripts became cross-cutting patterns. | Shared | MVP | Common module, testing | What belongs in a shared package vs service-local code? | Distilled in [Common Contract Freeze Candidate Map](../../11_common_contract_freeze_candidate_map.md); freeze contracts before package shape. | Seeded |
| `NP-SRC-15` | Development environment and directory structure | Development and test structure should be reproducible before feature coding starts. | PCX used explicit venv, PostgreSQL URLs, migrations, and single-pass quality gate. | Shared | MVP | Development environment | Monorepo vs multi-repo decision is still open. | Use as environment skeleton input. | Open |
| `NP-SRC-07` | Full document | Existing NeX-OA material must be reconciled with the user-confirmed `nex-open-auth` boundary. | PCX permission simulation showed auth and visibility claims must be explicit. | `nex-oa` | MVP | Trust boundary, SRS | Does the source document include operations/admin concerns that should move to `nex-ag`? | Distilled in [Service Boundary Decision Record](../../12_service_boundary_decision_record.md); OA is NeX Open Auth. | Seeded |
| `NP-SRC-08` | Operations/admin design | Admin & governance needs logs, policy settings, monitoring, service lifecycle, audit, and dashboards. | PCX operations slices covered logs, readiness, provider metrics, startup/shutdown, and evidence exports. | `nex-ag` | MVP | Admin UI, operations | Which governance controls are MVP vs deferred hardening? | Distilled in [Service Boundary Decision Record](../../12_service_boundary_decision_record.md); keep host control as deferred unless required. | Seeded |
| `NP-SRC-09` | Context/knowledge lifecycle | `nex-cx` should own original source, extraction artifacts, chunks, embedding, BM25, graph, retrieval evidence, and lifecycle. | PCX ingestion, extraction, BM25, hybrid search, rerank, source context, and no-answer slices validated this domain. | `nex-cx` | MVP | Data model, retrieval API | Which graph features are MVP and which are deferred? | Distilled in [Service Boundary Decision Record](../../12_service_boundary_decision_record.md), [CX-to-AE Retrieval Context Package Contract](../../14_cx_ae_retrieval_context_package_contract.md), [Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md), [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md), [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md), and [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md); CX owns retrieval/evidence, mediates document-grounded generation, and validates structured drafts/citations. | Seeded |
| `NP-SRC-10` | Work assistant workspace | `nex-ae-web` and `nex-ae-api` should support chat, intent routing, grounded answers, document generation, artifacts, and workspace history. | PCX generation, summary, chat, artifact export, retry/edit, and template slices validated the UX direction. | `nex-ae-web`, `nex-ae-api` | MVP | UI, orchestration API | How much intent automation is required for the first MVP? | Distilled in [Service Boundary Decision Record](../../12_service_boundary_decision_record.md), [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md), [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md), and [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md); AE owns user-facing orchestration, artifacts, preview/download links, and chat workspace linkage while consuming CX-safe structured drafts. | Seeded |
| `NP-SRC-11` | Model operations | `nex-mo` should own provider registry, health, preflight, metrics, runtime settings, and resource monitoring. | PCX remote embedding/reranker/vLLM provider work produced health, smoke, metric, and memory evidence. | `nex-mo` | MVP | Provider API, monitoring | Should live DGX provider management be required in MVP or mock-first? | Distilled in [Service Boundary Decision Record](../../12_service_boundary_decision_record.md) and [CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md); MO owns stable provider APIs and runtime telemetry. Mock-first, live smoke as optional evidence. | Seeded |
| `NP-SRC-05` | Lifecycle and host control | Service lifecycle, host registry, graceful shutdown, start/stop plans, and process evidence need a contract. | PCX foreground app/worker supervisor and shutdown drain checks exposed this operational need. | `nex-ag`, shared | Deferred | Operations | Is systemd/control-plane management needed within the 2-week MVP? | Defer full host control unless go-live demands it. | Open |
| `NP-SRC-06` | Installation, bootstrap, license, security | Bootstrap, license, TLS, secret storage, support bundle, backup/restore, and security exit criteria are important but broad. | PCX created operational readiness docs and scripts but did not become an installer. | `nex-ag`, `nex-oa`, shared | Deferred | Security, operations | Which security baseline is non-negotiable for first pilot? | Extract only auth/secrets minimum for MVP. | Open |
| `NP-SRC-14` | Common functions | Common function definitions should be reconciled with service ownership and contract-only sharing. | PCX shared modules grew from repeated needs rather than upfront large framework design. | Shared | Needs Review | Common module | Which functions are stable enough for a shared package? | Review after MVP capability map. | Open |
| `NP-SRC-01` | Full SRS | The full SRS is the broadest source and should be distilled, not copied. | PCX slice history provides evidence to confirm or trim each requirement. | Shared | Needs Review | SRS | Which sections duplicate the smaller source documents? | Use as comprehensive cross-check after MVP rows. | Open |
| `NP-SRC-12` | v2.0 communication intelligence | Communication intelligence, customer timeline, STT, telephony, and automation are likely v2.0 expansion concepts. | PCX focused on document intelligence, not call-center communication workflows. | Shared | Deferred | Roadmap | Are any v2.0 concepts needed as architecture extension points now? | Preserve as deferred roadmap input. | Open |

## Review Rules

- One row should contain one decision-sized idea.
- Do not promote a broad source claim to MVP until an owner service is known.
- Keep implementation evidence separate from future preference.
- Mark duplicated large-document content as `Duplicate` instead of carrying it forward.
- Mark attractive but nonessential capabilities as `Deferred`.
- When the 400,000-token document conflicts with the 2-week MVP document, record
  the conflict and choose the smaller MVP unless the user explicitly expands scope.

## Initial Review Batches

| Batch | Scope | Output |
| --- | --- | --- |
| Batch 1 | 2-week MVP document | MVP capability shortlist and missing platform spine. |
| Batch 2 | PCX SRS and slice history | Evidence-backed requirements and deferred PCX features. |
| Batch 3 | 400,000-token design document | Architecture ideas filtered into MVP/deferred/rejected rows. |
| Batch 4 | Consolidation | First NeX-Platform SRS draft and service-level backlog. |
