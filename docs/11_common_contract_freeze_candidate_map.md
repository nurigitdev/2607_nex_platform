# Common Contract Freeze Candidate Map

Status: Draft seed for Slice 421.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)

This document identifies the cross-service contracts that should be frozen
before individual NeX-Platform services begin implementation. It is a contract
map, not a shared framework mandate. The first implementation should prefer
schema and behavior compatibility over a large shared utility package.

## Freeze Classification

| Classification | Meaning |
| --- | --- |
| Freeze Now | Stable enough to use as a cross-service requirement in the first SRS draft. |
| Freeze Candidate | Important, but needs one more owner or scope decision before freezing. |
| Defer | Useful later, but too broad for the first platform baseline. |
| Conflict | Source documents disagree or conflict with the user-confirmed service boundary. |

## Freeze Now

| Contract Area | Decision | Source Basis | Consumers |
| --- | --- | --- | --- |
| Service IDs | Use lower-kebab-case service IDs: `nex-oa`, `nex-ag`, `nex-ae`, `nex-cx`, `nex-mo`. | `NP-SRC-02`, `NP-SRC-13` | All services |
| Python packages | Use lower_snake_case package names such as `nex_cx`. | `NP-SRC-02` | Backend services |
| Database names/users | Use service-owned lower_snake_case databases and users such as `nex_cx_db` and `nex_cx_user`. | `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-13` | All services |
| JSON fields | Use lower_snake_case JSON fields. | `NP-SRC-02`, `NP-SRC-03` | All APIs |
| Enum values | Use UPPER_SNAKE_CASE enum/state values. | `NP-SRC-02` | All APIs, DB constraints, UI labels |
| Time | Use RFC3339 UTC on the wire and TIMESTAMPTZ in PostgreSQL. | `NP-SRC-02` | All services |
| IDs | Use UUID internal IDs; never reuse IDs after deletion. | `NP-SRC-02` | All services |
| API families | Business APIs use `/api/v1/...`; admin APIs use `/admin/v1/...`; health endpoints stay `/health`, `/ready`, `/version`. | `NP-SRC-02`, `NP-SRC-03`, `NP-SRC-13` | All services |
| HTTP conventions | Use 200 for read, 201 for sync create, 202 for async create/delete, 204 for completed delete, 401/403/404/409/429/503 for common failure classes. | `NP-SRC-02` | All APIs |
| Headers | Support `Authorization`, `Idempotency-Key`, `X-Request-ID`, `traceparent`, `tracestate`, `X-Service-ID`, `Content-Type`, and `Accept`. | `NP-SRC-02`, `NP-SRC-03` | All APIs |
| Request correlation | `traceparent` is the distributed trace header; `X-Request-ID` is for operator support and log correlation. | `NP-SRC-02`, `NP-SRC-03` | All APIs, logs |
| Success envelope | Return raw resource JSON for a single resource; use `data` and `meta` envelope for lists, async responses, and aggregates. | `NP-SRC-02`, `NP-SRC-03` | All APIs |
| Error envelope | Use `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, `error_code`, `retryable`, `request_id`, `trace_id`, and `details`. | `NP-SRC-02`, `NP-SRC-03` | All APIs |
| Error redaction | Do not include secrets, stack traces, SQL, raw tokens, or full private document/prompt bodies in error detail. | `NP-SRC-02`, `NP-SRC-03`, PCX lessons | All APIs |
| Pagination | Use `cursor` and `limit`; return `next_cursor` and `has_more`; do not make page number the default for new APIs. | `NP-SRC-02` | List APIs |
| Filter/sort | Explicitly allowlist filter and sort fields; never pass user input directly into SQL column/expression strings. | `NP-SRC-02` | List/search/admin APIs |
| Idempotency | For create/control operations, same key plus same payload returns the prior result; same key plus different payload returns 409 `IDEMPOTENCY_KEY_CONFLICT`. | `NP-SRC-02` | Create/control APIs |
| Async API | Long-running work returns 202 with `job_id` and a `Location` pointing to the job resource. | `NP-SRC-02`, `NP-SRC-03`, PCX lessons | AE, CX, MO, AG |
| Database isolation | Each service uses only its own database; cross-service database access and cross-database joins are forbidden. | `NP-SRC-03`, `NP-SRC-13` | All services |

## State Contracts

| Contract | Frozen Values |
| --- | --- |
| `platform_mode` | `BOOTSTRAP`, `SETUP`, `OPERATIONAL`, `MAINTENANCE`, `RECOVERY` |
| `desired_state` | `RUNNING`, `STOPPED` |
| `lifecycle_state` | `UNKNOWN`, `STARTING`, `RUNNING`, `DRAINING`, `STOPPING`, `STOPPED`, `FAILED`, `FORCE_STOPPED` |
| `health_status` | `HEALTHY`, `DEGRADED`, `UNHEALTHY`, `UNKNOWN` |
| `readiness_status` | `READY`, `NOT_READY` |
| `job_status` | `PENDING`, `QUEUED`, `RUNNING`, `CANCEL_REQUESTED`, `CANCELLED`, `RETRYING`, `COMPLETED`, `FAILED`, `TIMEOUT` |
| `progress_mode` | `DETERMINATE`, `INDETERMINATE`, `STREAMING` |
| `upload_status` | `SELECTED`, `UPLOADING`, `UPLOADED`, `FAILED`, `CANCELLED` |
| `ingestion_status` | `NOT_REQUESTED`, `QUEUED`, `RUNNING`, `READY`, `FAILED`, `CANCELLED` |
| `license_status` | `NOT_INSTALLED`, `ACTIVE`, `GRACE`, `EXPIRED`, `INVALID` |

Important separation:

- `DEGRADED` belongs to `health_status`, not `lifecycle_state`.
- Domain stages such as `PARSING`, `CHUNKING`, `EMBEDDING`, `GENERATING`,
  `RENDERING`, and `VALIDATING` belong to `current_stage`, not `job_status`.

## Common Job Contract

Freeze the job shape early because ingestion, generation, artifact rendering,
provider checks, backup/restore, and service control all need progress feedback.

| Field | Freeze Status | Notes |
| --- | --- | --- |
| `job_id` | Freeze Now | UUID. |
| `job_type` | Freeze Now | Service-specific values allowed, but field name is fixed. |
| `status` | Freeze Now | Must use canonical `job_status`. |
| `current_stage` | Freeze Now | Domain-specific stage; not part of `job_status`. |
| `progress_mode` | Freeze Now | `DETERMINATE`, `INDETERMINATE`, or `STREAMING`. |
| `progress_percent` | Freeze Now | Only meaningful for determinate work; do not invent percentages for indeterminate work. |
| `processed_items` / `total_items` | Freeze Candidate | Required when determinate progress is available. |
| `message` | Freeze Now | User/operator-facing progress text. |
| `queue_position` / `estimated_wait_seconds` | Freeze Candidate | Include only when based on reliable observation. |
| `can_cancel` / `retryable` | Freeze Now | UI and orchestration need these consistently. |
| `created_at` / `started_at` / `updated_at` | Freeze Now | RFC3339 UTC on the wire. |

Recommended APIs:

```text
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/events
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
GET  /admin/v1/jobs/summary
GET  /admin/v1/workers
```

## Logging, Audit, And Security

| Contract | Freeze Status | Notes |
| --- | --- | --- |
| Application log core fields | Freeze Now | `occurred_at`, `service_id`, `level`, `message`, `trace_id`, `request_id`, `job_id`, `user_id`, `endpoint`, `status_code`, `latency_ms`, `details`. |
| Redaction keys | Freeze Now | Redact `password`, `authorization`, `access_token`, `refresh_token`, `service_secret`, `reset_token`, `activation_token`, and `cookie`. |
| Audit fields | Freeze Now | `actor_type`, `actor_id`, `action_type`, `target_type`, `target_id`, `result_status`, `reason`, `before_value`, `after_value`. |
| Security log fields | Freeze Now | `event_type`, `subject_type`, `subject_id`, `result_status`, `failure_reason`, `token_kid`, scope/audience metadata. |
| Audit/security retention | Freeze Candidate | Must be separated from normal application log retention, but exact retention period is an operations policy. |
| Dynamic log level | Freeze Candidate | Useful, but first freeze log schema and redaction. |
| Cross-service log merge | Defer | AG can read logs through service APIs later; do not require merge UI for the first contract freeze. |

## Freeze Candidates

| Contract Area | Why Not Freeze Fully Yet | Next Decision |
| --- | --- | --- |
| OpenAPI/JSON Schema generation | The target repository shape is still open. | Decide monorepo vs multi-repo and schema package location. |
| Shared `nex_common` package | Useful, but too early to mandate a large package. | Start with schema files and contract tests; add code package only where duplication hurts. |
| SQLAlchemy async runtime | The Python backend direction is stable, but final service repository layout is not. | Freeze config names first; implement service-local adapters if needed. |
| DB pool defaults | Source values are examples, not production tuning. | Freeze setting names, not numeric defaults. |
| Service lifecycle drain APIs | Useful for production readiness, but host control is outside the first MVP. | Freeze `/health`, `/ready`, `/version`; make drain hook a later hardening contract. |
| Evidence contract | Retrieval/generation needs stable evidence IDs, source locations, permission snapshots, and citation labels. | Freeze minimal retrieval package after CX/AE generation boundary review. |
| AE-to-CX generation request package | Generation ownership is now reconciled, but the final JSON Schema file is not generated yet. | Use [AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md) as the first schema seed. |
| CX-to-MO generation provider contract | MO provider execution is now separated from CX prompt/evidence ownership, but final JSON Schema file is not generated yet. | Use [CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md) as the first schema seed. |
| CX generation execution record | Retrieval, prompt, MO, structured draft, citation, and retry lineage are connected, but final storage schema is not generated yet. | Use [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md) as the first lineage seed. |
| Structured draft and citation schema | Document generation needs stable sections, blocks, citation claims, evidence anchors, validation statuses, and safe read shape before artifact rendering. | Use [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md) as the first schema seed. |
| AE artifact rendering handoff contract | Generated drafts need AE-owned artifact records, versions, render jobs, file metadata, preview/download links, and CX lineage refs. | Use [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md) as the first artifact schema seed. |
| Generation progress event contract | Long-running generation and artifact rendering need stable event envelopes, stage names, status separation, streaming/polling semantics, and redacted progress metadata. | Use [Generation Progress Event Contract](21_generation_progress_event_contract.md) as the first progress schema seed. |
| Generation failure and repair policy | Recovery needs stable failure classes, retryability, repair/regenerate actions, lineage fields, and operator/user warning rules. | Use [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md) as the first recovery policy seed. |
| Chat workspace artifact link requirements | AE chat needs stable artifact cards, version links, preview/download actions, source drilldown, quality badges, and recovery affordances. | Use [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md) as the first chat-artifact UX seed. |
| Prompt/template/output compatibility matrix | Generation needs explicit compatibility among execution mode, template, prompt contract, output schema, artifact intent, target format, quality policy, and provider capability. | Use [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md) as the first compatibility rule seed. |
| AG generation artifact audit dashboard | Operators need read-only generation timeline, artifact lineage, citation/completeness, compatibility, download audit, provider usage, and recovery views. | Use [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md) as the first AG audit view seed. |
| Generation contract JSON schema catalog | Generation request, response, event, lineage, draft, artifact, compatibility, and audit contracts need explicit schema IDs before OpenAPI and contract tests. | Use [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md) as the first schema catalog seed. |
| Generation OpenAPI endpoint surface | Generation orchestration needs service-owned AE/CX/MO/AG/OA endpoints, headers, idempotency, error codes, and streaming/polling routes. | Use [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md) as the first endpoint seed. |
| Generation E2E acceptance and contract test plan | Generation needs a mock-first spine that verifies retrieval package, CX generation, MO provider execution, AE artifact, recovery, compatibility, and AG audit together. | Use [Generation E2E Acceptance + Contract Test Plan](28_generation_e2e_acceptance_contract_test_plan.md) as the first acceptance seed. |
| Service-specific requirement partition | MVP implementation needs stable service-owned requirement IDs and dependency order before backlog slicing. | Use [Service-Specific Requirement Partition](30_service_specific_requirement_partition.md) as the first requirement partition seed. |
| Cross-service traceability matrix | MVP requirements need source, decision, contract, test, and evidence traceability before implementation starts. | Use [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md) as the first traceability seed. |
| Common schema and contract package layout | Service teams need one place for JSON Schema, OpenAPI, examples, negative fixtures, versioning, and contract validation hooks. | Use [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md) as the first package layout seed. |
| Channel request context | Helpful for future web/app/voice channels. | Keep optional fields; do not design channel-specific data models yet. |

## Conflicts To Resolve

| Conflict | Source | Proposed Resolution |
| --- | --- | --- |
| `DEGRADED` appears as lifecycle state in `NP-SRC-03`, while `NP-SRC-02` says not to use `DEGRADED` for lifecycle. | `NP-SRC-02`, `NP-SRC-03` | Freeze `DEGRADED` only in `health_status`; keep lifecycle focused on process/control states. |
| Generation ownership is split differently across source docs. | `NP-SRC-03`, `NP-SRC-13`, user-confirmed boundary | Keep `nex-ae-api` as user intent/prompt/template/final formatting orchestrator; keep `nex-cx` as retrieval/evidence/content lifecycle owner; keep `nex-mo` as provider execution owner. |
| Statement coverage target differs across sources. | `NP-SRC-03` says 90%; `NP-SRC-13` says 95%; PCX current gate reports statement and branch separately. | Freeze branch coverage target 85%; keep statement target as MVP policy decision, with 95% as aspirational first-platform target unless implementation reality requires a written exception. |
| Common foundation can become a large shared framework too early. | `NP-SRC-03`, PCX lessons | Freeze contracts first; defer broad shared utilities until service boundaries are proven. |

## Contract Test Requirements

Every service should eventually run contract tests for:

- OpenAPI request/response schema validation.
- Unknown enum handling.
- `application/problem+json` error shape.
- Idempotency key conflict behavior.
- Cursor pagination metadata.
- `traceparent` and `X-Request-ID` propagation.
- RFC3339 UTC timestamp serialization.
- Backward-compatible enum and schema migration.
- DB check constraints matching API enums.
- UI labels remaining separate from enum values.

## Next Inputs

This map should feed:

- NeX-Platform MVP SRS v0.1 common requirements.
- Service-specific OpenAPI and JSON Schema skeletons.
- Service boundary conflict review, especially generation ownership.
- Development environment and repo strategy map.
