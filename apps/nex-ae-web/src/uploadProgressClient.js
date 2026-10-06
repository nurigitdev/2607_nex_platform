export const AE_WEB_UPLOAD_PROGRESS_CLIENT_SCHEMA_VERSION =
  "ae_web_upload_progress_client.v1";
export const AE_UPLOAD_PROGRESS_SCHEMA_VERSION =
  "ae_upload_ingestion_progress.v1";

const ALLOWED_STATUSES = new Set([
  "QUEUED",
  "PROCESSING",
  "WAITING_FOR_RETRY",
  "INDEX_READY",
  "FAILED",
  "CANCELLED"
]);
const TERMINAL_STATUSES = new Set(["INDEX_READY", "FAILED", "CANCELLED"]);
const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export class UploadProgressClientError extends Error {
  constructor(message, { status = "UPLOAD_PROGRESS_INVALID", retryable = false } = {}) {
    super(message);
    this.name = "UploadProgressClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function uploadProgressRoute(uploadHandoffId) {
  const normalized = requiredRef(uploadHandoffId, "UPLOAD_HANDOFF_ID_INVALID");
  return `/api/v1/uploads/${encodeURIComponent(normalized)}/progress`;
}

export function createMockUploadProgressClient({ responseFactory } = {}) {
  return {
    clientMode: "mock",
    async getProgress(uploadHandoffId) {
      const route = uploadProgressRoute(uploadHandoffId);
      const response = responseFactory
        ? await responseFactory(uploadHandoffId)
        : mockIndexReadyProgress(uploadHandoffId);
      return normalizeUploadProgress(response, { clientMode: "mock", route });
    }
  };
}

export function createFetchUploadProgressClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new UploadProgressClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  return {
    clientMode: "fetch",
    async getProgress(uploadHandoffId) {
      const route = uploadProgressRoute(uploadHandoffId);
      let response;
      try {
        response = await request(`${normalizedBaseUrl}${route}`, {
          method: "GET",
          credentials: "same-origin",
          headers: { Accept: "application/json" }
        });
      } catch {
        throw new UploadProgressClientError("Upload progress request failed.", {
          status: "NETWORK_ERROR",
          retryable: true
        });
      }
      const payload = await safeJson(response);
      if (!response.ok) {
        throw new UploadProgressClientError("Upload progress request returned an error.", {
          status: safeErrorCode(payload.error_code, response.status),
          retryable: Boolean(payload.retryable || response.status >= 500)
        });
      }
      return normalizeUploadProgress(payload, {
        clientMode: "fetch",
        route
      });
    }
  };
}

export function normalizeUploadProgress(record, { clientMode, route }) {
  if (!isObject(record) || record.progress_schema_version !== AE_UPLOAD_PROGRESS_SCHEMA_VERSION) {
    throw new UploadProgressClientError("Upload progress schema is invalid.");
  }
  if (!ALLOWED_STATUSES.has(record.status)) {
    throw new UploadProgressClientError("Upload progress status is invalid.");
  }
  assertSafeMetadata(record.metadata);
  const ingestion = isObject(record.ingestion) ? record.ingestion : {};
  const vectorIndex = isObject(record.vector_index) ? record.vector_index : {};
  const failure = isObject(record.failure) ? record.failure : {};
  return Object.freeze({
    upload_progress_client_schema_version:
      AE_WEB_UPLOAD_PROGRESS_CLIENT_SCHEMA_VERSION,
    clientMode,
    route,
    uploadHandoffId: requiredRef(record.upload_handoff_id, "UPLOAD_HANDOFF_ID_INVALID"),
    workspaceId: requiredRef(record.workspace_id, "WORKSPACE_ID_INVALID"),
    documentId: requiredRef(record.document_id, "DOCUMENT_ID_INVALID"),
    status: record.status,
    progressPercent: boundedInteger(record.progress_percent, 0, 100),
    terminal: TERMINAL_STATUSES.has(record.status),
    ingestion: Object.freeze({
      available: Boolean(ingestion.available),
      runId: optionalRef(ingestion.run_id, "INGESTION_RUN_ID_INVALID"),
      status: optionalCode(ingestion.status),
      stepTotal: boundedInteger(ingestion.step_total, 0, 10_000),
      stepCompleted: boundedInteger(ingestion.step_completed, 0, 10_000),
      attemptCount: boundedInteger(ingestion.attempt_count, 0, 1_000),
      maxAttempts: boundedInteger(ingestion.max_attempts, 0, 1_000)
    }),
    vectorIndex: Object.freeze({
      available: Boolean(vectorIndex.available),
      status: optionalCode(vectorIndex.status),
      freshnessStatus: optionalCode(vectorIndex.freshness_status),
      retrievalUsable: Boolean(vectorIndex.retrieval_usable),
      expectedVectorCount: boundedInteger(
        vectorIndex.expected_vector_count,
        0,
        100_000_000
      ),
      actualVectorCount: boundedInteger(
        vectorIndex.actual_vector_count,
        0,
        100_000_000
      )
    }),
    failure: Object.freeze({
      present: Boolean(failure.present),
      errorCode: optionalCode(failure.error_code),
      retryable: Boolean(failure.retryable)
    }),
    metadata: Object.freeze({
      ownerScoped: record.metadata.owner_scoped === true,
      privatePayloadIncluded: false,
      providerCredentialsIncluded: false
    })
  });
}

function mockIndexReadyProgress(uploadHandoffId) {
  return {
    progress_schema_version: AE_UPLOAD_PROGRESS_SCHEMA_VERSION,
    upload_handoff_id: uploadHandoffId,
    workspace_id: "workspace-local",
    document_id: "doc-local-upload-001",
    status: "INDEX_READY",
    progress_percent: 100,
    ingestion: {
      available: true,
      run_id: "run-local-upload-001",
      status: "SUCCEEDED",
      step_total: 4,
      step_completed: 4,
      attempt_count: 1,
      max_attempts: 4
    },
    vector_index: {
      available: true,
      status: "READY",
      freshness_status: "READY",
      retrieval_usable: true,
      expected_vector_count: 3,
      actual_vector_count: 3
    },
    failure: { present: false, error_code: null, retryable: false },
    metadata: {
      owner_scoped: true,
      raw_source_included: false,
      markdown_included: false,
      chunk_text_included: false,
      embedding_vector_included: false,
      provider_credentials_included: false
    }
  };
}

function assertSafeMetadata(metadata) {
  if (
    !isObject(metadata) ||
    metadata.owner_scoped !== true ||
    metadata.raw_source_included !== false ||
    metadata.markdown_included !== false ||
    metadata.chunk_text_included !== false ||
    metadata.embedding_vector_included !== false ||
    metadata.provider_credentials_included !== false
  ) {
    throw new UploadProgressClientError("Upload progress metadata is unsafe.", {
      status: "UPLOAD_PROGRESS_METADATA_UNSAFE"
    });
  }
}

async function safeJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}

function safeErrorCode(value, httpStatus) {
  const normalized = String(value || "").trim().toUpperCase();
  return /^[A-Z][A-Z0-9_.-]{0,63}$/.test(normalized)
    ? normalized.replaceAll(".", "_").replaceAll("-", "_")
    : `HTTP_${httpStatus}`;
}

function requiredRef(value, status) {
  if (!SAFE_REF.test(String(value || ""))) {
    throw new UploadProgressClientError("Upload progress reference is invalid.", { status });
  }
  return String(value);
}

function optionalRef(value, status) {
  return value == null ? null : requiredRef(value, status);
}

function optionalCode(value) {
  if (value == null) return null;
  const normalized = String(value);
  if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(normalized)) {
    throw new UploadProgressClientError("Upload progress code is invalid.");
  }
  return normalized;
}

function boundedInteger(value, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new UploadProgressClientError("Upload progress number is invalid.");
  }
  return value;
}

function normalizeBaseUrl(baseUrl) {
  if (baseUrl == null || baseUrl === "") return "";
  if (typeof baseUrl !== "string") {
    throw new UploadProgressClientError("Upload progress base URL must be text.", {
      status: "BASE_URL_INVALID"
    });
  }
  return baseUrl.replace(/\/+$/, "");
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
