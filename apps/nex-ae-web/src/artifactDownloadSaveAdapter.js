export const AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION =
  "ae_web_artifact_download_save.v1";

const SUPPORTED_PAYLOAD_KINDS = ["text", "base64"];
const TEXT_ENCODING = "utf-8";
const BASE64_ENCODING = "base64";
const DEFAULT_FILE_NAME = "artifact-download";
const MAX_FILE_NAME_LENGTH = 160;
const CONTROL_CHARS = /[\u0000-\u001f\u007f]+/g;
const PATH_SEGMENT_SEPARATOR = /[\\/]+/;
const SAFE_EXTENSION_BY_CONTENT_TYPE = {
  "application/pdf": ".pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    ".docx",
  "text/html": ".html",
  "text/markdown": ".md",
  "text/plain": ".txt"
};

const SENSITIVE_KEY_NAMES = new Set([
  "content",
  "content_base64",
  "contentbase64",
  "raw",
  "raw_content",
  "raw_download",
  "raw_payload",
  "storage_path",
  "storage_ref",
  "service_token",
  "access_token",
  "authorization",
  "database_url",
  "provider_url",
  "password"
]);

const SENSITIVE_VALUE_PATTERNS = [
  /postgresql(?:\+\w+)?:\/\/[^"'\s]+/i,
  /\/data\/nex-platform/i,
  /ed6@c496em/i,
  /nuri1004/i,
  /JVBERi0xLjQKJQ==/
];

export class ArtifactDownloadSaveError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_DOWNLOAD_SAVE_ERROR", retryable = false } = {}
  ) {
    super(message);
    this.name = "ArtifactDownloadSaveError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function buildArtifactDownloadSavePlan(downloadSurface) {
  const normalized = normalizeDownloadSurface(downloadSurface);
  const plan = {
    artifact_download_save_schema_version:
      AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION,
    status: "READY",
    artifactId: normalized.artifactId,
    artifactVersionId: normalized.artifactVersionId,
    artifactFileId: normalized.artifactFileId,
    fileName: normalized.fileName,
    contentType: normalized.contentType,
    payloadKind: normalized.payloadKind,
    contentEncoding: normalized.contentEncoding,
    contentLength: normalized.contentLength,
    encodedContentLength: normalized.encodedContentLength,
    browserSaveRequired: true,
    metadata: safeDownloadSaveMetadata({
      blobCreated: false,
      objectUrlCreated: false,
      anchorClicked: false,
      objectUrlRevoked: false,
      browserSaveAvailable: false
    })
  };
  assertArtifactDownloadSaveResultSafe(plan);
  return plan;
}

export function createArtifactDownloadBlob(
  downloadSurface,
  { BlobCtor = globalThis.Blob } = {}
) {
  const normalized = normalizeDownloadSurface(downloadSurface);
  if (typeof BlobCtor !== "function") {
    throw new ArtifactDownloadSaveError("Blob is not available.", {
      status: "BLOB_UNAVAILABLE",
      retryable: true
    });
  }
  const body =
    normalized.payloadKind === "base64"
      ? decodeBase64ToUint8Array(downloadSurface.contentBase64)
      : normalized.content;
  const blob = new BlobCtor([body], { type: normalized.contentType });
  return {
    blob,
    plan: buildArtifactDownloadSavePlan(downloadSurface)
  };
}

export function saveArtifactDownload(
  downloadSurface,
  {
    BlobCtor = globalThis.Blob,
    documentRef = globalThis.document,
    urlRef = globalThis.URL,
    appendTarget = documentRef?.body ?? null
  } = {}
) {
  const { blob, plan } = createArtifactDownloadBlob(downloadSurface, { BlobCtor });
  const browserSaveAvailable =
    isObject(documentRef) &&
    typeof documentRef.createElement === "function" &&
    isObject(urlRef) &&
    typeof urlRef.createObjectURL === "function" &&
    typeof urlRef.revokeObjectURL === "function";

  if (!browserSaveAvailable) {
    return buildArtifactDownloadSaveResult(plan, {
      status: "PREPARED",
      blobCreated: true,
      browserSaveAvailable: false
    });
  }

  let objectUrl = null;
  let anchor = null;
  let anchorAppended = false;
  let anchorClicked = false;
  let objectUrlRevoked = false;
  try {
    objectUrl = urlRef.createObjectURL(blob);
    anchor = documentRef.createElement("a");
    anchor.href = objectUrl;
    anchor.download = plan.fileName;
    anchor.rel = "noopener";
    if (anchor.style) {
      anchor.style.display = "none";
    }
    if (appendTarget && typeof appendTarget.appendChild === "function") {
      appendTarget.appendChild(anchor);
      anchorAppended = true;
    }
    if (typeof anchor.click === "function") {
      anchor.click();
      anchorClicked = true;
    }
  } finally {
    if (
      anchorAppended &&
      anchor &&
      appendTarget &&
      typeof appendTarget.removeChild === "function"
    ) {
      appendTarget.removeChild(anchor);
    }
    if (objectUrl) {
      urlRef.revokeObjectURL(objectUrl);
      objectUrlRevoked = true;
    }
  }

  return buildArtifactDownloadSaveResult(plan, {
    status: anchorClicked ? "SAVED" : "PREPARED",
    blobCreated: true,
    objectUrlCreated: Boolean(objectUrl),
    anchorClicked,
    objectUrlRevoked,
    browserSaveAvailable: true
  });
}

export function buildArtifactDownloadSaveSummary(result) {
  if (
    !isObject(result) ||
    result.artifact_download_save_schema_version !==
      AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION
  ) {
    throw new ArtifactDownloadSaveError("Download save result is invalid.", {
      status: "DOWNLOAD_SAVE_RESULT_INVALID"
    });
  }
  const summary = {
    artifact_download_save_schema_version:
      result.artifact_download_save_schema_version,
    status: result.status,
    artifact_id: normalizeOptionalText(result.artifactId),
    artifact_version_id: normalizeOptionalText(result.artifactVersionId),
    artifact_file_id: normalizeOptionalText(result.artifactFileId),
    file_name: sanitizeDownloadFileName(result.fileName),
    content_type: normalizeContentType(result.contentType),
    payload_kind: normalizePayloadKind(result.payloadKind),
    content_encoding: normalizeContentEncoding(
      result.contentEncoding,
      result.payloadKind
    ),
    content_length: normalizeContentLength(result.contentLength),
    encoded_content_length: normalizeContentLength(result.encodedContentLength),
    browser_save_available: Boolean(result.metadata?.browserSaveAvailable),
    blob_created: Boolean(result.metadata?.blobCreated),
    object_url_created: Boolean(result.metadata?.objectUrlCreated),
    anchor_clicked: Boolean(result.metadata?.anchorClicked),
    object_url_revoked: Boolean(result.metadata?.objectUrlRevoked),
    metadata: safeDownloadSaveMetadata(result.metadata)
  };
  assertArtifactDownloadSaveResultSafe(summary);
  return summary;
}

export function assertArtifactDownloadSaveResultSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactDownloadSaveKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactDownloadSaveError(
      "Download save result contains sensitive keys.",
      { status: "DOWNLOAD_SAVE_RESULT_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactDownloadSaveError(
      "Download save result contains sensitive values.",
      { status: "DOWNLOAD_SAVE_RESULT_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactDownloadSaveKeys(payload) {
  const found = [];

  function visit(value, path) {
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    if (!isObject(value)) return;
    for (const [key, child] of Object.entries(value)) {
      const keyPath = path ? `${path}.${key}` : key;
      const normalized = key.replaceAll("-", "_").toLowerCase();
      if (SENSITIVE_KEY_NAMES.has(normalized)) {
        found.push(keyPath);
      }
      visit(child, keyPath);
    }
  }

  visit(payload, "");
  return found.sort();
}

export function sanitizeDownloadFileName(
  value,
  { fallback = DEFAULT_FILE_NAME, contentType = null } = {}
) {
  const rawName = normalizeOptionalText(value) || fallback;
  const leaf = rawName.split(PATH_SEGMENT_SEPARATOR).filter(Boolean).at(-1) || fallback;
  let sanitized = leaf
    .replace(CONTROL_CHARS, "")
    .replaceAll(":", "-")
    .replace(/\s+/g, " ")
    .trim();
  if (!sanitized || sanitized === "." || sanitized === "..") {
    sanitized = fallback;
  }
  if (sanitized.length > MAX_FILE_NAME_LENGTH) {
    sanitized = sanitized.slice(0, MAX_FILE_NAME_LENGTH).trim() || fallback;
  }
  if (!sanitized.includes(".") && contentType) {
    sanitized = `${sanitized}${SAFE_EXTENSION_BY_CONTENT_TYPE[contentType] || ""}`;
  }
  return sanitized;
}

function normalizeDownloadSurface(downloadSurface) {
  if (!isObject(downloadSurface) || !isObject(downloadSurface.artifactFile)) {
    throw new ArtifactDownloadSaveError("Download surface is invalid.", {
      status: "DOWNLOAD_SURFACE_INVALID"
    });
  }
  const artifactFile = downloadSurface.artifactFile;
  const payloadKind = normalizePayloadKind(downloadSurface.downloadPayloadKind);
  const contentEncoding = normalizeContentEncoding(
    downloadSurface.contentEncoding,
    payloadKind
  );
  if (payloadKind === "text" && typeof downloadSurface.content !== "string") {
    throw new ArtifactDownloadSaveError("Text download content is missing.", {
      status: "DOWNLOAD_TEXT_CONTENT_MISSING"
    });
  }
  if (payloadKind === "base64") {
    validateBase64Content(downloadSurface.contentBase64);
  }
  const contentType = normalizeContentType(
    downloadSurface.contentType || artifactFile.mimeType
  );
  return {
    artifactId: normalizeOptionalText(artifactFile.artifactId) || null,
    artifactVersionId: normalizeOptionalText(artifactFile.artifactVersionId) || null,
    artifactFileId: requiredText(artifactFile.artifactFileId, "artifact_file_id"),
    fileName: sanitizeDownloadFileName(
      downloadSurface.downloadFileName || artifactFile.fileName,
      { contentType }
    ),
    contentType,
    payloadKind,
    contentEncoding,
    content:
      payloadKind === "text" ? String(downloadSurface.content) : null,
    contentLength:
      payloadKind === "base64"
        ? decodeBase64ToUint8Array(downloadSurface.contentBase64).byteLength
        : normalizeContentLength(
            downloadSurface.contentLength ?? String(downloadSurface.content).length
          ),
    encodedContentLength:
      payloadKind === "base64"
        ? String(downloadSurface.contentBase64).trim().length
        : normalizeContentLength(downloadSurface.encodedContentLength),
  };
}

function buildArtifactDownloadSaveResult(plan, overrides = {}) {
  const result = {
    ...plan,
    status: normalizeStatus(overrides.status || plan.status),
    metadata: safeDownloadSaveMetadata({
      ...plan.metadata,
      ...overrides
    })
  };
  assertArtifactDownloadSaveResultSafe(result);
  return result;
}

function safeDownloadSaveMetadata(overrides = {}) {
  return {
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    rawDownloadContentIncluded: false,
    rawBase64PayloadIncluded: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    storageLocationIncluded: false,
    blobCreated: Boolean(overrides.blobCreated),
    objectUrlCreated: Boolean(overrides.objectUrlCreated),
    anchorClicked: Boolean(overrides.anchorClicked),
    objectUrlRevoked: Boolean(overrides.objectUrlRevoked),
    browserSaveAvailable: Boolean(overrides.browserSaveAvailable)
  };
}

function normalizePayloadKind(value) {
  const normalized = normalizeOptionalText(value) || "text";
  if (!SUPPORTED_PAYLOAD_KINDS.includes(normalized)) {
    throw new ArtifactDownloadSaveError("Download payload kind is unsupported.", {
      status: "DOWNLOAD_PAYLOAD_KIND_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeContentEncoding(value, payloadKind) {
  const fallback = payloadKind === "base64" ? BASE64_ENCODING : TEXT_ENCODING;
  const normalized = normalizeOptionalText(value) || fallback;
  if (payloadKind === "text" && normalized.toLowerCase() !== TEXT_ENCODING) {
    throw new ArtifactDownloadSaveError("Text download encoding is unsupported.", {
      status: "DOWNLOAD_TEXT_ENCODING_UNSUPPORTED"
    });
  }
  if (payloadKind === "base64" && normalized.toLowerCase() !== BASE64_ENCODING) {
    throw new ArtifactDownloadSaveError("Base64 download encoding is unsupported.", {
      status: "DOWNLOAD_BASE64_ENCODING_UNSUPPORTED"
    });
  }
  return normalized.toLowerCase();
}

function normalizeContentType(value) {
  return normalizeOptionalText(value) || "application/octet-stream";
}

function normalizeStatus(value) {
  const normalized = normalizeOptionalText(value) || "READY";
  if (!["READY", "PREPARED", "SAVED"].includes(normalized)) {
    throw new ArtifactDownloadSaveError("Download save status is unsupported.", {
      status: "DOWNLOAD_SAVE_STATUS_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeContentLength(value) {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) {
    throw new ArtifactDownloadSaveError("Download content length is invalid.", {
      status: "DOWNLOAD_CONTENT_LENGTH_INVALID"
    });
  }
  return Math.trunc(numeric);
}

function validateBase64Content(value) {
  const text = normalizeOptionalText(value);
  if (text == null) {
    throw new ArtifactDownloadSaveError("Base64 download content is missing.", {
      status: "DOWNLOAD_BASE64_CONTENT_MISSING"
    });
  }
  if (text.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(text)) {
    throw new ArtifactDownloadSaveError("Base64 download content is invalid.", {
      status: "DOWNLOAD_BASE64_CONTENT_INVALID"
    });
  }
}

function decodeBase64ToUint8Array(value) {
  validateBase64Content(value);
  const text = String(value).trim();
  if (typeof globalThis.atob === "function") {
    const binary = globalThis.atob(text);
    return Uint8Array.from(binary, char => char.charCodeAt(0));
  }
  if (typeof globalThis.Buffer === "function") {
    return Uint8Array.from(globalThis.Buffer.from(text, BASE64_ENCODING));
  }
  throw new ArtifactDownloadSaveError("Base64 decoder is not available.", {
    status: "BASE64_DECODER_UNAVAILABLE",
    retryable: true
  });
}

function requiredText(value, fieldName) {
  const text = normalizeOptionalText(value);
  if (!text) {
    throw new ArtifactDownloadSaveError(`${fieldName} is required.`, {
      status: "DOWNLOAD_SAVE_REQUIRED_FIELD_MISSING"
    });
  }
  return text;
}

function normalizeOptionalText(value) {
  if (value == null) return null;
  return String(value).trim();
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
