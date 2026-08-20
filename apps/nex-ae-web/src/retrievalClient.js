import {
  AE_RETRIEVAL_CONTEXT_ROUTE,
  AE_RETRIEVAL_INTERACTION_SCHEMA_VERSION
} from "./documentScope.js";

export const AE_WEB_RETRIEVAL_CLIENT_SCHEMA_VERSION = "ae_web_retrieval_client.v1";
export const KNOWN_CX_RETRIEVAL_STATUSES = ["READY", "NO_ANSWER", "NOT_REQUESTED"];

export class RetrievalClientError extends Error {
  constructor(message, { status = "RETRIEVAL_CLIENT_ERROR", retryable = false } = {}) {
    super(message);
    this.name = "RetrievalClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function createMockRetrievalClient({ responseFactory } = {}) {
  return {
    clientMode: "mock",
    async submitRetrievalRequest(requestPayload) {
      const record = responseFactory
        ? responseFactory(requestPayload)
        : buildMockRetrievalInteractionRecord(requestPayload);
      return buildRetrievalClientResult(record, {
        clientMode: "mock",
        route: requestPayload.route || AE_RETRIEVAL_CONTEXT_ROUTE
      });
    }
  };
}

export function createFetchRetrievalClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new RetrievalClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async submitRetrievalRequest(requestPayload) {
      const route = requestPayload.route || AE_RETRIEVAL_CONTEXT_ROUTE;
      let response;
      try {
        response = await request(`${baseUrl}${route}`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify(requestPayload)
        });
      } catch {
        throw new RetrievalClientError("Retrieval request failed.", {
          status: "NETWORK_ERROR",
          retryable: true
        });
      }

      const responsePayload = await safeJson(response);
      if (!response.ok) {
        throw new RetrievalClientError(
          responsePayload.detail ||
            `Retrieval request failed with HTTP ${response.status}.`,
          {
            status: responsePayload.error_code || `HTTP_${response.status}`,
            retryable: Boolean(responsePayload.retryable)
          }
        );
      }

      return buildRetrievalClientResult(responsePayload, {
        clientMode: "fetch",
        route
      });
    }
  };
}

export function buildRetrievalClientResult(
  record,
  { clientMode = "mock", route = AE_RETRIEVAL_CONTEXT_ROUTE } = {}
) {
  if (
    !isObject(record) ||
    record.retrieval_interaction_schema_version !== AE_RETRIEVAL_INTERACTION_SCHEMA_VERSION
  ) {
    throw new RetrievalClientError("Retrieval interaction record is invalid.", {
      status: "RETRIEVAL_RECORD_INVALID"
    });
  }

  const retrieval = isObject(record.retrieval) ? record.retrieval : {};
  return {
    retrieval_client_schema_version: AE_WEB_RETRIEVAL_CLIENT_SCHEMA_VERSION,
    interaction_schema_version: record.retrieval_interaction_schema_version,
    clientMode,
    route,
    retrievalInteractionId: record.retrieval_interaction_id || null,
    chatDocumentId: record.chat_document_id || null,
    status: record.status || "UNKNOWN",
    cxRetrievalPackageId: record.cx_retrieval_package_id || null,
    cxPackageHash: record.cx_package_hash || null,
    cxStatus: record.cx_status || "UNKNOWN",
    purpose: record.purpose || "search",
    userMessageHash: record.user_message_hash || null,
    evidenceCount: retrieval.evidence_count ?? 0,
    bestScore: retrieval.best_score ?? null,
    confidenceBucket: retrieval.confidence_bucket || "UNKNOWN",
    noAnswerReason: retrieval.no_answer_reason || null,
    warnings: normalizeWarningKinds(retrieval.warnings),
    qualityWarnings: isObject(retrieval.quality_warnings)
      ? retrieval.quality_warnings
      : null,
    retryable: false,
    metadata: {
      userMessageIncluded: false,
      sourcePreviewIncluded: false,
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false
    }
  };
}

function normalizeWarningKinds(warnings) {
  if (!Array.isArray(warnings)) return [];
  const normalized = [];
  for (const warning of warnings) {
    if (typeof warning !== "string") continue;
    const kind = warning.split(":", 1)[0].trim();
    if (kind && !normalized.includes(kind)) {
      normalized.push(kind);
    }
  }
  return normalized;
}

function buildMockRetrievalInteractionRecord(requestPayload) {
  const mode = requestPayload.retrieval?.execution_mode || "DOCUMENT_SEARCH";
  const skipped = mode === "GENERAL_CHAT";
  const selectedCount = requestPayload.surface?.selected_count ?? 0;
  const evidenceCount = skipped ? 0 : Math.max(1, selectedCount);
  const cxStatus = skipped ? "NOT_REQUESTED" : "READY";

  return {
    retrieval_interaction_schema_version: AE_RETRIEVAL_INTERACTION_SCHEMA_VERSION,
    retrieval_interaction_id: skipped ? "ret-local-general-001" : "ret-local-001",
    chat_document_id: requestPayload.chat_document_id,
    status: skipped ? "SKIPPED" : "COMPLETED",
    trace_id: "trace-local",
    request_id: "request-local",
    user_message_hash: "f".repeat(64),
    cx_retrieval_package_id: skipped ? null : "cx-ret-local",
    cx_package_hash: skipped ? null : "d".repeat(64),
    cx_status: cxStatus,
    purpose: requestPayload.retrieval?.purpose || "search",
    retrieval: {
      evidence_count: evidenceCount,
      best_score: skipped ? null : 0.91,
      confidence_bucket: cxStatus,
      no_answer_reason: skipped ? "retrieval_disabled" : null,
      warnings: []
    },
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z"
  };
}

async function safeJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
