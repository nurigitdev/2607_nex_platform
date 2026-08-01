# Cross-Service Traceability Matrix

Status: Draft seed for Slice 441.

Sources:

- [Source Material Inventory](./archive/planning/09_source_material_inventory.md)
- [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md)
- [Service-Specific Requirement Partition](30_service_specific_requirement_partition.md)
- [Common Contract Freeze Candidate Map](11_common_contract_freeze_candidate_map.md)
- [Generation E2E Acceptance + Contract Test Plan](28_generation_e2e_acceptance_contract_test_plan.md)

This document seeds the traceability matrix from source material to MVP
requirement, service owner, contract artifact, and verification evidence. It is
not meant to list every future requirement. It focuses on the first buildable
vertical spine and the highest-risk cross-service boundaries.

## Traceability Rule

Each MVP requirement should eventually trace through:

```text
source material or PCX lesson
-> decision or requirement document
-> service-owned requirement ID
-> contract/schema/API artifact
-> acceptance or contract test
-> evidence artifact
```

If a requirement cannot be traced, it should be treated as a candidate rather
than a frozen MVP item.

## Source-To-Requirement Matrix

| Trace ID | Source Basis | Decision Artifact | Requirement IDs | Verification |
| --- | --- | --- | --- | --- |
| `TRACE-AUTH-001` | `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-07`, MVP auth flow | Service boundary and MVP SRS | `OA-FR-001` to `OA-FR-005`, `PLAT-FR-002` | Auth API contract tests, claim validation tests, AG auth audit read. |
| `TRACE-CONTENT-001` | `NP-SRC-09`, PCX ingestion/extraction work | MVP capability map and CX ownership | `CX-FR-001` to `CX-FR-004` | Upload/ingestion integration, extractor fixture tests, index freshness checks. |
| `TRACE-RETRIEVAL-001` | `NP-SRC-09`, PCX hybrid search/BM25/reranker work | Retrieval package contract | `CX-FR-005`, `CX-FR-006`, `AEAPI-FR-003` | Retrieval contract tests, no-answer/low-confidence branches, source context checks. |
| `TRACE-MO-001` | `NP-SRC-11`, PCX provider route/metrics work | CX-to-MO provider contract | `MO-FR-001` to `MO-FR-005`, `CX-FR-007` | Mock provider tests, live smoke evidence, route readiness checks. |
| `TRACE-AE-001` | `NP-SRC-10`, PCX chat/generation/artifact work | AE orchestration and artifact handoff contracts | `AEAPI-FR-001` to `AEAPI-FR-006`, `AEWEB-FR-001` to `AEWEB-FR-005` | AE API integration, Playwright UI flow, artifact download permission tests. |
| `TRACE-GEN-001` | `NP-SRC-09`, `NP-SRC-10`, `NP-SRC-11`, PCX generation work | Generation contract set, schema seed, OpenAPI seed | `CX-FR-007`, `CX-FR-008`, `MO-FR-002`, `AEAPI-FR-002` to `AEAPI-FR-005` | `GEN-E2E-001` to `GEN-E2E-010`, schema validation, compatibility mismatch tests. |
| `TRACE-AG-001` | `NP-SRC-08`, PCX dashboard/audit/readiness work | AG audit dashboard requirements | `AG-FR-001` to `AG-FR-005` | AG API contract tests, redaction checks, audit export evidence. |
| `TRACE-PLAT-001` | `NP-SRC-02`, `NP-SRC-03`, PCX quality gate lessons | Common contract map and testing strategy | `PLAT-FR-001` to `PLAT-FR-007`, `NFR-*` | Health/ready/version tests, problem+json tests, idempotency tests, coverage gate. |

## Requirement-To-Contract Matrix

| Requirement Family | Primary Contracts | Secondary Contracts |
| --- | --- | --- |
| `OA-FR-*` | Common headers, service identity, auth claim references | AG audit read, error envelope |
| `CX-FR-001` to `CX-FR-004` | CX content/extraction/chunk/index contracts from service SRS | Common job, progress event, source material inventory |
| `CX-FR-005` to `CX-FR-006` | CX-to-AE retrieval context package | Permission boundary, no-answer guardrail |
| `CX-FR-007` to `CX-FR-008` | AE-to-CX generation request, CX execution lineage, structured draft/citation | Compatibility matrix, recovery policy, progress event |
| `MO-FR-*` | CX-to-MO generation provider contract, provider route/readiness contracts | vLLM metrics, resource telemetry, AG provider usage |
| `AEAPI-FR-*` | AE orchestration, artifact handoff, chat artifact link | Generation progress/recovery, compatibility matrix |
| `AEWEB-FR-*` | Design system, chat workspace artifact requirements | UI i18n, progress event, quality badges |
| `AG-FR-*` | AG generation artifact audit requirements | Common audit event, service health/readiness, redaction |
| `PLAT-FR-*` | Common contract freeze map, JSON Schema seed, OpenAPI seed | Testing strategy, E2E acceptance plan |

## Requirement-To-Test Matrix

| Test ID | Requirement Coverage | Test Type | Evidence |
| --- | --- | --- | --- |
| `CT-AUTH-001` | `OA-FR-002`, `OA-FR-003`, `PLAT-FR-002` | Contract/API | Token validation pass/fail fixtures. |
| `CT-CX-INGEST-001` | `CX-FR-001` to `CX-FR-004`, `PLAT-FR-005` | Integration | Ingestion job events and index readiness summary. |
| `CT-CX-RETR-001` | `CX-FR-005`, `CX-FR-006` | Contract/API | Retrieval package payloads with permission and no-answer cases. |
| `CT-MO-001` | `MO-FR-001` to `MO-FR-004` | Contract/mock provider | Alias execution, route readiness, timeout, throttling fixtures. |
| `CT-GEN-001` | `GEN-E2E-001` to `GEN-E2E-010` | Mock E2E | End-to-end run log and schema validation result. |
| `CT-AE-ART-001` | `AEAPI-FR-004` to `AEAPI-FR-006` | API/UI | Artifact render/download permission fixtures and screenshot. |
| `CT-AG-001` | `AG-FR-001` to `AG-FR-005` | API/contract | Redacted audit dashboard response and export sample. |
| `CT-PLAT-001` | `PLAT-FR-001`, `PLAT-FR-003`, `PLAT-FR-004`, `PLAT-FR-007` | Contract/regression | Health, idempotency, problem+json, schema/OpenAPI validation. |

## Coverage Gaps

| Gap | Risk | Follow-Up |
| --- | --- | --- |
| OA claim catalog is not yet fully enumerated. | Services may implement incompatible scopes. | Add OA claim/service-scope catalog before auth implementation deepens. |
| CX extraction contracts are not yet service-specific. | File-format responsibilities can blur. | Derive CX service SRS and extraction contract files from PCX lessons. |
| AG policy write surface remains read-mostly. | Operators may expect controls not included in MVP. | Keep read-only MVP explicit; add policy mutation only by later decision. |
| Schema package layout is not frozen. | Services may duplicate schema names differently. | Resolve in common schema and contract package layout. |
| Development environment profile is not frozen. | Mock/live/test setup can drift. | Resolve in platform development environment freeze. |

## Traceability Maintenance

- Update this matrix when a requirement ID is added, removed, or renamed.
- Keep source references at document level unless a specific paragraph becomes
  legally or operationally important.
- Prefer linking to contract docs over copying field tables.
- Treat live smoke evidence as supplementary to mock/contract verification.
- Keep raw source material outside commits unless separately approved.

## Next Inputs

This matrix should feed:

- Development environment freeze, starting from
  [Platform Development Environment Freeze](32_platform_development_environment_freeze.md).
- Common schema and contract package layout, starting from
  [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md).
- Testing strategy detail, starting from
  [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md).
- First sprint backlog and acceptance evidence checklist, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
