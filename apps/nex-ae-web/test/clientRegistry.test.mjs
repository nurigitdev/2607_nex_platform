import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION,
  ClientRegistryError,
  buildClientRegistrySummary,
  createAeWebClients
} from "../src/clientRegistry.js";

function documents() {
  return [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      ownerScope: {
        tenantId: "tenant-local",
        ownerUserId: "owner-local"
      },
      processingStatus: "COMPLETED",
      summaryStatus: "READY"
    }
  ];
}

describe("AE Web client registry", () => {
  it("builds a safe mock client registry for all browser adapters", () => {
    const registry = createAeWebClients({
      mode: "mock",
      documents: documents()
    });
    const summary = buildClientRegistrySummary(registry);

    assert.equal(
      registry.client_registry_schema_version,
      AE_WEB_CLIENT_REGISTRY_SCHEMA_VERSION
    );
    assert.equal(registry.clientMode, "mock");
    assert.equal(registry.baseUrl, "");
    assert.equal(registry.documentDetailClient.clientMode, "mock");
    assert.equal(registry.uploadClient.clientMode, "mock");
    assert.equal(registry.retrievalClient.clientMode, "mock");
    assert.equal(registry.generationFeedbackClient.clientMode, "mock");
    assert.equal(registry.repairedResponseReviewClient.clientMode, "mock");
    assert.equal(registry.repairedResponseDecisionClient.clientMode, "mock");
    assert.equal(summary.clients.document_detail, "mock");
    assert.equal(summary.clients.generation_feedback, "mock");
    assert.equal(summary.clients.repaired_response_review, "mock");
    assert.equal(summary.clients.repaired_response_decision, "mock");
    assert.deepEqual(summary.metadata, {
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false,
      rawSourceIncluded: false
    });
    assert.doesNotMatch(JSON.stringify(summary), /service_token|api_key|database_url|provider_url/);
  });

  it("builds fetch clients with normalized base URL and shared fetch implementation", async () => {
    const calls = [];
    const registry = createAeWebClients({
      mode: "fetch",
      baseUrl: "https://ae.local/",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        if (String(url).includes("/feedback")) {
          return {
            ok: true,
            status: 202,
            async json() {
              return {
                feedback_schema_version: "ae_generation_feedback.v1",
                feedback_id: "feedback-001",
                status: "RECORDED",
                tenant_id: "tenant-local",
                user_id: "owner-local",
                interaction_id: "interaction-001",
                feedback_value: "positive",
                feedback_reasons: ["helpful"],
                quality_issue_refs: [],
                created_at: "2026-08-25T00:00:00Z"
              };
            }
          };
        }
        if (String(url).includes("/repaired-response-handoffs/review")) {
          return {
            ok: true,
            status: 200,
            async json() {
              return {
                collection_schema_version:
                  "ae_repaired_response_review_collection.v1",
                interaction_id: "interaction-001",
                items: [],
                item_count: 0,
                checked_at: "2026-08-27T00:00:00Z"
              };
            }
          };
        }
        if (String(url).includes("/repaired-response-handoffs/handoff-001/decisions")) {
          return {
            ok: true,
            status: 202,
            async json() {
              return {
                decision_schema_version: "ae_repaired_response_decision.v1",
                repaired_response_decision_id: "decision-001",
                decision_request_id: "decision-request-001",
                decision_status: "RECORDED",
                decision_action: "accept_repair",
                repaired_response_handoff_id: "handoff-001",
                tenant_id: "tenant-local",
                workspace_id: "workspace-local",
                owner_user_id: "owner-local",
                chat_document_id: "chat-doc-local",
                interaction_id: "interaction-001",
                selected_cx_generation_id: "cx-gen-repair-001",
                rejected_cx_generation_id: "cx-gen-parent-001",
                decision_reason_codes: ["prefer_repaired"],
                metadata: {
                  raw_prompt_stored: false,
                  raw_generation_output_stored: false,
                  raw_source_text_stored: false,
                  raw_evidence_stored: false
                },
                created_at: "2026-08-27T00:03:00Z"
              };
            }
          };
        }
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              projection_schema_version: "ae_document_detail_projection.v1",
              tenant_id: "tenant-local",
              owner_user_id: "owner-local",
              document: {
                document_id: "doc-001",
                filename: "29_mvp_srs.md",
                status: {},
                summary: { summary_available: false }
              },
              cx: { source_kind: "ae-facade" }
            };
          }
        };
      }
    });

    await registry.documentDetailClient.getDocumentDetail("doc-001");
    await registry.generationFeedbackClient.submitGenerationFeedback({
      route: "/api/v1/chat/interactions/interaction-001/feedback",
      payload: {
        tenant_id: "tenant-local",
        user_id: "owner-local",
        interaction_id: "interaction-001",
        feedback_value: "positive",
        feedback_reasons: ["helpful"],
        quality_issue_refs: [],
        submitted_via: "ae-web"
      }
    });
    await registry.repairedResponseReviewClient.listRepairedResponseReviews(
      "interaction-001"
    );
    await registry.repairedResponseDecisionClient.submitRepairedResponseDecision({
      route:
        "/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001/decisions",
      payload: {
        tenant_id: "tenant-local",
        workspace_id: "workspace-local",
        owner_user_id: "owner-local",
        chat_document_id: "chat-doc-local",
        interaction_id: "interaction-001",
        repaired_response_handoff_id: "handoff-001",
        decision_action: "accept_repair",
        decision_request_id: "decision-request-001",
        decision_reason_codes: ["prefer_repaired"],
        submitted_via: "chat_review",
        actor_claims_ref: {
          actor_type: "user",
          actor_id: "owner-local",
          tenant_id: "tenant-local"
        }
      }
    });
    const summary = buildClientRegistrySummary(registry);

    assert.equal(registry.clientMode, "fetch");
    assert.equal(registry.baseUrl, "https://ae.local");
    assert.equal(calls[0].url, "https://ae.local/api/v1/documents/doc-001");
    assert.equal(
      calls[1].url,
      "https://ae.local/api/v1/chat/interactions/interaction-001/feedback"
    );
    assert.equal(
      calls[2].url,
      "https://ae.local/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/review"
    );
    assert.equal(
      calls[3].url,
      "https://ae.local/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-001/decisions"
    );
    assert.equal(calls[3].options.method, "POST");
    assert.equal(summary.base_url, "https://ae.local");
    assert.equal(summary.clients.upload, "fetch");
    assert.equal(summary.clients.retrieval, "fetch");
    assert.equal(summary.clients.generation_feedback, "fetch");
    assert.equal(summary.clients.repaired_response_review, "fetch");
    assert.equal(summary.clients.repaired_response_decision, "fetch");
  });

  it("rejects unsupported client modes and invalid base URLs", () => {
    assert.throws(
      () => createAeWebClients({ mode: "live" }),
      error =>
        error instanceof ClientRegistryError &&
        error.status === "CLIENT_MODE_UNSUPPORTED"
    );
    assert.throws(
      () => createAeWebClients({ mode: "fetch", baseUrl: 123, fetchImpl: async () => ({}) }),
      error =>
        error instanceof ClientRegistryError &&
        error.status === "BASE_URL_INVALID"
    );
    assert.throws(
      () => buildClientRegistrySummary({}),
      error =>
        error instanceof ClientRegistryError &&
        error.status === "CLIENT_REGISTRY_SUMMARY_INVALID"
    );
  });
});
