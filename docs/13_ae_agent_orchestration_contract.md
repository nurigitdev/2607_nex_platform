# AE Agent Orchestration Contract

Status: Draft seed for Slice 423.

Sources:

- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- [Service Boundary Decision Record](12_service_boundary_decision_record.md)
- NeX-PCX generation, template, artifact, chat, search, and summary slice
  lessons.

This document defines the first `nex-ae-api` agent orchestration contract. The
agent is not an unconstrained autonomous worker in the MVP. It is a bounded orchestrator
that turns a user request into explicit service calls, preserves traceability,
and returns a chat/workspace response with durable artifact links when needed.

## Decision Summary

| Decision | Status | Rationale |
| --- | --- | --- |
| `nex-ae-api` is the user-facing agent API. | Freeze Now | It owns intent, mode, prompt, template, final formatting, generated artifact metadata, and chat/workspace state. |
| `nex-cx` owns retrieval context packages. | Freeze Now | CX owns corpus, permission-filtered search, evidence quality, source anchors, no-answer, chunks, BM25, vectors, and graph extension points. |
| `nex-mo` owns provider execution. | Freeze Now | MO owns embedding, reranking, generation, aliases, provider health, runtime metadata, timeout/cancel, and usage; document-generation calls reach MO through CX. |
| User-facing generation does not make CX the final answer owner. | Freeze Now | CX may expose compatibility or grounding helper endpoints later, but AE remains the orchestrator and final response owner. |
| Long-running work uses common job semantics. | Freeze Now | Generation, report creation, summary, and artifact rendering can take time and need progress feedback. |
| Explicit mode can override intent detection. | Freeze Candidate | Users and tests need predictable behavior while intent automation matures. |

## Supported MVP Execution Modes

| Mode | User Intent | Required Services | Output |
| --- | --- | --- | --- |
| `GENERAL_ANSWER` | Ask a general question without document grounding. | AE -> CX general-generation facade -> MO generation, unless a later direct-AE-to-MO policy is approved. | Chat answer. |
| `DOCUMENT_SEARCH` | Find relevant source passages. | AE -> CX search. | Evidence list with source context. |
| `GROUNDED_ANSWER` | Answer using permitted documents. | AE -> CX retrieval package -> AE generation policy -> CX generation API -> MO generation. | Citation-aware chat answer. |
| `DOCUMENT_SUMMARY` | Summarize selected or searched documents. | AE -> CX document/retrieval package -> AE summary policy -> CX generation API -> MO generation. | Summary answer or Markdown artifact. |
| `DOCUMENT_GENERATION` | Create a report, proposal, memo, or similar document. | AE -> CX retrieval package -> AE template/output policy -> CX generation API -> MO generation -> AE artifact. | Generated artifact plus chat response. |
| `ARTIFACT_TRANSFORM` | Convert generated Markdown to another supported format. | AE artifact renderer. | Downloadable artifact. |

Deferred modes:

- Autonomous multi-step domain agent.
- Scheduled background assistant.
- External business-system action execution.
- Direct provider URL calls from AE.
- Direct AE-to-MO document-generation calls without an explicit later policy.

## Agent Orchestration Loop

```text
Browser
-> nex-ae-web
-> nex-ae-api
   1. Intake user prompt, selected workspace, selected document scope, and explicit mode.
   2. Validate user/session/service claims through nex-oa rules.
   3. Classify intent or honor explicit execution mode.
   4. Build retrieval request when document grounding is needed.
   5. Request retrieval context package from nex-cx.
   6. Validate no-answer, low-confidence, citation, and permission metadata.
   7. Select template and prompt contract.
   8. Build AE generation policy package with template, output, and prompt intent.
   9. Request nex-cx generation when an LLM call is needed.
  10. Let nex-cx build the provider-facing prompt package and call nex-mo.
  11. Run answer quality and citation guardrails using CX result metadata.
  12. Render and persist artifacts when needed.
  13. Persist chat message, activity, lineage, and links.
  14. Return response/progress to nex-ae-web.
```

## Package Contracts

The first implementation should keep these as JSON-compatible schemas before
creating a large shared code package.

### Agent Request Package

| Field | Owner | Notes |
| --- | --- | --- |
| `request_id` | AE | Correlates UI, job, logs, and service calls. |
| `chat_document_id` | AE | Current conversation/workspace target. |
| `actor_claims_ref` | OA/AE | Reference to validated user and service claims; do not copy raw tokens. |
| `user_prompt` | AE | Original user input, retained according to workspace retention policy. |
| `execution_mode` | AE | Explicit mode or intent-detected mode. |
| `language` | AE | Korean default; English supported. |
| `document_scope` | AE/CX | Selected group, collection, owner, classification, or global scope. |
| `output_contract` | AE | Chat answer, Markdown artifact, DOCX export, or future format. |

### Retrieval Context Package

| Field | Owner | Notes |
| --- | --- | --- |
| `retrieval_package_id` | CX | Stable ID or hash for reproducibility. |
| `query_text` | CX | Query after AE mode handling; preserve original prompt reference. |
| `retrieval_profile` | CX | Hybrid/BM25/vector/rerank policy and tokenizer metadata. |
| `permission_snapshot` | CX | Scope, actor, group, classification, and filtered-count metadata. |
| `evidence_items` | CX | Chunks, source anchors, scores, neighboring context, and citation labels. |
| `no_answer` / `confidence` | CX | Guardrail signal before generation. |
| `package_hash` | CX | Reproducibility anchor for AE generation history. |

### Generation Policy Package

| Field | Owner | Notes |
| --- | --- | --- |
| `prompt_contract_id` / `prompt_version` | AE | Template-aware prompt contract, not a free-form hidden string. |
| `template_id` / `template_version` | AE | Report/proposal/summary template selection. |
| `system_prompt_policy` | AE | User-facing instruction policy, language, and citation rules. |
| `generation_parameters` | AE/CX | Max tokens, temperature, streaming, stop rules, and output format. |
| `retrieval_package_ref` | AE/CX | Reference to CX package and hash, not copied ad hoc evidence only. |
| `provider_capability` | CX/MO | CX resolves provider-facing capability and calls MO by stable alias. |

### Agent Result Package

| Field | Owner | Notes |
| --- | --- | --- |
| `interaction_id` | AE | Chat/workspace message lineage. |
| `answer_text` | AE | Final user-facing answer after formatting. |
| `quality_metadata` | AE | Citation coverage, no-answer decision, template completeness, guardrail outcomes. |
| `artifact_refs` | AE | Markdown/DOCX/PDF or future artifacts with preview/download links. |
| `provider_usage` | MO/AE | Token and latency metadata returned by MO and stored in AE run history. |
| `source_refs` | CX/AE | Citation labels and source anchors for UI drilldown. |
| `trace_id` / `request_id` | Shared | Cross-service observability. |

## Document Generation Flow

| Step | Owner | Notes |
| --- | --- | --- |
| Intent detection | AE | Detect report/proposal/summary/edit intent; explicit user mode wins. |
| Retrieval planning | AE | Decide whether document grounding is required and choose CX search profile. |
| Similarity/hybrid search | CX | Applies permission filtering and returns evidence package. |
| Template selection | AE | Uses user choice or intent-derived default. |
| Prompt policy assembly | AE | Supplies user-facing system prompt policy, selected template, output contract, and selected evidence references. |
| Provider-facing prompt package | CX | Combines evidence, template metadata, citation rules, and output schema for MO. |
| Provider generation | CX -> MO | CX calls MO using capability alias and receives usage/runtime metadata. |
| Quality guardrail | AE with CX references | Checks citation coverage, missing sections, and no-answer/low-confidence signals. |
| Artifact rendering | AE | Creates Markdown-first artifact and optional DOCX/PDF exports later. |
| Workspace response | AE | Persists chat message, artifact links, lineage, and activity. |

CX-mediated generation routing:

- Source documents describe CX generation APIs and state that AE should not call
  MO directly for document generation.
- For the MVP boundary, CX generation APIs are the default document-grounded
  generation route.
- CX still must not own final chat state, artifact links, or user-facing
  formatting.
- The first hard contract to freeze is AE <-> CX retrieval context package.

## Job Stages

| Stage | User-Facing Meaning |
| --- | --- |
| `INTAKE` | Request received and validated. |
| `INTENT_DETECTED` | Execution mode selected. |
| `RETRIEVAL_REQUESTED` | Document grounding requested from CX. |
| `CONTEXT_PACKAGED` | Evidence package ready or no-answer identified. |
| `TEMPLATE_SELECTED` | Output template and prompt contract selected. |
| `PROMPT_POLICY_PACKAGED` | AE generation policy package prepared. |
| `CX_GENERATION_REQUESTED` | CX generation request submitted. |
| `GENERATION_RUNNING` | CX has called MO and provider generation is running. |
| `QUALITY_CHECKING` | Citation, confidence, and template completeness checked. |
| `ARTIFACT_RENDERING` | Downloadable artifact is being prepared. |
| `COMPLETED` | Chat response and links are ready. |

These are `current_stage` values, not `job_status` enum values.

## Guardrails

| Guardrail | Rule |
| --- | --- |
| No raw token logging | AE stores claim references and safe actor metadata, not bearer tokens. |
| No direct provider URL | AE calls CX for generation; CX calls MO by capability alias and never raw provider URLs. |
| No ungrounded citation | AE must not fabricate citations when CX package reports no usable evidence. |
| No hidden template mismatch | Prompt version must align with selected template version. |
| No evidence loss | AE generation history stores CX retrieval package ID/hash and CX generation ID. |
| No artifact-only answer | Chat response links to artifacts and summarizes the generated output. |
| No cross-service writes | AE does not write CX chunks/vectors/BM25 or MO provider registry. |

## Contract Tests To Derive

- Explicit `DOCUMENT_GENERATION` mode bypasses ambiguous intent detection.
- `GROUNDED_ANSWER` requires a CX retrieval package before CX-mediated MO generation.
- CX no-answer or low-confidence package prevents unsupported confident answer.
- AE generation policy package records prompt version, template version, output
  contract, and retrieval package hash.
- CX generation record stores provider capability, provider-facing prompt
  package metadata, and MO usage metadata.
- AE stores generated artifact references and chat lineage after provider
  success.
- Artifact transform can run from an existing AE artifact without re-querying CX.
- AE rejects direct provider URL requests and document-generation requests that
  try to call MO directly.
- AE propagates `trace_id`, `request_id`, and service-auth scope to CX and MO.

## Next Inputs

This contract should feed:

- CX-to-AE retrieval context package schema.
- AE-to-CX generation request package schema.
- AE chat workspace SRS requirements.
- CX-to-MO generation provider contract.
- AG operational event and job-stage display rules.

The CX-to-AE retrieval context package direction is detailed in
[CX-to-AE Retrieval Context Package Contract](14_cx_ae_retrieval_context_package_contract.md).
Generation routing is reconciled in
[Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md).
The first AE-to-CX generation request package is defined in
[AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md).
The CX-to-MO generation provider contract is defined in
[CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md).
The CX generation execution and lineage record is defined in
[CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md).
The structured draft and citation schema is defined in
[Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md).
The AE artifact rendering handoff is defined in
[AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md).
The generation progress event contract is defined in
[Generation Progress Event Contract](21_generation_progress_event_contract.md).
The chat workspace artifact link requirements are defined in
[Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md).
