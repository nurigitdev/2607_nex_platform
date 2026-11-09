export interface DocumentLibraryItem {
  readonly documentId: string;
  readonly filename: string;
  readonly contentType: string;
  readonly sizeBytes: number;
  readonly extractionStatus: string;
  readonly summaryStatus: string;
  readonly summaryAvailable: boolean;
  readonly summaryPreview: string | null;
  readonly dedupeStatus: string;
}

export interface DocumentLibraryClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly listWorkspaceDocuments: (workspaceId: string) => Promise<readonly DocumentLibraryItem[]>;
}

export class DocumentLibraryClientError extends Error {
  readonly status: string;
  readonly statusCode: number | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    status = "DOCUMENT_LIBRARY_REQUEST_FAILED",
    statusCode: number | null = null,
    retryable = false,
  ) {
    super(message);
    this.name = "DocumentLibraryClientError";
    this.status = status;
    this.statusCode = statusCode;
    this.retryable = retryable;
  }
}

export function createDocumentLibraryClient({
  mode,
  baseUrl = "",
  fetchImpl,
  documents = [],
}: {
  readonly mode: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
  readonly documents?: readonly DocumentLibraryItem[];
}): DocumentLibraryClientPort {
  if (mode === "mock") {
    return Object.freeze({
      clientMode: "mock" as const,
      async listWorkspaceDocuments(workspaceId: string) {
        requiredRef(workspaceId, "workspace_id");
        return documents.map(item => Object.freeze({ ...item }));
      },
    });
  }
  if (typeof fetchImpl !== "function") {
    throw new DocumentLibraryClientError("Fetch is unavailable.", "FETCH_UNAVAILABLE");
  }
  return Object.freeze({
    clientMode: "fetch" as const,
    async listWorkspaceDocuments(workspaceId: string) {
      const normalizedWorkspaceId = requiredRef(workspaceId, "workspace_id");
      const response = await fetchImpl(
        `${baseUrl}/api/v1/workspaces/${encodeURIComponent(normalizedWorkspaceId)}/documents`,
        { credentials: "include", headers: { Accept: "application/json" } },
      );
      const payload = await readJson(response);
      if (!response.ok) {
        throw new DocumentLibraryClientError(
          "문서 목록을 불러오지 못했습니다.",
          safeCode(payload.error_code),
          response.status,
          Boolean(payload.retryable || response.status >= 500),
        );
      }
      if (payload.workspace_id !== normalizedWorkspaceId || !Array.isArray(payload.documents)) {
        throw new DocumentLibraryClientError(
          "문서 목록 응답이 올바르지 않습니다.",
          "DOCUMENT_LIBRARY_RESPONSE_INVALID",
        );
      }
      return payload.documents.map(projectDocumentLibraryItem);
    },
  });
}

export function projectDocumentLibraryItem(value: unknown): DocumentLibraryItem {
  if (!isObject(value) || value.document_library_schema_version !== "ae_document_library_item.v1") {
    throw new DocumentLibraryClientError(
      "문서 항목이 올바르지 않습니다.",
      "DOCUMENT_LIBRARY_ITEM_INVALID",
    );
  }
  const status = isObject(value.status) ? value.status : {};
  const summary = isObject(value.summary) ? value.summary : {};
  return Object.freeze({
    documentId: requiredRef(value.document_id, "document_id"),
    filename: requiredText(value.filename, "filename"),
    contentType: optionalText(value.content_type, "application/octet-stream"),
    sizeBytes: nonNegativeInteger(value.size_bytes),
    extractionStatus: safeCode(status.extraction_status, "UNKNOWN"),
    summaryStatus: safeCode(status.summary_status, "UNKNOWN"),
    summaryAvailable: summary.summary_available === true,
    summaryPreview: summary.summary_available === true
      ? optionalBoundedText(summary.summary_preview, 500)
      : null,
    dedupeStatus: safeCode(status.dedupe_status, "UNKNOWN"),
  });
}

function requiredRef(value: unknown, field: string) {
  const normalized = requiredText(value, field);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(normalized)) {
    throw new DocumentLibraryClientError(`${field} 값이 올바르지 않습니다.`, "DOCUMENT_REF_INVALID");
  }
  return normalized;
}

function requiredText(value: unknown, field: string) {
  if (typeof value !== "string" || !value.trim()) {
    throw new DocumentLibraryClientError(`${field} 값이 필요합니다.`, "DOCUMENT_LIBRARY_ITEM_INVALID");
  }
  return value.trim();
}

function optionalText(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function optionalBoundedText(value: unknown, maximum: number) {
  return typeof value === "string" && value.trim() ? value.trim().slice(0, maximum) : null;
}

function nonNegativeInteger(value: unknown) {
  if (!Number.isInteger(value) || Number(value) < 0) {
    throw new DocumentLibraryClientError("문서 크기가 올바르지 않습니다.", "DOCUMENT_SIZE_INVALID");
  }
  return Number(value);
}

function safeCode(value: unknown, fallback = "DOCUMENT_LIBRARY_REQUEST_FAILED") {
  const candidate = typeof value === "string" ? value.trim().toUpperCase() : "";
  return /^[A-Z][A-Z0-9_.-]{0,95}$/.test(candidate) ? candidate : fallback;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await response.json();
    return isObject(value) ? value : {};
  } catch {
    return {};
  }
}
