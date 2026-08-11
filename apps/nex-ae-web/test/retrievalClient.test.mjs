import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_RETRIEVAL_CONTEXT_ROUTE,
  buildDocumentScope,
  buildRetrievalRequest
} from "../src/documentScope.js";
import {
  AE_WEB_RETRIEVAL_CLIENT_SCHEMA_VERSION,
  RetrievalClientError,
  buildRetrievalClientResult,
  createFetchRetrievalClient,
  createMockRetrievalClient
} from "../src/retrievalClient.js";

function documents() {
  return [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      detailRoute: "/api/v1/documents/doc-001",
      sourceKind: "postgres-read",
      summaryStatus: "READY",
      confidenceBucket: "HIGH"
    }
  ];
}

function scopedRequest({ grounded = true, topK = 5 } = {}) {
  const scope = buildDocumentScope({
    documents: documents(),
    selectedDocumentIds: ["doc-001"]
  });
  return buildRetrievalRequest({
    userMessage: "Find selected evidence",
    chatDocumentId: "chat-doc-local",
    documentScope: scope,
    grounded,
    topK
  });
}

function interactionRecord(overrides = {}) {
  return {
    retrieval_interaction_schema_version: "ae_retrieval_interaction.v1",
    retrieval_interaction_id: "ret-001",
    chat_document_id: "chat-doc-local",
    status: "COMPLETED",
    trace_id: "trace-local",
    request_id: "request-local",
    user_message_hash: "a".repeat(64),
    user_message_preview: "Find selected evidence",
    cx_retrieval_package_id: "cx-ret-001",
    cx_package_hash: "b".repeat(64),
    cx_status: "READY",
    purpose: "grounded_answer",
    retrieval: {
      evidence_count: 2,
      best_score: 0.91,
      confidence_bucket: "READY",
      no_answer_reason: null,
      warnings: ["tokenizer_fallback_used"]
    },
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
    ...overrides
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

describe("retrieval client adapters", () => {
  it("submits a grounded mock retrieval request and returns a safe result", async () => {
    const client = createMockRetrievalClient();

    const result = await client.submitRetrievalRequest(scopedRequest({ topK: 3 }));

    assert.equal(client.clientMode, "mock");
    assert.equal(result.retrieval_client_schema_version, AE_WEB_RETRIEVAL_CLIENT_SCHEMA_VERSION);
    assert.equal(result.clientMode, "mock");
    assert.equal(result.route, AE_RETRIEVAL_CONTEXT_ROUTE);
    assert.equal(result.status, "COMPLETED");
    assert.equal(result.cxStatus, "READY");
    assert.equal(result.cxRetrievalPackageId, "cx-ret-local");
    assert.equal(result.evidenceCount, 1);
    assert.equal(result.metadata.userMessageIncluded, false);
    assert.equal(result.metadata.sourcePreviewIncluded, false);
    assert.doesNotMatch(JSON.stringify(result), /Find selected evidence|source_preview_text|chunk_text|service_token|provider_url/);
  });

  it("keeps general chat requests in a skipped retrieval state", async () => {
    const client = createMockRetrievalClient();

    const result = await client.submitRetrievalRequest(scopedRequest({ grounded: false }));

    assert.equal(result.status, "SKIPPED");
    assert.equal(result.cxStatus, "NOT_REQUESTED");
    assert.equal(result.evidenceCount, 0);
    assert.equal(result.noAnswerReason, "retrieval_disabled");
  });

  it("normalizes no-answer records without raw evidence text", async () => {
    const client = createMockRetrievalClient({
      responseFactory: () =>
        interactionRecord({
          cx_status: "NO_ANSWER",
          retrieval: {
            evidence_count: 0,
            best_score: 0,
            confidence_bucket: "LOW",
            no_answer_reason: "no_terms_matched",
            warnings: []
          }
        })
    });

    const result = await client.submitRetrievalRequest(scopedRequest());

    assert.equal(result.cxStatus, "NO_ANSWER");
    assert.equal(result.evidenceCount, 0);
    assert.equal(result.noAnswerReason, "no_terms_matched");
    assert.equal(result.userMessageHash, "a".repeat(64));
    assert.doesNotMatch(JSON.stringify(result), /user_message_preview|source_text|evidence_text/);
  });

  it("posts retrieval requests through the AE facade route", async () => {
    const calls = [];
    const client = createFetchRetrievalClient({
      baseUrl: "https://ae.local",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ payload: interactionRecord() });
      }
    });

    const result = await client.submitRetrievalRequest(scopedRequest({ topK: 4 }));
    const body = JSON.parse(calls[0].options.body);

    assert.equal(calls[0].url, "https://ae.local/api/v1/retrieval/contexts");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers.Accept, "application/json");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.equal(body.retrieval.execution_mode, "DOCUMENT_SEARCH");
    assert.equal(body.retrieval.top_k, 4);
    assert.equal(body.retrieval.include_source_preview, false);
    assert.deepEqual(body.retrieval.document_scope, { document_ids: ["doc-001"] });
    assert.equal(result.clientMode, "fetch");
    assert.equal(result.retrievalInteractionId, "ret-001");
  });

  it("maps HTTP, network, unavailable fetch, and invalid record failures", async () => {
    const httpClient = createFetchRetrievalClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 503,
          payload: {
            error_code: "cx.retrieval_unavailable",
            detail: "CX retrieval unavailable.",
            retryable: true
          }
        })
    });
    await assert.rejects(
      () => httpClient.submitRetrievalRequest(scopedRequest()),
      error =>
        error instanceof RetrievalClientError &&
        error.status === "cx.retrieval_unavailable" &&
        error.retryable === true
    );

    const networkClient = createFetchRetrievalClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.submitRetrievalRequest(scopedRequest()),
      error =>
        error instanceof RetrievalClientError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    assert.throws(
      () => createFetchRetrievalClient({ fetchImpl: "bad" }),
      error => error instanceof RetrievalClientError && error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => buildRetrievalClientResult({ retrieval_interaction_schema_version: "wrong" }),
      error => error instanceof RetrievalClientError && error.status === "RETRIEVAL_RECORD_INVALID"
    );
  });
});
