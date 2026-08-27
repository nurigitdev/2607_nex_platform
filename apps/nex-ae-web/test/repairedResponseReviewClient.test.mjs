import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_REPAIRED_RESPONSE_REVIEW_COLLECTION_SCHEMA_VERSION,
  AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
  AE_WEB_REPAIRED_RESPONSE_REVIEW_CLIENT_SCHEMA_VERSION,
  AE_WEB_REPAIRED_RESPONSE_REVIEW_SURFACE_SCHEMA_VERSION,
  RepairedResponseReviewClientError,
  buildRepairedResponseReviewCollectionSurface,
  buildRepairedResponseReviewSurfaceFromProjection,
  buildRepairedResponseReviewSurfaceSummary,
  createFetchRepairedResponseReviewClient,
  createMockRepairedResponseReviewClient,
  findSensitiveRepairedResponseReviewKeys,
  repairedResponseReviewCollectionRoute,
  repairedResponseReviewDetailRoute
} from "../src/repairedResponseReviewClient.js";

function projection(overrides = {}) {
  return {
    projection_schema_version: AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
    projection_status: "READY_FOR_DECISION",
    repaired_response_handoff_id: "handoff-001",
    handoff_request_id: "request-001",
    trace_id: "trace-local",
    request_id: "request-local",
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
      title: "Repaired response ready for review",
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
      output_preview: "Repaired answer with citation support.",
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
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
    checked_at: "2026-08-27T00:01:00Z",
    ...overrides
  };
}

function collection(items = [projection()]) {
  return {
    collection_schema_version: AE_REPAIRED_RESPONSE_REVIEW_COLLECTION_SCHEMA_VERSION,
    interaction_id: "interaction-001",
    items,
    item_count: items.length,
    checked_at: "2026-08-27T00:02:00Z"
  };
}

function jsonResponse({ ok = true, status = 200, payload }) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

describe("AE Web repaired response review client", () => {
  it("builds routes and safe surfaces from AE review projections", () => {
    const surface = buildRepairedResponseReviewSurfaceFromProjection(projection(), {
      clientMode: "fetch",
      route: "/route"
    });
    const summary = buildRepairedResponseReviewSurfaceSummary(surface);

    assert.equal(
      surface.review_surface_schema_version,
      AE_WEB_REPAIRED_RESPONSE_REVIEW_SURFACE_SCHEMA_VERSION
    );
    assert.equal(
      repairedResponseReviewCollectionRoute("interaction/001"),
      "/api/v1/chat/interactions/interaction%2F001/repaired-response-handoffs/review"
    );
    assert.equal(
      repairedResponseReviewDetailRoute("interaction-001", "handoff/001"),
      "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff%2F001/review"
    );
    assert.equal(summary.repaired_response_handoff_id, "handoff-001");
    assert.equal(summary.repaired_output_preview_present, true);
    assert.equal(summary.client_mode, "fetch");
    assert.equal(summary.metadata.rawGenerationOutputRendered, false);
    assert.doesNotMatch(
      JSON.stringify(summary),
      /raw_prompt|raw_generation_output|source_text|service_token|database_url/
    );
  });

  it("lists and reads mock repaired response reviews", async () => {
    const client = createMockRepairedResponseReviewClient({
      projections: [projection()]
    });

    const listed = await client.listRepairedResponseReviews("interaction-001");
    const detail = await client.getRepairedResponseReview(
      "interaction-001",
      "handoff-001"
    );

    assert.equal(client.clientMode, "mock");
    assert.equal(
      listed.review_client_schema_version,
      AE_WEB_REPAIRED_RESPONSE_REVIEW_CLIENT_SCHEMA_VERSION
    );
    assert.equal(listed.itemCount, 1);
    assert.equal(detail.repairedResponseHandoffId, "handoff-001");
    assert.equal(detail.clientMode, "mock");
  });

  it("fetches collection and detail projections through same-origin credentials", async () => {
    const calls = [];
    const client = createFetchRepairedResponseReviewClient({
      baseUrl: "/ae-api",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        if (String(url).endsWith("/review") && !String(url).includes("handoff-001")) {
          return jsonResponse({ payload: collection() });
        }
        return jsonResponse({ payload: projection() });
      }
    });

    const listed = await client.listRepairedResponseReviews("interaction-001");
    const detail = await client.getRepairedResponseReview(
      "interaction-001",
      "handoff-001"
    );

    assert.equal(listed.clientMode, "fetch");
    assert.equal(detail.clientMode, "fetch");
    assert.equal(
      calls[0].url,
      "/ae-api/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/review"
    );
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers.Accept, "application/json");
    assert.equal(
      calls[1].url,
      "/ae-api/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001/review"
    );
  });

  it("maps fetch, HTTP, invalid payload, and missing mock failures", async () => {
    const httpClient = createFetchRepairedResponseReviewClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 404,
          payload: {
            error_code: "ae.repaired_response_handoff_not_found",
            detail: "Missing handoff."
          }
        })
    });
    await assert.rejects(
      () => httpClient.getRepairedResponseReview("interaction-001", "missing"),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "ae.repaired_response_handoff_not_found"
    );

    const networkClient = createFetchRepairedResponseReviewClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.listRepairedResponseReviews("interaction-001"),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    assert.throws(
      () => createFetchRepairedResponseReviewClient({ fetchImpl: "bad" }),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => buildRepairedResponseReviewCollectionSurface({}),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "REVIEW_COLLECTION_INVALID"
    );
    await assert.rejects(
      () =>
        createMockRepairedResponseReviewClient().getRepairedResponseReview(
          "interaction-001",
          "missing"
        ),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "NOT_FOUND"
    );
  });

  it("rejects incomplete actions and sensitive payload keys", () => {
    assert.deepEqual(
      findSensitiveRepairedResponseReviewKeys({
        nested: [{ raw_prompt: "private" }, { token: "private" }]
      }),
      ["nested[0].raw_prompt", "nested[1].token"]
    );
    assert.throws(
      () =>
        buildRepairedResponseReviewSurfaceFromProjection(
          projection({
            decision_controls: {
              ...projection().decision_controls,
              primary_actions: ["accept_repair"]
            }
          })
        ),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "REVIEW_PRIMARY_ACTIONS_INCOMPLETE"
    );
    assert.throws(
      () =>
        buildRepairedResponseReviewSurfaceFromProjection({
          ...projection(),
          raw_prompt: "private"
        }),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "REVIEW_PAYLOAD_SENSITIVE_KEY"
    );
    assert.throws(
      () => buildRepairedResponseReviewSurfaceSummary({}),
      error =>
        error instanceof RepairedResponseReviewClientError &&
        error.status === "REVIEW_SURFACE_INVALID"
    );
  });
});
