# Generation E2E Acceptance + Contract Test Plan

Status: Draft seed for Slice 438.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-03`
  (`03_260723_NeX_Platform_Common_Foundation_Design_v1.6.md`)
- [Testing Strategy Skeleton](./archive/planning/05_testing_strategy_skeleton.md)
- [AE Agent Orchestration Contract](13_ae_agent_orchestration_contract.md)
- [CX-to-AE Retrieval Context Package Contract](14_cx_ae_retrieval_context_package_contract.md)
- [AE-to-CX Generation Request Package Contract](16_ae_cx_generation_request_package_contract.md)
- [CX-to-MO Generation Provider Contract](17_cx_mo_generation_provider_contract.md)
- [CX Generation Execution Record + Lineage Contract](./archive/planning/18_cx_generation_execution_record_lineage_contract.md)
- [Structured Draft + Citation Schema Contract](./archive/planning/19_structured_draft_citation_schema_contract.md)
- [AE Artifact Rendering Handoff Contract](./archive/planning/20_ae_artifact_rendering_handoff_contract.md)
- [Generation Progress Event Contract](./archive/planning/21_generation_progress_event_contract.md)
- [Generation Failure + Repair/Retry Policy Contract](./archive/planning/22_generation_failure_repair_retry_policy_contract.md)
- [Chat Workspace Artifact Link Requirements](./archive/planning/23_chat_workspace_artifact_link_requirements.md)
- [Prompt/Template/Output Compatibility Matrix](./archive/planning/24_prompt_template_output_compatibility_matrix.md)
- [AG Generation Artifact Audit Dashboard Requirements](./archive/planning/25_ag_generation_artifact_audit_dashboard_requirements.md)
- [Generation Contract JSON Schema Seed](./archive/planning/26_generation_contract_json_schema_seed.md)
- [Generation OpenAPI Endpoint Seed](./archive/planning/27_generation_openapi_endpoint_seed.md)

This document freezes the first end-to-end acceptance and contract test plan for
generation. It turns the Slice 424-437 contracts into executable verification
targets without requiring the first platform implementation to copy NeX-PCX code.

## Acceptance Spine

The primary generation flow must prove the complete handoff:

1. AE accepts a user prompt in a chat workspace.
2. AE selects intent, execution mode, template, prompt contract, output
   contract, and quality policy.
3. AE requests a retrieval context package from CX when grounding is required.
4. CX returns permission-filtered evidence, source anchors, scoring metadata,
   confidence/no-answer status, and package hash.
5. AE sends an AE-to-CX generation request package that references the retrieval
   package and selected compatibility rule.
6. CX validates retrieval, permission, compatibility, output schema, quality
   policy, and generation parameters.
7. CX builds a provider-facing prompt package and calls MO by capability alias.
8. MO admits the request, executes or mocks the provider, and returns usage,
   finish reason, latency, and safe runtime metadata.
9. CX validates structured draft shape, citations, source anchors, and template
   completeness.
10. AE creates artifact metadata, renders requested formats, and links the
    artifact to the assistant chat message.
11. AG can read a redacted timeline, generation detail, artifact lineage,
    provider usage, compatibility summary, and recovery/audit events.

A build is not generation-ready until this spine passes with mock providers.
Live provider smoke can remain a separate evidence gate.

## Required Test Layers

| Layer | Required Coverage |
| --- | --- |
| Schema contract | Validate sample request/response/event/artifact/audit payloads against JSON Schema. |
| API contract | Validate headers, status codes, error envelope, idempotency, pagination, and redaction. |
| Service boundary | Prove AE does not call MO directly for document-grounded generation and AG does not read service databases. |
| Orchestration integration | Run the mock end-to-end flow across AE facade, CX retrieval/generation, MO mock provider, AE artifact, and AG audit reads. |
| Failure/recovery | Exercise no-answer, low confidence, provider timeout, template mismatch, citation failure, render failure, retry, repair, and regenerate. |
| UI acceptance | Capture Korean-default AE chat/artifact flow and AG audit detail when UI exists. |
| Live smoke | Separately verify DGX/vLLM generation route with a short request and redacted evidence. |

The first implementation can run mock e2e in CI and live smoke manually or in a
protected environment.

## Golden Scenarios

| Scenario ID | Name | Expected Result |
| --- | --- | --- |
| `GEN-E2E-001` | General answer without retrieval | AE selects `GENERAL_ANSWER`, CX retrieval is skipped, no citation is claimed, and AG shows no source evidence. |
| `GEN-E2E-002` | Grounded answer with evidence | CX returns evidence package, generation cites valid source anchors, AE shows answer, and AG shows citation status. |
| `GEN-E2E-003` | Report generation with artifact export | AE selects report template and `report_generation_v1`, CX validates required sections, AE renders MD/DOCX, and chat shows artifact link. |
| `GEN-E2E-004` | No-answer guardrail | CX returns no-answer or low evidence, AE blocks grounded generation or asks for mode change, and AG shows guardrail reason. |
| `GEN-E2E-005` | Template/prompt mismatch | AE or CX rejects report template paired with grounded answer prompt before MO call. |
| `GEN-E2E-006` | Provider timeout retry | MO timeout creates failed event, retry preserves retrieval and prompt hashes, and lineage is visible. |
| `GEN-E2E-007` | Citation repair | Invalid citation triggers repair path limited to the same retrieval package. |
| `GEN-E2E-008` | Render failure retry | Valid CX draft remains visible while AE render retry creates a new render job. |
| `GEN-E2E-009` | Artifact download permission check | Unauthorized actor cannot download; authorized actor receives the requested format. |
| `GEN-E2E-010` | AG redacted audit export | AG export includes IDs, hashes, statuses, and summaries but excludes prompts, secrets, provider paths, and raw documents. |

These scenarios should become executable tests before generation is declared
MVP-complete.

## Contract Test Matrix

| Contract | Must Test |
| --- | --- |
| Retrieval package | Package hash mismatch, stale package, selected evidence subset, permission-filtered no-answer. |
| AE-to-CX request | Required fields, idempotency, raw provider field rejection, explicit prompt/template versions. |
| CX-to-MO request | Capability alias, workload class, response format, timeout/cancel, secret redaction. |
| CX execution record | Status/stage separation, prompt/evidence hashes, MO usage, terminal immutability, retry lineage. |
| Structured draft | Required sections, block shape, citation claim refs, unsupported block rejection, source anchor readiness. |
| Artifact handoff | Draft hash guard, allowed target formats, render job status, no raw filesystem path. |
| Progress event | Sequence ordering, polling/SSE envelope parity, stage taxonomy, safe failure details. |
| Recovery policy | Same-input retry, fresh retrieval regenerate, citation repair boundary, manual warning acceptance. |
| Compatibility rule | Active rule selection, mismatch rejection, schema/provider capability validation. |
| AG audit | Cursor filters, redaction, operator note isolation, service API-only reads. |

## Mock Provider Requirements

Mock MO generation should support:

- Successful text response with usage and latency metadata.
- Structured JSON response matching `cx_structured_draft.v1`.
- Streaming progress events mapped to `generation_progress_event.v1`.
- Provider timeout.
- Admission throttled.
- Invalid JSON or missing section output.
- Citation label mismatch output.

Mocks must be deterministic enough for regression tests and honest enough to
exercise failure branches.

## Evidence Artifacts

| Evidence | Required For |
| --- | --- |
| Contract fixture payloads | Every schema and OpenAPI contract. |
| Mock e2e run log | Every generation acceptance scenario. |
| Coverage summary | Implementation slices that add executable code. |
| Playwright screenshots | User-visible AE/AG UI changes. |
| Live DGX/vLLM smoke markdown | Protected/live provider verification. |
| Redaction sample | AG audit/export and error envelope checks. |

For documentation-only slices, `git diff --check` and link/keyword checks are
sufficient unless executable behavior changed.

## Exit Criteria

Generation MVP can move from design to implementation when:

- Schema catalog and OpenAPI endpoint files can be generated from the seed docs.
- Mock e2e passes `GEN-E2E-001` through `GEN-E2E-010`.
- Contract tests cover the required request, response, event, artifact, and
  audit payloads.
- No service writes data outside its ownership boundary.
- Provider secrets, raw prompts, raw source documents, and filesystem paths are
  redacted from public and AG views.
- AE chat can show a generated artifact link with source/citation/quality
  metadata.
- AG can trace the same generation from user prompt through artifact download.

## Next Inputs

This plan should feed:

- MVP SRS assembly, starting from
  [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md).
- Service-specific implementation backlog for generation MVP.
- Contract fixture and example payload creation.
- OpenAPI generation and contract test automation.
- AE and AG UI acceptance scenario planning.
