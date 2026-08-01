# Generation Progress Event Contract

Status: Draft seed for Slice 431.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md)
- [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md)

This document freezes the first progress event contract for long-running
generation. It lets AE web, AE API, CX, MO, and AG describe the same generation
flow without mixing user-facing stages, common job status, provider runtime
events, and artifact rendering status.

## Event Ownership

| Event Source | Owner | Purpose |
| --- | --- | --- |
| AE orchestration event | AE | User prompt intake, intent selection, template selection, artifact rendering, chat response linkage. |
| CX generation event | CX | Retrieval package validation, prompt package assembly, generation execution record, draft/citation validation. |
| MO provider event | MO | Admission, queueing, provider generation, streaming deltas, token usage, provider finish reason. |
| AE artifact event | AE | Render job stages, preview/download link creation, artifact version status. |
| AG projection event | AG | Read-only operational timeline assembled through service APIs. |

AG does not own generation progress. It observes progress through AE/CX/MO APIs
and stores projections only when an audit or monitoring policy requires it.

## Event Envelope

All progress events should use a JSON-compatible envelope.

| Field | Required | Notes |
| --- | --- | --- |
| `event_id` | Yes | Stable event ID or deterministic append-only ID. |
| `event_schema_version` | Yes | Start with `generation_progress_event.v1`. |
| `event_type` | Yes | Domain event type; separate from `job_status`. |
| `event_source_service` | Yes | `nex-ae-api`, `nex-cx`, `nex-mo`, or `nex-ag`. |
| `trace_id` / `request_id` | Yes | Cross-service correlation. |
| `occurred_at` | Yes | RFC3339 UTC timestamp. |
| `sequence_no` | Yes | Monotonic within the source execution stream. |
| `job_id` | No | Present when the service exposes a common job resource. |
| `cx_generation_id` | No | Present for CX-mediated generation. |
| `mo_generation_id` | No | Present after MO accepts provider execution. |
| `artifact_id` | No | Present when AE artifact rendering begins. |
| `artifact_version_id` | No | Present when a render job creates a version. |
| `job_status` | Yes | Common status: `PENDING`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `TIMEOUT`, or `CANCELLED`. |
| `current_stage` | Yes | User/domain stage such as `RETRIEVAL_REQUESTED` or `GENERATING`. |
| `progress_mode` | Yes | `DETERMINATE`, `INDETERMINATE`, or `STREAMING`. |
| `progress_percent` | No | Present only when determinate. |
| `message_key` | Yes | Localizable UI message key, not final text. |
| `safe_message` | No | Optional already-localized or operator-safe text. |
| `retryable` | Yes | Whether the failed or terminal event can be retried. |
| `details` | No | Redacted safe metadata. |

`job_status`, `current_stage`, and `event_type` are different fields. Do not use
provider streaming event names as common job status values.

## Event Types

| Event Type | Source | Required Stage |
| --- | --- | --- |
| `generation.request.accepted` | AE/CX | `INTAKE` or `EVIDENCE_VALIDATING` |
| `generation.intent.selected` | AE | `INTENT_DETECTED` |
| `generation.retrieval.requested` | AE | `RETRIEVAL_REQUESTED` |
| `generation.retrieval.ready` | CX | `CONTEXT_PACKAGED` |
| `generation.retrieval.no_answer` | CX | `CONTEXT_PACKAGED` |
| `generation.template.selected` | AE | `TEMPLATE_SELECTED` |
| `generation.prompt.packaged` | CX | `PROMPT_ASSEMBLING` |
| `generation.provider.admitted` | MO | `MO_ADMISSION_WAITING` |
| `generation.provider.streaming_delta` | MO/CX | `GENERATING` |
| `generation.provider.completed` | MO/CX | `GENERATING` |
| `generation.draft.validating` | CX | `DRAFT_VALIDATING` |
| `generation.citation.validating` | CX | `CITATION_VALIDATING` |
| `generation.artifact.rendering` | AE | `ARTIFACT_RENDERING` |
| `generation.artifact.ready` | AE | `FINALIZING` |
| `generation.completed` | AE/CX | `COMPLETED` |
| `generation.failed` | AE/CX/MO | Service-specific failing stage |
| `generation.cancelled` | AE/CX/MO | Service-specific cancel stage |

Service-local implementations can emit more granular events, but public API
streams should map them to this allowlist for MVP clients.

## Canonical Stage Timeline

| Order | Stage | Owner | User-Facing Meaning |
| ---: | --- | --- | --- |
| 1 | `INTAKE` | AE | Request received and validated. |
| 2 | `INTENT_DETECTED` | AE | Mode and intent were selected. |
| 3 | `RETRIEVAL_REQUESTED` | AE/CX | Document grounding was requested. |
| 4 | `CONTEXT_PACKAGED` | CX | Evidence package is ready or no-answer was detected. |
| 5 | `TEMPLATE_SELECTED` | AE | Template and output target are selected. |
| 6 | `PROMPT_ASSEMBLING` | CX | Provider-facing prompt package is being assembled. |
| 7 | `MO_ADMISSION_WAITING` | CX/MO | MO is admitting or queueing provider execution. |
| 8 | `GENERATING` | MO/CX | Provider generation is running or streaming. |
| 9 | `DRAFT_VALIDATING` | CX | Structured draft schema is being checked. |
| 10 | `CITATION_VALIDATING` | CX | Citation claims and source anchors are being checked. |
| 11 | `ARTIFACT_RENDERING` | AE | Preview or export files are being rendered. |
| 12 | `FINALIZING` | AE/CX | Links, lineage, and response metadata are being finalized. |
| 13 | `COMPLETED` | AE | Chat response and artifact links are ready. |

Stages can be skipped only when the execution mode does not need them. For
example, `GENERAL_ANSWER` can skip retrieval and citation validation if policy
allows ungrounded generation.

## Streaming And Polling

| Mode | Rule |
| --- | --- |
| Polling | `GET /api/v1/generations/{generation_id}/events` returns ordered events with cursor pagination. |
| Server-sent events | `GET /api/v1/generations/{generation_id}/events/stream` can stream mapped progress events. |
| Provider deltas | Raw provider token deltas stay inside MO/CX unless explicitly redacted and mapped. |
| Artifact jobs | AE render jobs expose the same event envelope and common job status. |

The MVP can implement polling first and add streaming later without changing the
event schema.

## Redaction Rules

Progress events must not include:

- Raw bearer tokens, service secrets, cookies, or API keys.
- Raw provider endpoint URLs, ports, model paths, or private deployment paths.
- Full private source documents or full provider prompts.
- Unredacted stack traces or SQL statements.
- Token-by-token generated text unless a streaming content policy explicitly
  allows it.

Events can include safe hashes, IDs, counts, confidence buckets, validation
statuses, usage summaries, and operator-safe failure codes.

## API Shape

Recommended service-local APIs:

```text
GET /api/v1/generations/{generation_id}/events
GET /api/v1/generations/{generation_id}/events/stream
GET /api/v1/artifact-render-jobs/{render_job_id}/events
GET /admin/v1/generation-events?trace_id=...
```

List responses use cursor pagination. Stream responses should support last
event ID resume when practical.

## Contract Tests To Derive

- Event envelopes include `event_id`, `event_schema_version`, `event_type`,
  `event_source_service`, `trace_id`, `request_id`, `occurred_at`, `sequence_no`,
  `job_status`, `current_stage`, and `progress_mode`.
- `job_status`, `current_stage`, and `event_type` remain separate fields.
- Streaming provider deltas are mapped to allowed progress event types before AE
  web receives them.
- Polling responses preserve deterministic sequence order and cursor metadata.
- Failed events include stable failure codes and never leak provider secrets or
  raw prompts.
- Artifact render job events use the same envelope as generation events.

## Next Inputs

This contract should feed:

- Generation failure, repair, and retry policy contract, starting from
  [Generation Failure + Repair/Retry Policy Contract](22_generation_failure_repair_retry_policy_contract.md).
- Chat workspace artifact link requirements.
- AG generation and artifact audit dashboard requirements, starting from
  [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md).
- Generation OpenAPI endpoint seed.
- Generation E2E acceptance scenario and contract test plan.
