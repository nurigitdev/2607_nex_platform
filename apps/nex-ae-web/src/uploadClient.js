import {
  AE_UPLOAD_HANDOFF_SCHEMA_VERSION,
  AE_UPLOAD_ROUTE,
  buildUploadHandoffPayload,
  buildUploadSurfaceFromHandoff
} from "./uploadSurface.js";

export const AE_WEB_UPLOAD_CLIENT_SCHEMA_VERSION = "ae_web_upload_client.v1";

export class UploadClientError extends Error {
  constructor(message, { status = "UPLOAD_CLIENT_ERROR", retryable = false } = {}) {
    super(message);
    this.name = "UploadClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function createMockUploadClient({ responseFactory } = {}) {
  return {
    clientMode: "mock",
    async submitUploadDraft(draft) {
      const payload = buildUploadHandoffPayload(draft);
      const handoff = responseFactory
        ? responseFactory(payload)
        : buildMockUploadHandoff(payload);
      return buildUploadSubmissionResult(handoff, {
        clientMode: "mock",
        uploadRoute: AE_UPLOAD_ROUTE
      });
    }
  };
}

export function createFetchUploadClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new UploadClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async submitUploadDraft(draft) {
      const payload = buildUploadHandoffPayload(draft);
      let response;
      try {
        response = await request(`${baseUrl}${AE_UPLOAD_ROUTE}`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });
      } catch {
        throw new UploadClientError("Upload request failed.", {
          status: "NETWORK_ERROR",
          retryable: true
        });
      }

      const responsePayload = await safeJson(response);
      if (!response.ok) {
        throw new UploadClientError(
          responsePayload.detail || `Upload request failed with HTTP ${response.status}.`,
          {
            status: responsePayload.error_code || `HTTP_${response.status}`,
            retryable: Boolean(responsePayload.retryable)
          }
        );
      }

      return buildUploadSubmissionResult(responsePayload, {
        clientMode: "fetch",
        uploadRoute: AE_UPLOAD_ROUTE
      });
    }
  };
}

export function buildUploadSubmissionResult(
  handoff,
  { clientMode = "mock", uploadRoute = AE_UPLOAD_ROUTE } = {}
) {
  const surface = buildUploadSurfaceFromHandoff(handoff);
  const dedupeStatus = handoff.dedupe?.status || handoff.dedupe_status || "CREATED";

  return {
    upload_client_schema_version: AE_WEB_UPLOAD_CLIENT_SCHEMA_VERSION,
    handoff_schema_version: handoff.upload_handoff_schema_version,
    clientMode,
    uploadRoute,
    uploadHandoffId: handoff.upload_handoff_id || null,
    documentId: surface.documentId,
    status: surface.status || "QUEUED",
    dedupeStatus,
    retryable: false,
    source: {
      filename: surface.filename,
      contentType: surface.contentType,
      sizeBytes: surface.sizeBytes,
      sourceSha256: surface.sourceSha256
    },
    ownerScope: surface.ownerScope,
    links: safeLinks(handoff.links),
    metadata: {
      sourceContentIncluded: false,
      browserServiceTokenIncluded: false,
      cxStorageIncluded: false,
      providerUrlIncluded: false
    }
  };
}

function buildMockUploadHandoff(payload) {
  return {
    upload_handoff_schema_version: AE_UPLOAD_HANDOFF_SCHEMA_VERSION,
    upload_handoff_id: "handoff-local-upload-001",
    workspace_id: payload.workspace_id,
    tenant_id: payload.tenant_id,
    owner_user_id: payload.owner_user_id,
    ownership_ref: payload.ownership_ref,
    status: "QUEUED",
    dedupe: {
      status: "CREATED"
    },
    source: {
      filename: payload.filename,
      content_type: payload.content_type,
      size_bytes: payload.size_bytes,
      source_sha256: payload.source_sha256 || null
    },
    cx_document_ref: {
      document_id: "doc-local-upload-001"
    },
    links: {
      upload_handoff: "/api/v1/uploads/handoff-local-upload-001",
      document_detail: "/api/v1/documents/doc-local-upload-001"
    }
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

function safeLinks(links) {
  if (!isObject(links)) return {};
  return Object.fromEntries(
    Object.entries(links).filter(([, value]) => typeof value === "string")
  );
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
