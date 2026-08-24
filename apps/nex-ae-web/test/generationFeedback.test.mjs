import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_GENERATION_FEEDBACK_SCHEMA_VERSION,
  AE_WEB_GENERATION_FEEDBACK_CLIENT_SCHEMA_VERSION,
  AE_WEB_GENERATION_FEEDBACK_SURFACE_SCHEMA_VERSION,
  GenerationFeedbackError,
  buildGenerationFeedbackRequest,
  buildGenerationFeedbackSubmissionResult,
  buildGenerationFeedbackSurfaceSummary,
  createFetchGenerationFeedbackClient,
  createGenerationFeedbackSurfaceState,
  createMockGenerationFeedbackClient,
  findSensitiveGenerationFeedbackKeys,
  generationFeedbackRoute
} from "../src/generationFeedback.js";

function feedbackResponse(overrides = {}) {
  return {
    feedback_schema_version: AE_GENERATION_FEEDBACK_SCHEMA_VERSION,
    feedback_id: "feedback-001",
    status: "RECORDED",
    tenant_id: "tenant-local",
    user_id: "owner-local",
    interaction_id: "interaction-001",
    chat_document_id: "chat-doc-001",
    cx_generation_id: "cx-gen-001",
    feedback_value: "negative",
    feedback_reasons: ["not_helpful", "citation_issue"],
    quality_issue_refs: [{ issue_code: "citation_missing" }],
    created_at: "2026-08-25T00:00:00Z",
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

describe("AE Web generation feedback client and surface", () => {
  it("builds safe feedback requests for the AE feedback facade route", () => {
    const request = buildGenerationFeedbackRequest({
      tenantId: "tenant-local",
      userId: "owner-local",
      interactionId: "interaction/001",
      chatDocumentId: "chat-doc-001",
      cxGenerationId: "cx-gen-001",
      feedbackValue: "negative",
      feedbackReasons: ["not_helpful", "citation_issue", "not_helpful"],
      feedbackComment: "Citation 2 did not support the answer.",
      qualityIssueRefs: [
        {
          source_service: "nex-ae-api",
          issue_type: "user_reported",
          issue_code: "ae_web_generation_feedback_negative",
          issue_ref_id: "cx-gen-001"
        }
      ]
    });

    assert.equal(
      request.feedback_client_schema_version,
      AE_WEB_GENERATION_FEEDBACK_CLIENT_SCHEMA_VERSION
    );
    assert.equal(
      request.route,
      "/api/v1/chat/interactions/interaction%2F001/feedback"
    );
    assert.deepEqual(request.payload.feedback_reasons, [
      "not_helpful",
      "citation_issue"
    ]);
    assert.equal(request.payload.feedback_comment, "Citation 2 did not support the answer.");
    assert.equal(request.metadata.browserServiceTokenIncluded, false);
    assert.doesNotMatch(
      JSON.stringify(request),
      /raw_prompt|raw_generation_output|service_token|database_url|provider_url/
    );
  });

  it("submits mock and fetch feedback requests and returns safe summaries", async () => {
    const request = buildGenerationFeedbackRequest({
      tenantId: "tenant-local",
      userId: "owner-local",
      interactionId: "interaction-001",
      cxGenerationId: "cx-gen-001",
      feedbackValue: "positive",
      feedbackReasons: ["helpful"]
    });
    const mockClient = createMockGenerationFeedbackClient();
    const mockResult = await mockClient.submitGenerationFeedback(request);
    const calls = [];
    const fetchClient = createFetchGenerationFeedbackClient({
      baseUrl: "https://ae.local",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ payload: feedbackResponse({ feedback_value: "positive" }) });
      }
    });
    const fetchResult = await fetchClient.submitGenerationFeedback(request);

    assert.equal(mockClient.clientMode, "mock");
    assert.equal(mockResult.feedback_schema_version, AE_GENERATION_FEEDBACK_SCHEMA_VERSION);
    assert.equal(mockResult.metadata.rawCommentRendered, false);
    assert.equal(fetchResult.clientMode, "fetch");
    assert.equal(calls[0].url, "https://ae.local/api/v1/chat/interactions/interaction-001/feedback");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.equal(JSON.parse(calls[0].options.body).feedback_value, "positive");
  });

  it("maps HTTP, network, missing fetch, and invalid response failures", async () => {
    const request = buildGenerationFeedbackRequest({
      tenantId: "tenant-local",
      userId: "owner-local",
      interactionId: "interaction-001",
      feedbackValue: "neutral",
      feedbackReasons: ["other"]
    });
    const httpClient = createFetchGenerationFeedbackClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 422,
          payload: {
            error_code: "ae.generation_feedback_payload_invalid",
            detail: "Invalid feedback.",
            retryable: false
          }
        })
    });
    await assert.rejects(
      () => httpClient.submitGenerationFeedback(request),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "ae.generation_feedback_payload_invalid" &&
        error.retryable === false
    );

    const networkClient = createFetchGenerationFeedbackClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.submitGenerationFeedback(request),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    assert.throws(
      () => createFetchGenerationFeedbackClient({ fetchImpl: "bad" }),
      error => error instanceof GenerationFeedbackError && error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => buildGenerationFeedbackSubmissionResult({ feedback_schema_version: "wrong" }),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "GENERATION_FEEDBACK_RESPONSE_INVALID"
    );
  });

  it("builds UI surface state and summaries without raw text", () => {
    const surface = createGenerationFeedbackSurfaceState({
      interactionId: "interaction-001",
      chatDocumentId: "chat-doc-001",
      cxGenerationId: "cx-gen-001",
      feedbackValue: "negative",
      selectedReasons: ["not_helpful", "citation_issue"],
      status: "RECORDED",
      feedbackId: "feedback-001",
      clientMode: "fetch"
    });
    const summary = buildGenerationFeedbackSurfaceSummary(surface);

    assert.equal(
      surface.feedback_surface_schema_version,
      AE_WEB_GENERATION_FEEDBACK_SURFACE_SCHEMA_VERSION
    );
    assert.equal(summary.feedback_id_present, true);
    assert.equal(summary.selected_reason_count, 2);
    assert.equal(summary.client_mode, "fetch");
    assert.equal(summary.metadata.rawCommentRendered, false);
    assert.doesNotMatch(
      JSON.stringify(summary),
      /feedback_comment|raw_prompt|raw_generation_output|service_token|provider_url/
    );
  });

  it("rejects unsupported values, malformed refs, sensitive fields, and invalid summaries", () => {
    assert.equal(
      generationFeedbackRoute("interaction 001"),
      "/api/v1/chat/interactions/interaction%20001/feedback"
    );
    assert.throws(
      () =>
        buildGenerationFeedbackRequest({
          tenantId: "tenant-local",
          userId: "owner-local",
          interactionId: "interaction-001",
          feedbackValue: "bad",
          feedbackReasons: ["other"]
        }),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "FEEDBACK_VALUE_UNSUPPORTED"
    );
    assert.throws(
      () =>
        buildGenerationFeedbackRequest({
          tenantId: "tenant-local",
          userId: "owner-local",
          interactionId: "interaction-001",
          feedbackValue: "neutral",
          feedbackReasons: "other"
        }),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "GENERATION_FEEDBACK_REASONS_INVALID"
    );
    assert.throws(
      () =>
        buildGenerationFeedbackRequest({
          tenantId: "tenant-local",
          userId: "owner-local",
          interactionId: "interaction-001",
          feedbackValue: "neutral",
          feedbackReasons: ["other"],
          qualityIssueRefs: ["bad"]
        }),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "GENERATION_FEEDBACK_QUALITY_REF_INVALID"
    );
    assert.deepEqual(
      findSensitiveGenerationFeedbackKeys({
        nested: [{ raw_prompt: "private" }, { token: "secret" }]
      }),
      ["nested[0].raw_prompt", "nested[1].token"]
    );
    assert.throws(
      () =>
        buildGenerationFeedbackRequest({
          tenantId: "tenant-local",
          userId: "owner-local",
          interactionId: "interaction-001",
          feedbackValue: "neutral",
          feedbackReasons: ["other"],
          qualityIssueRefs: [],
          raw_prompt: "private"
        }),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "GENERATION_FEEDBACK_PAYLOAD_SENSITIVE"
    );
    assert.throws(
      () => buildGenerationFeedbackSurfaceSummary({}),
      error =>
        error instanceof GenerationFeedbackError &&
        error.status === "GENERATION_FEEDBACK_SURFACE_INVALID"
    );
  });
});
