# Platform Development Environment Freeze

Status: Draft seed for Slice 442.

Sources:

- `NP-SRC-15`
  (`15_260724_NeX_Platform_Development_Environment_Directory_Structure_v1.1.md`)
- [Development Environment Skeleton](04_development_environment_skeleton.md)
- [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md)
- [Service-Specific Requirement Partition](30_service_specific_requirement_partition.md)
- [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md)

This document freezes the first development environment assumptions for
NeX-Platform MVP implementation. The goal is to keep local, test, mock-live, and
production-like runs predictable while avoiding early coupling between services.

## Repository Strategy

| Decision | Rationale |
| --- | --- |
| Start MVP implementation in a monorepo-style workspace. | The first vertical spine needs coordinated contracts, mock providers, UI, and service bootstraps. |
| Keep service packages separately owned inside the workspace. | Monorepo convenience must not become shared database or hidden runtime coupling. |
| Keep raw source-material documents and live evidence outside committed source by default. | PCX source material may be large or private. |
| Promote schemas/OpenAPI to versioned contract directories before service code depends on them. | Prevents each service from inventing its own payload shape. |

If NeX-Platform later splits into multiple repositories, the contract package and
service boundaries from this workspace should remain unchanged.

## Proposed Workspace Layout

```text
nex-platform/
  apps/
    nex-ae-web/
  services/
    nex-ae-api/
    nex-cx/
    nex-mo/
    nex-oa/
    nex-ag/
  contracts/
    schemas/
    openapi/
    examples/
  docs/
    srs/
    design/
    operations/
  scripts/
    dev/
    smoke/
    quality/
  tests/
    contract/
    e2e/
    fixtures/
```

The layout is a planning target, not a command to move current NeX-PCX files.

## Runtime Baseline

| Runtime | MVP Baseline |
| --- | --- |
| Python | Backend services, workers, scripts, contract tests. Pin a single supported minor version per implementation repo. |
| Node.js | AE web, AG web if separate, frontend tests, Playwright. Pin one supported LTS line. |
| PostgreSQL | Service-owned metadata databases. |
| pgvector | CX-owned vector storage only. |
| Redis/queue | Optional for MVP; start with service-local database-backed job queues if schedule is tight. |
| Docker | Optional, not required for local DB or provider work. PCX proved non-Docker local DB development is viable. |

Runtime versions should be frozen in implementation files such as `.python-version`,
`.nvmrc`, lockfiles, and CI metadata once the code repositories are created.

## Environment Profiles

| Profile | Purpose | Provider Mode | DB Mode |
| --- | --- | --- | --- |
| `local_mock` | Default developer profile without DGX/vLLM access. | Mock embedding/reranker/generation. | Local service DBs or a shared dev PostgreSQL instance with service-owned DB names. |
| `local_live` | Local services with remote DGX/vLLM providers. | Remote HTTP/OpenAI-compatible providers through MO. | Development DBs. |
| `test` | Deterministic CI and local regression. | Mock providers only. | Isolated test DBs reset by migrations/fixtures. |
| `staging_live` | Protected integration environment. | Remote provider smoke allowed. | Staging DBs. |
| `production` | Real users and governed providers. | MO-managed live providers. | Production service DBs. |

Implementation default should be `local_mock`. Live providers are opt-in.

## Service Database Naming

| Service | Development DB | Test DB | Production DB |
| --- | --- | --- | --- |
| `nex-oa` | `nex_oa_dev` | `nex_oa_test` | `nex_oa_app` |
| `nex-ag` | `nex_ag_dev` | `nex_ag_test` | `nex_ag_app` |
| `nex-ae-api` | `nex_ae_dev` | `nex_ae_test` | `nex_ae_app` |
| `nex-cx` | `nex_cx_dev` | `nex_cx_test` | `nex_cx_app` |
| `nex-mo` | `nex_mo_dev` | `nex_mo_test` | `nex_mo_app` |

The exact database users/passwords are environment-specific secrets. Do not
commit them.

## Configuration Families

| Family | Example Keys | Owner |
| --- | --- | --- |
| Database | `NEX_CX_DATABASE_URL`, `NEX_AE_DATABASE_URL`, `NEX_MO_DATABASE_URL` | Service-local |
| OA trust | `NEX_OA_JWKS_URL`, `NEX_SERVICE_ID`, `NEX_SERVICE_TOKEN_AUDIENCE` | All backend services |
| Provider mode | `NEX_MO_PROVIDER_MODE`, `NEX_MO_GENERATION_PROFILE`, `NEX_MO_EMBEDDING_PROFILE` | MO |
| Remote providers | `NEX_MO_PROVIDER_BASE_URL`, alias-specific route records | MO |
| Runtime profile | `NEX_PROFILE=local_mock|local_live|test|staging_live|production` | All services |
| Observability | `LOG_LEVEL`, `TRACE_SAMPLE_RATE`, `METRICS_INTERVAL_SECONDS` | All services |
| Artifacts | `NEX_AE_ARTIFACT_STORAGE_ROOT`, signed-link settings | AE API |
| Source files | `NEX_CX_SOURCE_STORAGE_ROOT`, extraction temp root | CX |

Configuration files may provide non-secret defaults, but secrets belong in local
environment files, secret stores, or deployment configuration.

## Mock And Live Provider Rules

| Rule | Requirement |
| --- | --- |
| Mock-first CI | CI must not require DGX/vLLM availability. |
| Live opt-in | Live provider smoke runs only when explicit profile and credentials are present. |
| MO boundary | CX calls MO aliases; AE/AG do not call provider hosts. |
| Evidence | Live smoke writes redacted evidence outside source unless sanitized. |
| Timeout | Mock providers must support timeout/throttle/failure branches. |

## Local Setup Checklist

1. Create service-owned databases and users for selected profile.
2. Apply each service's migrations.
3. Seed OA bootstrap admin/service claims.
4. Seed MO mock provider aliases.
5. Seed CX default extraction, chunk, tokenizer, and retrieval profiles.
6. Seed AE default prompt/template/output compatibility rules.
7. Start backend services.
8. Start AE web.
9. Run health/ready/version checks.
10. Run mock E2E acceptance before live provider smoke.

## Guardrails

- Do not share service databases for convenience once implementation begins.
- Do not store provider API keys, DB passwords, or signing keys in committed
  files.
- Do not make live DGX/vLLM availability a prerequisite for normal development.
- Do not let local path assumptions leak into public API examples.
- Do not use Docker as an implicit requirement unless the implementation team
  explicitly accepts it.

## Next Inputs

This environment freeze should feed:

- Common schema and contract package layout, starting from
  [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md).
- Testing strategy detail, starting from
  [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md).
- First sprint repository and bootstrap backlog, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
- Operations runbook for local/mock/live startup.
