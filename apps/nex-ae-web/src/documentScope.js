export const AE_WEB_DOCUMENT_SCOPE_SCHEMA_VERSION = "ae_web_document_scope.v1";
export const AE_RETRIEVAL_INTERACTION_SCHEMA_VERSION = "ae_retrieval_interaction.v1";
export const AE_RETRIEVAL_CONTEXT_ROUTE = "/api/v1/retrieval/contexts";

export class DocumentScopeError extends Error {
  constructor(message, { status = "DOCUMENT_SCOPE_INVALID" } = {}) {
    super(message);
    this.name = "DocumentScopeError";
    this.status = status;
  }
}

export function buildDocumentScope({ documents, selectedDocumentIds }) {
  if (!Array.isArray(documents)) {
    throw new DocumentScopeError("documents must be an array.", {
      status: "DOCUMENTS_INVALID"
    });
  }
  const knownDocuments = new Map(
    documents.map(documentItem => [documentItem.documentId, documentItem])
  );
  const uniqueIds = uniqueNonEmptyStrings(selectedDocumentIds, "selectedDocumentIds");
  const selectedItems = uniqueIds.map(documentId => {
    const documentItem = knownDocuments.get(documentId);
    if (!documentItem) {
      throw new DocumentScopeError("selectedDocumentIds must reference known documents.", {
        status: "DOCUMENT_SCOPE_UNKNOWN_DOCUMENT"
      });
    }
    return {
      documentId,
      filename: documentItem.filename,
      detailRoute: documentItem.detailRoute || `/api/v1/documents/${encodeURIComponent(documentId)}`,
      sourceKind: documentItem.sourceKind || "ae-facade",
      summaryStatus: documentItem.summaryStatus || "UNKNOWN",
      confidenceBucket: documentItem.confidenceBucket || "UNKNOWN"
    };
  });

  return {
    document_scope_schema_version: AE_WEB_DOCUMENT_SCOPE_SCHEMA_VERSION,
    route: AE_RETRIEVAL_CONTEXT_ROUTE,
    document_scope: {
      document_ids: uniqueIds
    },
    selectedItems,
    selectedCount: selectedItems.length,
    metadata: {
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      sourcePreviewIncluded: false
    }
  };
}

export function buildRetrievalRequest({
  userMessage,
  chatDocumentId,
  documentScope,
  grounded,
  topK = 5
}) {
  const normalizedUserMessage = requiredText(userMessage, "userMessage");
  const normalizedChatDocumentId = requiredText(chatDocumentId, "chatDocumentId");
  const includeDocumentScope = Boolean(grounded);
  const request = {
    route: AE_RETRIEVAL_CONTEXT_ROUTE,
    retrieval_interaction_schema_version: AE_RETRIEVAL_INTERACTION_SCHEMA_VERSION,
    user_message: normalizedUserMessage,
    chat_document_id: normalizedChatDocumentId,
    retrieval: {
      execution_mode: includeDocumentScope ? "DOCUMENT_SEARCH" : "GENERAL_CHAT",
      query_text: normalizedUserMessage,
      document_scope: includeDocumentScope ? documentScope.document_scope : null,
      retrieval_profile: {
        search_strategy: "hybrid"
      },
      top_k: topK,
      include_neighbors: false,
      include_source_preview: false,
      purpose: includeDocumentScope ? "grounded_answer" : "search"
    },
    surface: {
      document_scope_schema_version: documentScope.document_scope_schema_version,
      selected_count: includeDocumentScope ? documentScope.selectedCount : 0,
      selected_documents: includeDocumentScope ? documentScope.selectedItems : []
    }
  };
  if (includeDocumentScope && documentScope.selectedCount < 1) {
    throw new DocumentScopeError("grounded retrieval requires at least one document.", {
      status: "DOCUMENT_SCOPE_EMPTY"
    });
  }
  return request;
}

export function documentScopeLabel(documentScope) {
  if (!documentScope || documentScope.selectedCount < 1) return "문서 범위 없음";
  return documentScope.selectedItems
    .map(item => item.filename || item.documentId)
    .join(", ");
}

function uniqueNonEmptyStrings(values, fieldName) {
  if (!Array.isArray(values)) {
    throw new DocumentScopeError(`${fieldName} must be an array.`, {
      status: "DOCUMENT_SCOPE_IDS_INVALID"
    });
  }
  const unique = [];
  for (const value of values) {
    const normalized = requiredText(value, fieldName);
    if (!unique.includes(normalized)) unique.push(normalized);
  }
  return unique;
}

function requiredText(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new DocumentScopeError(`${fieldName} must be a non-empty string.`, {
      status: "TEXT_INVALID"
    });
  }
  return value.trim();
}
