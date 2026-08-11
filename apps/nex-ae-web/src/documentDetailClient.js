export const AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION =
  "ae_document_detail_projection.v1";

export class DocumentDetailClientError extends Error {
  constructor(message, { status = "DOCUMENT_DETAIL_CLIENT_ERROR", retryable = false } = {}) {
    super(message);
    this.name = "DocumentDetailClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function createMockDocumentDetailClient({ documents }) {
  const surfaces = new Map(
    documents.map(documentItem => [
      documentItem.documentId,
      buildDocumentSurface(documentItem, { clientMode: "mock" })
    ])
  );

  return {
    clientMode: "mock",
    async getDocumentDetail(documentId) {
      const surface = surfaces.get(documentId);
      if (!surface) {
        throw new DocumentDetailClientError("Document detail was not found.", {
          status: "NOT_FOUND"
        });
      }
      return surface;
    }
  };
}

export function createFetchDocumentDetailClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new DocumentDetailClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async getDocumentDetail(documentId) {
      const detailRoute = documentDetailRoute(documentId);
      let response;
      try {
        response = await request(`${baseUrl}${detailRoute}`, {
          credentials: "same-origin",
          headers: {
            Accept: "application/json"
          }
        });
      } catch {
        throw new DocumentDetailClientError("Document detail request failed.", {
          status: "NETWORK_ERROR",
          retryable: true
        });
      }

      const payload = await safeJson(response);
      if (!response.ok) {
        throw new DocumentDetailClientError(
          payload.detail || `Document detail request failed with HTTP ${response.status}.`,
          {
            status: payload.error_code || `HTTP_${response.status}`,
            retryable: Boolean(payload.retryable)
          }
        );
      }
      return buildDocumentSurfaceFromProjection(payload, {
        clientMode: "fetch",
        detailRoute
      });
    }
  };
}

export function buildDocumentSurfaceFromProjection(payload, { clientMode, detailRoute } = {}) {
  if (!isObject(payload) || !isObject(payload.document)) {
    throw new DocumentDetailClientError("Document detail projection is invalid.", {
      status: "PROJECTION_INVALID"
    });
  }

  const document = payload.document;
  const status = isObject(document.status) ? document.status : {};
  const summary = isObject(document.summary) ? document.summary : {};
  const cx = isObject(payload.cx) ? payload.cx : {};

  return buildDocumentSurface(
    {
      documentId: document.document_id,
      filename: document.filename,
      projectionSchemaVersion:
        payload.projection_schema_version || AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION,
      detailRoute: detailRoute || documentDetailRoute(document.document_id),
      ownerScope: {
        tenantId: payload.tenant_id,
        ownerUserId: payload.owner_user_id
      },
      sourceService: "nex-cx",
      sourceKind: cx.source_kind || "ae-facade",
      processingStatus:
        status.processing_status || normalizeProcessingStatus(document.processing?.status),
      extractionStatus: status.extraction_status,
      summaryStatus: normalizeSummaryStatus(status.summary_status, summary.summary_available),
      confidenceBucket: summary.summary_available ? "READY" : "UNKNOWN",
      bestScore: null,
      clientMode
    },
    { clientMode }
  );
}

export function buildDocumentSurface(documentItem, { clientMode } = {}) {
  if (!documentItem || !documentItem.documentId) {
    throw new DocumentDetailClientError("Document surface item is invalid.", {
      status: "DOCUMENT_SURFACE_INVALID"
    });
  }

  return {
    documentId: String(documentItem.documentId),
    filename: documentItem.filename || "Untitled document",
    detailRoute: documentItem.detailRoute || documentDetailRoute(documentItem.documentId),
    projectionSchemaVersion:
      documentItem.projectionSchemaVersion || AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION,
    tenantId: documentItem.ownerScope?.tenantId || "UNKNOWN",
    ownerUserId: documentItem.ownerScope?.ownerUserId || "UNKNOWN",
    sourceService: documentItem.sourceService || "nex-cx",
    sourceKind: documentItem.sourceKind || "ae-facade",
    processingStatus: documentItem.processingStatus || "UNKNOWN",
    extractionStatus: documentItem.extractionStatus || "UNKNOWN",
    summaryStatus: documentItem.summaryStatus || "UNKNOWN",
    confidenceBucket: documentItem.confidenceBucket || "UNKNOWN",
    bestScore: documentItem.bestScore ?? null,
    clientMode: clientMode || documentItem.clientMode || "mock"
  };
}

export function documentDetailRoute(documentId) {
  return `/api/v1/documents/${encodeURIComponent(documentId)}`;
}

async function safeJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}

function normalizeProcessingStatus(status) {
  return status || "UNKNOWN";
}

function normalizeSummaryStatus(summaryStatus, summaryAvailable) {
  if (summaryStatus) return summaryStatus;
  return summaryAvailable ? "READY" : "UNKNOWN";
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
