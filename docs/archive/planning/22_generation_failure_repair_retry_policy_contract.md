# Generation Failure + Repair/Retry Policy Contract

Status: Draft seed for Slice 432.

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
- [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
- [Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)
- [Generation Progress Event Contract](21_generation_progress_event_contract.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)

This document freezes the first failure, repair, and retry policy for
generation. The goal is to make failed or incomplete generation recoverable
without hiding lineage, silently changing evidence, or making AE/CX/MO ownership
ambiguous.

## Recovery Actions

| Action | Owner | Meaning |
| --- | --- | --- |
| `retry` | Same service that failed | Re-run the same operation with the same inputs and hashes. |
| `repair` | CX or AE depending on failure | Fix structured draft, citation, template completeness, or artifact rendering without fresh retrieval. |
| `regenerate` | AE orchestrates, CX executes | Create a new CX generation execution, usually with the same retrieval package and changed prompt/output policy. |
| `sectional_retry` | CX/AE | Re-run or repair only affected sections while preserving other validated sections. |
| `fresh_retrieval_regenerate` | AE/CX | Re-run retrieval first, then create a new generation execution. |
| `manual_accept_with_warning` | AE | User/operator accepts a partial result with explicit warning and audit record. |
| `cancel` | AE/CX/MO | Stop pending or running work; terminal lineage is preserved. |

Terminal records must not return to `RUNNING`. Recovery creates a new lineage
edge or a new render job/version.

## Failure Classification

| Failure Class | Typical Code | Retryability | Default Action |
| --- | --- | --- | --- |
| Request contract invalid | `cx.generation_request_invalid` | No | Reject and ask AE to fix request package. |
| Retrieval no-answer | `cx.no_answer_generation_blocked` | No direct retry | Ask user to broaden scope or switch mode. |
| Low confidence | `cx.low_confidence_generation_blocked` | Conditional | Warn, ask confirmation, or regenerate after fresh retrieval. |
| Prompt/template mismatch | `cx.prompt_template_mismatch` | No | AE fixes compatibility and submits new request. |
| MO admission throttled | `mo.admission_throttled` | Yes | Retry after policy delay with same prompt package hash. |
| MO provider timeout | `mo.provider_timeout` | Yes | Retry with same inputs, or reduce output scope. |
| MO provider runtime failed | `mo.provider_runtime_failed` | Conditional | Retry same route once, then switch route only by policy. |
| Structured draft invalid | `cx.structured_draft_schema_invalid` | Yes | Repair normalized draft or regenerate. |
| Citation validation failed | `cx.citation_validation_failed` | Conditional | Citation repair, sectional retry, or block. |
| Required section missing | `cx.required_section_missing` | Yes | Sectional retry or regenerate with stricter template policy. |
| Artifact render failed | `ae.render_job_failed` | Yes | Retry render job with same artifact version inputs. |
| Artifact access denied | `ae.artifact_access_denied` | No | Recheck claims or deny. |

All failure records use `application/problem+json` for API errors and the
progress event envelope for timeline visibility.

## Lineage Rules

| Field | Required | Notes |
| --- | --- | --- |
| `parent_generation_id` | Yes for generation retry/repair | Original CX generation execution. |
| `lineage_type` | Yes | `retry`, `repair`, `regenerate`, `sectional_retry`, or `fresh_retrieval_regenerate`. |
| `lineage_reason` | Yes | Stable reason code or user/operator reason. |
| `attempt_no` | Yes | Monotonic per lineage chain. |
| `supersedes_generation_id` | No | Present when AE should show the new result instead of the old one. |
| `reuse_retrieval_package` | Yes | Whether the original retrieval package ID/hash is preserved. |
| `changed_fields` | Yes | Safe list of request/policy fields changed for recovery. |
| `recovery_policy_hash` | Yes | Hash over policy used to choose the action. |

Retries preserve the original retrieval package ID/hash unless
`lineage_type=fresh_retrieval_regenerate`.

## Repair Boundaries

| Repair Target | Owner | Allowed Without Fresh Generation |
| --- | --- | --- |
| Provider timeout | CX/MO | Same prompt package retry with same hash. |
| Invalid JSON shape | CX | Parse/normalize/repair when provider output contains recoverable content. |
| Missing required section | CX/AE | Sectional retry or regenerate; AE may adjust template only through a new request. |
| Invalid citation anchor | CX | Replace citation only with evidence from the same retrieval package. |
| Unsupported block type | CX/AE | Map to safe block type or fail if meaning would change. |
| Markdown render issue | AE | Retry render job with same source draft hash. |
| DOCX/PDF render issue | AE | Retry or create failed file record; do not ask CX to regenerate by default. |

Repair must not invent citations, broaden permissions, or silently switch source
evidence.

## Policy Inputs

| Policy Input | Owner | Notes |
| --- | --- | --- |
| `quality_policy` | AE/CX | No-answer, low-confidence, citation, and completeness behavior from request. |
| `generation_parameters` | AE/CX | Max tokens, timeout, temperature, streaming, and output target. |
| `provider_admission_policy` | MO | Retry-after, throttling, route health, and workload class rules. |
| `template_policy` | AE | Required sections and output schema requirements. |
| `render_policy` | AE | Target formats, file naming, style template, and converter settings. |
| `operator_override_policy` | AG | Whether manual accept, forced retry, or degraded operation is allowed. |

Every recovery decision should store enough policy hashes to explain why the
system retried, repaired, regenerated, or blocked.

## Progress Events

Failure and recovery actions must emit progress events from Slice 431.

| Event Type | Required Detail |
| --- | --- |
| `generation.failed` | Failure class, code, retryable, owner service, failed stage. |
| `generation.retry.scheduled` | Parent generation ID, retry-after, attempt number. |
| `generation.repair.started` | Repair target, policy hash, affected sections or citations. |
| `generation.repair.completed` | Validation status, changed section/citation counts. |
| `generation.regenerate.started` | Whether retrieval package is reused or refreshed. |
| `generation.manual_accept_with_warning` | Actor ref, warning codes, accepted risk summary. |

Events must be redacted. Raw prompts, tokens, provider secrets, and full source
documents are not progress details.

## User-Facing Behavior

| Case | AE UX Behavior |
| --- | --- |
| No-answer blocked | Explain that permitted evidence was insufficient; offer broaden scope or general answer mode. |
| Low confidence warning | Show caution and let user confirm when policy allows. |
| Required section missing | Show missing sections and offer sectional retry/regenerate. |
| Citation invalid | Show unsupported citation summary; do not present as fully grounded. |
| Provider timeout | Show retryable system delay and preserve original request. |
| Render failed | Keep generation result visible if valid; show artifact export retry. |

AE should never hide a failed validation behind a polished artifact.

## Contract Tests To Derive

- Terminal CX generation records create recovery lineage instead of mutating back
  to `RUNNING`.
- Same-input retry preserves retrieval package hash and provider prompt package
  hash.
- Fresh retrieval regenerate stores a new retrieval package ID/hash.
- Citation repair can only use evidence from the same retrieval package.
- Render job retry preserves artifact version source hashes.
- Manual accept with warning stores actor ref, warning code, and policy hash.
- Failure progress events include stable code, failed stage, retryability, and
  no provider secrets.

## Next Inputs

This contract should feed:

- Chat workspace artifact link requirements, starting from
  [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md).
- Prompt/template/output compatibility rule matrix, starting from
  [Prompt/Template/Output Compatibility Matrix](24_prompt_template_output_compatibility_matrix.md).
- AG generation and artifact audit dashboard requirements, starting from
  [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md).
- Generation OpenAPI endpoint seed.
- Generation E2E acceptance scenario and contract test plan.
