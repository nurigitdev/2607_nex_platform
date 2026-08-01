# AG Generation Artifact Audit Dashboard Requirements

Status: Draft seed for Slice 435.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)
- `NP-SRC-08`
  (`08_260723_NeX_AG_Operations_Administration_Design_v1.6.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- [Service Boundary Decision Record](../../12_service_boundary_decision_record.md)
- [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Progress Event Contract](21_generation_progress_event_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)
- [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md)

This document freezes the first admin and governance requirements for observing
generation and generated artifacts. `nex-ag` should help operators answer what
happened, who did it, which sources and models were involved, whether warnings
were accepted, and which files were rendered or downloaded. It should not become
the owner of chat messages, generated artifacts, CX corpus records, or MO
provider execution.

## Boundary Decision

| Area | Authoritative Owner | AG Role |
| --- | --- | --- |
| Chat message and artifact cards | AE | Read summary and link metadata through AE APIs. |
| Render jobs and artifact files | AE | Read status, failure, download, and retention summaries. |
| Retrieval package and citations | CX | Read source/citation/permission summaries through CX APIs. |
| Generation execution record | CX | Read lineage, validation, compatibility, and MO call summaries. |
| Provider runtime and usage | MO | Read model alias, route, usage, latency, health, and readiness summaries. |
| Identity and claims | OA | Read safe actor/service claim references and auth audit summaries. |
| Governance projection | AG | Store dashboard filters, operator notes, exported evidence, and policy actions. |

AG must not read service databases directly. Dashboard data is assembled from
service APIs using service claims and read scopes.

## Dashboard Views

| View | Purpose | Primary Source |
| --- | --- | --- |
| Generation timeline | Ordered progress events, status, stage, failures, retries, and completion. | CX/AE/MO events |
| Artifact lineage | Artifact, versions, render jobs, file outputs, current version, rollback state. | AE |
| Citation and completeness | Citation validation, source anchor readiness, required section coverage, warnings. | CX |
| Compatibility decisions | Template/prompt/output/provider rule ID, version, hash, mismatch results. | AE/CX |
| Download and preview audit | Actor, artifact file, format, download route type, result, timestamp. | AE/OA |
| Failure and recovery | Failure class, retryability, repair/regenerate lineage, manual warning acceptance. | AE/CX/MO |
| Provider usage summary | Provider alias, model revision, tokens, latency, finish reason, degraded state. | MO via CX |
| Permission snapshot | Actor claim ref, scope, denied/filtered counts, source visibility summary. | OA/CX |
| Operator actions | Policy override, note, export evidence, warning acceptance review. | AG |

The MVP dashboard can start with read-only cards and details. Policy mutation can
remain a later hardening step.

## Filter Requirements

| Filter | Requirement |
| --- | --- |
| Time window | Required; default to recent operational window. |
| Service | Filter events by `nex-ae-api`, `nex-cx`, `nex-mo`, `nex-oa`, or `nex-ag`. |
| Actor | Filter by safe actor reference or actor type. |
| Workspace/chat | Filter by chat document, workspace, or group scope when authorized. |
| Template | Filter by template ID/version and template type. |
| Prompt contract | Filter by prompt contract ID/version. |
| Compatibility rule | Filter by rule ID/version/hash. |
| Model/provider | Filter by MO alias, model revision, deployment ID, or capability. |
| Failure code | Filter by stable failure or warning code. |
| Artifact status | Filter by `READY`, `FAILED`, `ARCHIVED`, `DELETED`, or render job state. |

Filters must be allowlisted and cursor-paginated. Free-form filter input must
not be passed into service query expressions directly.

## Audit Event Shape

Generation and artifact audit projections should use a redacted shape.

| Field | Required | Notes |
| --- | --- | --- |
| `audit_event_id` | Yes | Stable AG event/projection ID. |
| `event_schema_version` | Yes | Start with `ag_generation_audit_event.v1`. |
| `trace_id` / `request_id` | Yes | Cross-service correlation. |
| `occurred_at` | Yes | RFC3339 UTC timestamp. |
| `source_service` | Yes | Service that emitted or supplied the source event. |
| `actor_ref` | Yes | Safe OA actor or service reference. |
| `action_type` | Yes | `generation_run`, `artifact_render`, `download`, `retry`, `repair`, `override`, or similar. |
| `target_type` | Yes | `generation`, `artifact`, `artifact_file`, `policy`, or `provider`. |
| `target_ref` | Yes | Safe target ID and display summary. |
| `result_status` | Yes | `SUCCEEDED`, `FAILED`, `DENIED`, `WARNED`, or `ACCEPTED_WITH_WARNING`. |
| `quality_summary` | No | Citation, completeness, confidence, no-answer, and warning summary. |
| `compatibility_summary` | No | Rule ID/version/hash and mismatch status. |
| `provider_summary` | No | Alias, model revision, usage, latency, and finish reason. |
| `details` | No | Redacted operator-safe metadata. |

The audit event shape is for dashboard and export. It is not a mandate that all
services store the same physical table.

## Redaction Requirements

AG views must not expose:

- Raw bearer tokens, API keys, cookies, or service secrets.
- Raw provider URLs, ports, private model paths, or host credentials.
- Full source documents, full retrieval packages, or full provider prompts.
- Raw generated documents when the viewer is not authorized for the artifact.
- Stack traces, SQL text, environment variables, or local filesystem paths.

AG views can expose safe IDs, hashes, counts, timestamps, status, failure codes,
model aliases, model revisions, usage aggregates, and redacted snippets when the
source service allows them.

## API Requirements

Recommended AG read APIs:

```text
GET /admin/v1/generation-audit/events
GET /admin/v1/generation-audit/generations/{generation_id}
GET /admin/v1/generation-audit/artifacts/{artifact_id}
GET /admin/v1/generation-audit/failures
GET /admin/v1/generation-audit/provider-usage
GET /admin/v1/generation-audit/exports/{export_id}
```

Recommended service reads consumed by AG:

```text
GET /api/v1/generations/{generation_id}
GET /api/v1/generations/{generation_id}/events
GET /api/v1/artifacts/{artifact_id}
GET /api/v1/artifacts/{artifact_id}/lineage
GET /api/v1/provider-generations/{mo_generation_id}
GET /api/v1/auth/audit-events?trace_id=...
```

Service-local endpoint names may vary, but the ownership and safe read shape
must remain stable.

## Operator Actions

| Action | MVP Scope |
| --- | --- |
| Add operator note | Allowed in AG; does not mutate AE/CX/MO records. |
| Export evidence snapshot | Allowed when actor has audit export scope. |
| Mark reviewed | Allowed in AG projection only. |
| Retry or repair generation | AG can link to AE/CX action but should not bypass AE/CX policy. |
| Force provider route | Defer unless a separate MO policy contract approves it. |
| Delete artifact | Defer to AE artifact policy; AG can request or audit the action. |

AG should make operational risk visible before it becomes a control plane.

## Contract Tests To Derive

- AG dashboard reads generation/artifact/provider data through service APIs, not
  direct database access.
- Dashboard filters are allowlisted, cursor-paginated, and preserve time window.
- Audit summaries include trace ID, request ID, actor ref, source service,
  action type, target ref, result status, and timestamps.
- Compatibility mismatch and recovery events are visible in AG views.
- Download audit never exposes raw filesystem paths or unsigned private storage
  references.
- Redaction removes secrets, raw provider endpoints, model file paths, full
  prompts, and unauthorized generated content.

## Next Inputs

This requirements document should feed:

- Generation JSON Schema seed, starting from
  [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md).
- Generation OpenAPI endpoint seed, starting from
  [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md).
- Generation E2E acceptance scenario and contract test plan.
- AG MVP dashboard SRS sections.
