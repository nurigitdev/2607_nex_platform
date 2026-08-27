import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
  buildRepairedResponseReviewSurfaceFromProjection
} from "../src/repairedResponseReviewClient.js";
import {
  AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
  AE_WEB_REPAIRED_RESPONSE_DECISION_CLIENT_SCHEMA_VERSION,
  RepairedResponseDecisionClientError,
  buildRepairedResponseDecisionRequest,
  buildRepairedResponseDecisionSubmissionResult,
  createFetchRepairedResponseDecisionClient,
  createMockRepairedResponseDecisionClient,
  findSensitiveRepairedResponseDecisionKeys,
  repairedResponseDecisionRoute
} from "../src/repairedResponseDecisionClient.js";

function projection(overrides = {}) {
  return {
    projection_schema_version: AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
    projection_status: "READY_FOR_DECISION",
    repaired_response_handoff_id: "handoff-001",
    handoff_request_id: "request-001",
    owner_scope: {
      tenant_id: "tenant-local",
      workspace_id: "workspace-local",
      owner_user_id: "owner-local"
    },
    conversation_scope: {
      chat_document_id: "chat-doc-local",
      interaction_id: "interaction-001"
    },
    review_card: {
      title: "수정 응답 검토",
      presentation_mode: "side_by_side_review",
      default_action: "review_repair"
    },
    original_response_ref: {
      cx_generation_id: "cx-gen-parent-001",
      link: "/api/v1/generations/cx-gen-parent-001",
      parent_generation_mutated: false
    },
    repaired_response_summary: {
      cx_generation_id: "cx-gen-repair-001",
      status: "SUCCEEDED",
      alias: "default",
      provider_capability: "grounded_generation",
      finish_reason: "stop",
      output_hash: "a".repeat(64),
      output_preview: "근거 누락 지점을 보강했습니다.",
      usage: { input_tokens: 10, output_tokens: 12, total_tokens: 22 },
      quality_summary: {
        grounding_required: true,
        retrieval_package_id: "cx-ret-001",
        grounded_response_quality_status: "PASS"
      }
    },
    lineage_summary: {
      remediation_action_id: "remediation-001",
      lineage_status: "REPAIRED",
      action_type: "regenerate_answer",
      lineage_type: "repair",
      attempt_no: 2,
      result_ref: { kind: "cx_generation", id: "cx-gen-repair-001" }
    },
    decision_controls: {
      available_actions: [
        "view_original",
        "view_repaired",
        "accept_repair",
        "keep_original",
        "view_lineage"
      ],
      primary_actions: ["accept_repair", "keep_original"],
      secondary_actions: ["view_original", "view_repaired", "view_lineage"],
      decision_submit_path:
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001/decisions",
      idempotency_key_hint: "request-001"
    },
    links: {
      handoff:
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001",
      original_generation: "/api/v1/generations/cx-gen-parent-001",
      repaired_generation: "/api/v1/generations/cx-gen-repair-001",
      remediation_execution:
        "/api/v1/generations/cx-gen-parent-001/remediation-executions/remediation-001"
    },
    redaction_summary: {
      raw_output_included: false,
      raw_prompt_included: false,
      raw_source_text_included: false,
      evidence_text_included: false,
      provider_detail_included: false,
      storage_path_included: false
    },
    checked_at: "2026-08-27T00:01:00Z",
    ...overrides
  };
}

function reviewSurface() {
  return buildRepairedResponseReviewSurfaceFromProjection(projection());
}

function decisionResponse(overrides = {}) {
  return {
    decision_schema_version: AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
    repaired_response_decision_id: "decision-001",
    decision_request_id: "decision-request-001",
    decision_status: "RECORDED",
    decision_action: "accept_repair",
    repaired_response_handoff_id: "handoff-001",
    handoff_request_id: "request-001",
    trace_id: "trace-local",
    request_id: "request-local",
    tenant_id: "tenant-local",
    workspace_id: "workspace-local",
    owner_user_id: "owner-local",
    chat_document_id: "chat-doc-local",
    interaction_id: "interaction-001",
    actor_claims_ref: {
      actor_type: "user",
      actor_id: "owner-local",
      tenant_id: "tenant-local"
    },
    parent_cx_generation_id: "cx-gen-parent-001",
    repair_cx_generation_id: "cx-gen-repair-001",
    selected_cx_generation_id: "cx-gen-repair-001",
    rejected_cx_generation_id: "cx-gen-parent-001",
    remediation_action_id: "remediation-001",
    decision_reason_codes: ["prefer_repaired"],
    decision_comment_hash: null,
    decision_comment_preview: null,
    metadata: {
      submitted_via: "chat_review",
      raw_prompt_stored: false,
      raw_generation_output_stored: false,
      raw_source_text_stored: false,
      raw_evidence_stored: false,
      free_text_comment_storage: "hash_and_short_preview_only",
      parent_generation_mutated: false
    },
    created_at: "2026-08-27T00:03:00Z",
    updated_at: "2026-08-27T00:03:00Z",
    ...overrides
  };
}

function jsonResponse({ ok = true, status = 202, payload }) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

describe("AE Web repaired response decision client", () => {
  it("builds a safe owner-scoped decision request from a review surface", () => {
    const request = buildRepairedResponseDecisionRequest({
      reviewSurface: reviewSurface(),
      action: "accept_repair",
      reasonCodes: ["citation_fixed", "prefer_repaired", "citation_fixed"],
      decisionComment: "The repaired response now matches the cited source.",
      actorClaimsRef: {
        actor_type: "user",
        actor_id: "owner-local",
        tenant_id: "tenant-local"
      }
    });

    assert.equal(
      request.decision_client_schema_version,
      AE_WEB_REPAIRED_RESPONSE_DECISION_CLIENT_SCHEMA_VERSION
    );
    assert.equal(
      repairedResponseDecisionRoute("interaction/001", "handoff/001"),
      "/api/v1/chat/interactions/interaction%2F001/repaired-response-handoffs/handoff%2F001/decisions"
    );
    assert.equal(request.method, "POST");
    assert.equal(request.route, projection().decision_controls.decision_submit_path);
    assert.equal(request.payload.decision_action, "accept_repair");
    assert.deepEqual(request.payload.decision_reason_codes, [
      "citation_fixed",
      "prefer_repaired"
    ]);
    assert.deepEqual(request.payload.actor_claims_ref, {
      actor_type: "user",
      actor_id: "owner-local",
      tenant_id: "tenant-local"
    });
    assert.equal(request.metadata.rawPromptIncluded, false);
    assert.doesNotMatch(
      JSON.stringify(request),
      /raw_prompt|raw_generation_output|source_text|service_token|database_url|provider_url|storage_path/
    );
  });

  it("submits mock decisions and normalizes safe result summaries", async () => {
    const client = createMockRepairedResponseDecisionClient();
    const request = buildRepairedResponseDecisionRequest({
      reviewSurface: reviewSurface(),
      action: "keep_original"
    });
    const result = await client.submitRepairedResponseDecision(request);

    assert.equal(client.clientMode, "mock");
    assert.equal(result.decision_schema_version, AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION);
    assert.equal(result.status, "RECORDED");
    assert.equal(result.action, "keep_original");
    assert.equal(result.reasonCount, 1);
    assert.equal(result.commentPreviewPresent, false);
    assert.equal(result.metadata.rawGenerationOutputRendered, false);
  });

  it("posts fetch decisions with same-origin credentials", async () => {
    const calls = [];
    const client = createFetchRepairedResponseDecisionClient({
      baseUrl: "/ae-api",
      fetchImpl: async (url, options) => {
        calls.push({ url, options, body: JSON.parse(options.body) });
        return jsonResponse({ payload: decisionResponse() });
      }
    });
    const request = buildRepairedResponseDecisionRequest({
      reviewSurface: reviewSurface(),
      action: "accept_repair",
      decisionRequestId: "decision-request-001"
    });
    const result = await client.submitRepairedResponseDecision(request);

    assert.equal(result.clientMode, "fetch");
    assert.equal(
      calls[0].url,
      "/ae-api/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001/decisions"
    );
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.equal(calls[0].body.decision_request_id, "decision-request-001");
  });

  it("maps HTTP, network, missing fetch, and invalid response failures", async () => {
    const httpClient = createFetchRepairedResponseDecisionClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 409,
          payload: {
            error_code: "ae.repaired_response_decision_scope_mismatch",
            detail: "scope mismatch",
            retryable: false
          }
        })
    });
    const request = buildRepairedResponseDecisionRequest({
      reviewSurface: reviewSurface(),
      action: "accept_repair"
    });

    await assert.rejects(
      () => httpClient.submitRepairedResponseDecision(request),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "ae.repaired_response_decision_scope_mismatch"
    );

    const networkClient = createFetchRepairedResponseDecisionClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.submitRepairedResponseDecision(request),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    assert.throws(
      () => createFetchRepairedResponseDecisionClient({ fetchImpl: "bad" }),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => buildRepairedResponseDecisionSubmissionResult({}),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "DECISION_RESPONSE_INVALID"
    );
    await assert.rejects(
      () =>
        createMockRepairedResponseDecisionClient({
          responseFactory: () => ({ decision_schema_version: "old" })
        }).submitRepairedResponseDecision(request),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "DECISION_RESPONSE_INVALID"
    );
  });

  it("rejects unsupported actions, reasons, comments, and sensitive keys", () => {
    assert.deepEqual(
      findSensitiveRepairedResponseDecisionKeys({
        nested: [{ raw_prompt: "private" }, { service_token: "private" }]
      }),
      ["nested[0].raw_prompt", "nested[1].service_token"]
    );
    assert.throws(
      () =>
        buildRepairedResponseDecisionRequest({
          reviewSurface: reviewSurface(),
          action: "archive"
        }),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "DECISION_ACTION_UNSUPPORTED"
    );
    assert.throws(
      () =>
        buildRepairedResponseDecisionRequest({
          reviewSurface: reviewSurface(),
          action: "accept_repair",
          reasonCodes: ["unsafe_raw"]
        }),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "DECISION_REASON_CODE_UNSUPPORTED"
    );
    assert.throws(
      () =>
        buildRepairedResponseDecisionRequest({
          reviewSurface: reviewSurface(),
          action: "accept_repair",
          decisionComment: "x".repeat(241)
        }),
      error =>
        error instanceof RepairedResponseDecisionClientError &&
        error.status === "DECISION_COMMENT_TOO_LONG"
    );
    assert.throws(
      () =>
        buildRepairedResponseDecisionRequest({
          reviewSurface: {},
          action: "accept_repair"
        }),
      error => error.status === "REVIEW_SURFACE_INVALID"
    );
  });
});
