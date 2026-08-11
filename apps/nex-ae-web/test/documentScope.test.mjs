import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_RETRIEVAL_CONTEXT_ROUTE,
  AE_WEB_DOCUMENT_SCOPE_SCHEMA_VERSION,
  DocumentScopeError,
  buildDocumentScope,
  buildRetrievalRequest,
  documentScopeLabel
} from "../src/documentScope.js";

function documents() {
  return [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      detailRoute: "/api/v1/documents/doc-001",
      sourceKind: "postgres-read",
      summaryStatus: "READY",
      confidenceBucket: "HIGH"
    },
    {
      documentId: "doc-002",
      filename: "31_traceability.md",
      detailRoute: "/api/v1/documents/doc-002",
      sourceKind: "postgres-read",
      summaryStatus: "READY",
      confidenceBucket: "HIGH"
    }
  ];
}

describe("document scope propagation", () => {
  it("builds a deduplicated selected document scope", () => {
    const scope = buildDocumentScope({
      documents: documents(),
      selectedDocumentIds: ["doc-001", "doc-001", "doc-002"]
    });

    assert.equal(scope.document_scope_schema_version, AE_WEB_DOCUMENT_SCOPE_SCHEMA_VERSION);
    assert.equal(scope.route, AE_RETRIEVAL_CONTEXT_ROUTE);
    assert.deepEqual(scope.document_scope.document_ids, ["doc-001", "doc-002"]);
    assert.equal(scope.selectedCount, 2);
    assert.equal(documentScopeLabel(scope), "29_mvp_srs.md, 31_traceability.md");
    assert.deepEqual(scope.metadata, {
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      sourcePreviewIncluded: false
    });
  });

  it("builds a grounded AE retrieval request with document scope", () => {
    const scope = buildDocumentScope({
      documents: documents(),
      selectedDocumentIds: ["doc-001"]
    });

    const request = buildRetrievalRequest({
      userMessage: "  summarize selected document  ",
      chatDocumentId: "chat-doc-local",
      documentScope: scope,
      grounded: true,
      topK: 3
    });

    assert.equal(request.route, AE_RETRIEVAL_CONTEXT_ROUTE);
    assert.equal(request.chat_document_id, "chat-doc-local");
    assert.equal(request.user_message, "summarize selected document");
    assert.equal(request.retrieval.execution_mode, "DOCUMENT_SEARCH");
    assert.deepEqual(request.retrieval.document_scope, { document_ids: ["doc-001"] });
    assert.equal(request.retrieval.include_source_preview, false);
    assert.equal(request.retrieval.purpose, "grounded_answer");
    assert.equal(request.retrieval.top_k, 3);
    assert.equal(request.surface.selected_count, 1);
  });

  it("builds an ungrounded request without document ids", () => {
    const scope = buildDocumentScope({
      documents: documents(),
      selectedDocumentIds: ["doc-001"]
    });

    const request = buildRetrievalRequest({
      userMessage: "general answer",
      chatDocumentId: "chat-doc-local",
      documentScope: scope,
      grounded: false
    });

    assert.equal(request.retrieval.execution_mode, "GENERAL_CHAT");
    assert.equal(request.retrieval.document_scope, null);
    assert.equal(request.surface.selected_count, 0);
    assert.deepEqual(request.surface.selected_documents, []);
  });

  it("rejects invalid scope and grounded empty scope inputs", () => {
    assert.throws(
      () =>
        buildDocumentScope({
          documents: documents(),
          selectedDocumentIds: ["missing"]
        }),
      error =>
        error instanceof DocumentScopeError &&
        error.status === "DOCUMENT_SCOPE_UNKNOWN_DOCUMENT"
    );
    assert.throws(
      () =>
        buildDocumentScope({
          documents: "bad",
          selectedDocumentIds: ["doc-001"]
        }),
      error => error instanceof DocumentScopeError && error.status === "DOCUMENTS_INVALID"
    );
    assert.throws(
      () =>
        buildRetrievalRequest({
          userMessage: "grounded",
          chatDocumentId: "chat-doc-local",
          documentScope: buildDocumentScope({
            documents: documents(),
            selectedDocumentIds: []
          }),
          grounded: true
        }),
      error => error instanceof DocumentScopeError && error.status === "DOCUMENT_SCOPE_EMPTY"
    );
  });
});
