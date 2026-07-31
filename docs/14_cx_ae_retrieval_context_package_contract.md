# CX-to-AE Retrieval Context Package Contract

Status: Draft seed for Slice 424.

Sources:

- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-13`
  (`13_260724_NeX_Platform_2Week_Barebone_SRS_v1.1.md`)
- [Service Boundary Decision Record](12_service_boundary_decision_record.md)
- [AE Agent Orchestration Contract](13_ae_agent_orchestration_contract.md)
- NeX-PCX search, no-answer, source context, permission explainability, rerank,
  generation, and citation-readiness slice lessons.

This document freezes the first contract direction between `nex-ae-api` and
`nex-cx`. The contract answers one practical question: when a user prompt enters
through `nex-ae-web`, what exactly does `nex-ae-api` request from `nex-cx`, and
what exactly does `nex-cx` return so that AE can search, summarize, generate,
or decline unsupported answers in a reproducible way?

## Direction Decision

| Interaction | Caller | Receiver | Contract Object | Decision |
| --- | --- | --- | --- | --- |
| User prompt intake | `nex-ae-web` | `nex-ae-api` | Agent request package | AE API receives prompt, workspace, explicit mode, selected scope, and UI language. |
| Intent/mode decision | `nex-ae-api` | Internal AE policy | Execution mode | AE API owns intent classification and explicit mode override. |
| Retrieval planning | `nex-ae-api` | `nex-cx` | Retrieval context request | AE asks CX for corpus-aware evidence, not for final user-facing generation ownership. |
| Retrieval response | `nex-cx` | `nex-ae-api` | Retrieval context package | CX returns ranked evidence, source anchors, permission snapshot, scores, and no-answer metadata. |
| Grounded generation | `nex-ae-api` | `nex-cx` | Generation request package | AE sends template/output policy and selected evidence; CX builds provider-facing prompt package and calls MO. |
| Provider execution | `nex-cx` | `nex-mo` | MO generation request | CX calls MO stable API by capability alias; AE does not call MO directly for document generation. |
| Workspace response | `nex-ae-api` | `nex-ae-web` | Agent result package | AE persists chat message, quality metadata, artifact links, and lineage. |

The preferred MVP route is:

```text
nex-ae-web
-> nex-ae-api
-> nex-cx retrieval context package
-> nex-ae-api prompt/template/system prompt package
-> nex-cx generation request
-> nex-mo generation provider
-> nex-cx generation record
-> nex-ae-api answer/artifact/chat response
-> nex-ae-web
```

The no-document route is policy-controlled. The MVP should prefer:

```text
nex-ae-web
-> nex-ae-api
-> nex-ae-api system prompt package
-> nex-cx general-generation facade
-> nex-mo generation provider
-> nex-ae-api chat response
-> nex-ae-web
```

Direct AE-to-MO generation requires a later explicit policy. CX-mediated routing
must not make CX the owner of chat state, template selection, final user-facing
formatting, or generated artifact links.

## Retrieval Context Request

`nex-ae-api` sends this request when the execution mode needs document grounding
or when AE needs a corpus-aware confidence probe before deciding whether to
answer.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | AE | Cross-service correlation ID. |
| `trace_id` | Yes | Shared | Distributed tracing reference. |
| `actor_claims_ref` | Yes | OA/AE | Validated claims reference; no raw token copy. |
| `chat_document_id` | Yes | AE | Used for lineage, not CX ownership. |
| `execution_mode` | Yes | AE | `DOCUMENT_SEARCH`, `GROUNDED_ANSWER`, `DOCUMENT_SUMMARY`, `DOCUMENT_GENERATION`, or probe mode. |
| `user_prompt` | Yes | AE | Original user prompt. |
| `query_text` | No | AE | Optional normalized query if AE rewrites prompt for search. |
| `document_scope` | Yes | AE/CX | Workspace-selected scope; CX validates against claims and corpus metadata. |
| `retrieval_profile` | No | AE/CX | Requested hybrid/vector/BM25/rerank policy; CX may choose default if omitted. |
| `top_k` | No | AE | Requested result count; CX enforces bounded limits. |
| `include_neighbors` | No | AE | Whether previous/next chunks should be included. |
| `include_source_preview` | No | AE | Whether source snippets/previews should be included for UI. |
| `purpose` | Yes | AE | `search`, `grounded_answer`, `summary`, `document_generation`, or `confidence_probe`. |

## Retrieval Context Package

`nex-cx` returns one package. AE should use the package ID/hash as the durable
reproducibility reference instead of copying ad hoc search rows into generation
history.

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `retrieval_package_id` | Yes | CX | Stable UUID or equivalent package identifier. |
| `package_hash` | Yes | CX | Hash over query, profile, permission snapshot, evidence IDs, and scoring metadata. |
| `status` | Yes | CX | `READY`, `NO_ANSWER`, `LOW_CONFIDENCE`, `PARTIAL`, or `FAILED`. |
| `query_text` | Yes | CX | Query used for retrieval after normalization. |
| `retrieval_profile` | Yes | CX | Search strategy, embedding profile, reranker profile, BM25 tokenizer, and chunk policy. |
| `permission_snapshot` | Yes | CX | Actor/scope/classification metadata and filtered-count summary. |
| `evidence_items` | Yes | CX | Ordered evidence list, empty when no usable evidence exists. |
| `source_summary` | Yes | CX | Source count, document count, chunk count, and source type summary. |
| `score_summary` | Yes | CX | Best score, score spread, ranker mix, rerank state, and confidence bucket. |
| `no_answer_reason` | No | CX | Required when status is `NO_ANSWER` or `LOW_CONFIDENCE`. |
| `warnings` | No | CX | Extraction gaps, stale index, permission filtering, tokenizer fallback, or provider failure notes. |
| `created_at` | Yes | CX | RFC3339 UTC timestamp. |

## Evidence Item Shape

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `evidence_id` | Yes | CX | Stable item ID inside the package. |
| `content_object_id` | Yes | CX | Source document/content object ID. |
| `content_version_id` | Yes | CX | Version used for retrieval. |
| `chunk_id` | Yes | CX | Primary chunk. |
| `chunk_policy_id` | Yes | CX | Policy such as `heading_1000_100`. |
| `source_anchor` | Yes | CX | Page, slide, sheet, paragraph, heading, block, or location metadata. |
| `citation_label` | Yes | CX | Stable label AE can show in generated answers. |
| `text` | Yes | CX | Chunk text or redacted text preview according to permissions. |
| `neighbor_context` | No | CX | Previous/next chunk references or snippets when requested. |
| `scores` | Yes | CX | Vector, BM25, hybrid, rerank, and final score fields where available. |
| `matched_terms` | No | CX | Keyword terms and tokenizer profile where available. |
| `permission_result` | Yes | CX | Whether and why the actor can see this item. |
| `quality_flags` | No | CX | Extraction warnings, stale embedding, stale BM25, low source confidence. |

## Status Semantics

| Status | Meaning | AE Behavior |
| --- | --- | --- |
| `READY` | Evidence is sufficient for the requested purpose. | AE may build grounded prompt and proceed to generation or display search results. |
| `NO_ANSWER` | CX found no usable evidence inside the permitted scope. | AE must not fabricate grounded claims; answer should say there is no supporting material. |
| `LOW_CONFIDENCE` | Evidence exists but confidence is below threshold. | AE may ask for clarification, show cautious answer, or require explicit user confirmation. |
| `PARTIAL` | Some evidence exists but warnings or missing source areas matter. | AE can proceed only with visible caveats and preserved warnings. |
| `FAILED` | Retrieval failed due to service/provider/index/runtime error. | AE returns an operational error with retry guidance and logs correlation IDs. |

## Permission Snapshot

The permission snapshot must be stable enough for later audit and generation
reproducibility.

| Field | Notes |
| --- | --- |
| `actor_type` / `actor_id` | User or service actor from OA-validated claims. |
| `scope_requested` | User-selected workspace, group, personal, team, collection, or global scope. |
| `scope_applied` | CX-normalized and claim-validated scope. |
| `classification_filter` | Classification levels used during retrieval. |
| `visible_document_count` | Documents visible before ranking. |
| `filtered_document_count` | Documents excluded by permission filtering. |
| `filtered_chunk_count` | Chunks excluded by permission filtering. |
| `policy_version` | Permission policy version used by CX. |

## Retrieval Profiles

| Profile Field | Notes |
| --- | --- |
| `search_strategy` | `vector`, `bm25`, `hybrid`, or later graph-augmented strategy. |
| `embedding_profile` | Model/profile ID, dimension, route alias, and index freshness. |
| `bm25_tokenizer` | Korean-friendly tokenizer such as `unicode_word_v1`, `korean_mixed_v1`, or optional MeCab profile. |
| `reranker_profile` | Reranker alias/model/profile and whether rerank completed. |
| `chunk_policy` | Chunk policy used during ingestion. |
| `source_context_policy` | Neighbor expansion and source preview behavior. |
| `confidence_policy` | No-answer and low-confidence thresholds. |

## Prompt And Generation Hand-Off

AE receives the retrieval context package and then decides the next call:

| AE Decision | Required Prior CX Package? | Next Receiver | Notes |
| --- | --- | --- | --- |
| Show search results only | Yes | `nex-ae-web` | AE formats evidence list and source drilldown. |
| Grounded answer | Yes | `nex-cx` generation API | AE sends generation policy and package hash; CX calls MO. |
| Document generation | Yes when source-grounded | `nex-cx` generation API | AE adds selected template, output contract, and package hash; CX calls MO. |
| General answer | No | `nex-cx` general-generation facade by default | Direct AE-to-MO requires a later policy. |
| No-answer response | Yes | `nex-ae-web` | AE returns no-answer/low-confidence response without generation unless explicitly overridden. |
| Provider execution | Yes for generation | `nex-mo` from CX | CX calls MO stable API and returns control to AE. |

Direction rule:

- AE requests retrieval from CX.
- CX returns evidence, permission, scoring, and confidence metadata to AE.
- AE owns prompt/template/system prompt assembly.
- AE calls CX for document-grounded generation by default.
- CX calls MO stable API for provider execution.
- Direct AE-to-MO generation requires a later explicit policy.
- AE returns chat response and artifact links to web users.

## Contract Tests To Derive

- AE sends `request_id`, `trace_id`, validated actor reference, execution mode,
  prompt, document scope, and purpose to CX.
- CX rejects unbounded scope requests when OA claims do not allow them.
- CX applies permission filtering before scoring output is returned.
- CX returns `NO_ANSWER` with `no_answer_reason` and empty evidence when no
  permitted evidence exists.
- CX returns `LOW_CONFIDENCE` with warnings when weak evidence exists.
- Evidence items include `chunk_id`, `chunk_policy_id`, `source_anchor`,
  `citation_label`, `scores`, and `permission_result`.
- AE persists `retrieval_package_id` and `package_hash` in generation history.
- AE does not call CX or MO generation for `NO_ANSWER` unless the user explicitly
  requests ungrounded/general answer mode.
- AE never sends raw provider URL, raw auth token, or direct CX database fields
  in the retrieval request.
- AE does not call MO directly for document-grounded generation.

## Next Inputs

This contract should feed:

- AE-to-CX generation request package contract.
- CX-to-MO generation provider request/response contract.
- CX search API skeleton.
- OA claim and service scope catalog.
- MVP SRS v0.1 retrieval/generation acceptance criteria.

Generation routing is reconciled in
[Generation Routing Boundary Reconciliation](15_generation_routing_boundary_reconciliation.md).
The AE-to-CX generation request package is defined in
[AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md).
The CX-to-MO generation provider request/response contract is defined in
[CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md).
