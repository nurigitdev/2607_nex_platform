# Generation Routing Boundary Reconciliation

Status: Draft seed for Slice 425.

Sources:

- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- `NP-SRC-11`
  (`11_260723_NeX_MO_Model_Operations_Design_v1.3.md`)
- [Service Boundary Decision Record](../../12_service_boundary_decision_record.md)
- [AE Agent Orchestration Contract](../../13_ae_agent_orchestration_contract.md)
- [CX-to-AE Retrieval Context Package Contract](../../14_cx_ae_retrieval_context_package_contract.md)

This document reconciles a routing conflict introduced during early platform
distillation. Slice 423 and Slice 424 correctly made `nex-ae-api` the user-facing
agent owner, but they leaned too far toward direct `nex-ae-api` -> `nex-mo`
generation calls. The source design documents consistently prefer a
CX-mediated route for document generation so that retrieval evidence, prompt
package, citation lineage, and model request history stay tied together.

## Reconciled Decision

| Area | Decision | Status |
| --- | --- | --- |
| User-facing agent ownership | `nex-ae-api` owns intent, execution mode, template choice, user-facing system prompt policy, chat state, final formatting, and artifact links. | Freeze Now |
| Document-grounded generation route | `nex-ae-api` requests generation through `nex-cx`; `nex-cx` calls `nex-mo` stable generation API. | Freeze Now |
| Provider execution | `nex-mo` remains the only provider abstraction and runtime execution owner. | Freeze Now |
| Provider runtime direct access | AE and CX never call raw provider URLs or ports. CX calls MO stable APIs only. | Freeze Now |
| General answer route | MVP should prefer the same CX-mediated LLM route when a model call is needed, unless a future explicit direct-AE-to-MO policy is approved. | Freeze Candidate |
| LLM-assisted intent classification | AE owns the final intent decision; if LLM assistance is needed, AE should request an intent-analysis facade through CX so MO calls remain centrally mediated. | Freeze Candidate |

## Why CX Mediates Document Generation

| Benefit | Explanation |
| --- | --- |
| Evidence continuity | CX already owns search evidence, source anchors, citations, no-answer, and permission filtering. |
| Prompt package integrity | CX can build provider-facing prompt packages from retrieval evidence without leaking chunk/index internals to AE. |
| Generation auditability | CX can connect retrieval package ID, prompt package, structured draft, citation validation, and MO provider request metadata. |
| Provider governance | MO request history remains behind stable service-to-service calls, while provider ports stay private. |
| AE simplicity | AE can focus on user intent, template selection, chat state, progress UX, final formatting, and artifact links. |

## Canonical Routes

### Document Search

```text
nex-ae-web
-> nex-ae-api
-> nex-cx search/retrieval package
-> nex-ae-api search result formatting
-> nex-ae-web
```

CX may call MO internally for query embedding or reranking, but AE never calls
MO for search.

### Document-Grounded Answer

```text
nex-ae-web
-> nex-ae-api
-> nex-cx retrieval context package
-> nex-ae-api generation intent/template/output policy
-> nex-cx generation request
-> nex-cx provider-facing prompt package
-> nex-mo generation stable API
-> nex-cx generation record and evidence lineage
-> nex-ae-api final answer/chat response
-> nex-ae-web
```

### Document Generation

```text
nex-ae-web
-> nex-ae-api
-> nex-cx retrieval context package
-> nex-ae-api content template and rendering target selection
-> nex-cx generation request
-> nex-cx structured draft/citation validation
-> nex-mo generation stable API
-> nex-cx generation result
-> nex-ae-api artifact rendering/linking/chat response
-> nex-ae-web
```

### General Answer Or Intent Analysis

The MVP should avoid direct AE-to-MO calls until a separate policy approves
them. When LLM assistance is needed, use a narrow CX facade:

```text
nex-ae-api
-> nex-cx intent-analysis or general-generation facade
-> nex-mo generation stable API
-> nex-cx model-call metadata
-> nex-ae-api final intent or chat response
```

This keeps the model-call audit path consistent while leaving AE as the owner of
the final user-facing decision.

## Ownership Split

| Object | Owner | Notes |
| --- | --- | --- |
| `execution_mode` | AE | Explicit user mode wins; AE records final decision. |
| Intent-analysis prompt policy | AE | AE decides why analysis is needed and how to interpret the result. |
| Intent-analysis provider call | CX -> MO | CX mediates the model call if LLM classification is needed. |
| Retrieval context package | CX | Permission-filtered evidence, scores, no-answer, and package hash. |
| Content template selection | AE | User selection or AE policy. |
| Provider-facing prompt package | CX | Built from retrieval package, selected evidence, template metadata, and output schema. |
| Generation provider request | CX -> MO | CX calls MO stable API by capability alias. |
| Provider usage metadata | MO -> CX -> AE | MO returns tokens/latency/provider metadata; CX persists generation lineage; AE stores user-facing run metadata. |
| Structured draft validation | CX | CX validates citations and source lineage before returning result. |
| Artifact rendering and links | AE | AE renders or coordinates output formats and owns chat-download links. |

## Request Direction

| Request | Caller | Receiver | Notes |
| --- | --- | --- | --- |
| `POST /api/v1/retrieval-context-packages` | AE | CX | Search, summary, and generation grounding. |
| `POST /api/v1/generations` | AE | CX | Document-grounded generation request. |
| `POST /api/v1/intent-analyses` | AE | CX | Optional LLM-assisted intent classification facade. |
| `POST /api/v1/generations` | CX | MO | Provider-facing generation call through MO stable API. |
| `GET /api/v1/generations/{generation_id}` | AE | CX | Generation result, structured draft, citation status, MO usage metadata. |
| Artifact preview/download APIs | Web | AE | User-facing artifact links stay AE-owned. |

The repeated `/api/v1/generations` name is service-local. Route ownership must
be read with the service host: AE calls the CX generation API; CX calls the MO
generation API.

## Updated Guardrails

| Guardrail | Rule |
| --- | --- |
| No AE direct provider call for document generation | AE must call CX for document-grounded generation. |
| No raw provider URL | CX must call MO stable API, not vLLM or provider runtime ports. |
| No prompt package leakage | AE sends template/output policy and selected evidence references; CX builds provider-facing prompt packages. |
| No unsupported grounded answer | CX no-answer or low-confidence status blocks confident grounded generation unless AE changes the mode to general answer. |
| No ownership confusion | CX owns generation execution record and evidence lineage; AE owns chat state and artifact links. |
| No hidden model-call history | MO usage metadata must flow back through CX to AE-visible run history. |

## Contract Tests To Derive

- AE document-generation request targets CX, not MO.
- CX document-generation request targets MO stable API, not a raw provider URL.
- AE intent decision can be explicit/rule-based without an LLM call.
- LLM-assisted intent analysis, when enabled, is mediated by CX and still
  returns a structured result for AE to accept or override.
- CX generation request includes retrieval package ID/hash, selected evidence
  IDs, content template ID, output schema ID, and generation profile.
- CX generation result includes structured draft status, citation validation,
  source lineage, and MO usage metadata.
- AE stores chat message, final formatting, artifact references, and links
  after CX generation succeeds.
- General answer routing remains a policy-controlled exception and direct
  AE-to-MO generation requires a later explicit policy.

## Documentation Updates Required

This decision supersedes the direct `nex-ae-api` -> `nex-mo` default route in
Slice 423 and Slice 424. Those documents should keep AE as the agent owner but
route document-grounded generation and LLM-assisted intent classification
through CX unless a later decision explicitly changes the policy.

The first AE-to-CX generation request package is defined in
[AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md).
The CX-to-MO provider-facing generation contract is defined in
[CX-to-MO Generation Provider Contract](../../17_cx_mo_generation_provider_contract.md).
The CX generation execution and lineage record is defined in
[CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md).
The structured draft and citation schema is defined in
[Structured Draft + Citation Schema Contract](19_structured_draft_citation_schema_contract.md).
The AE artifact rendering handoff is defined in
[AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md).
