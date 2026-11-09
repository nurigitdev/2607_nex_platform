export const AE_WEB_ARTIFACT_PREVIEW_PANEL_SCHEMA_VERSION =
  "ae_web_artifact_preview_panel.v1";

const PANEL_STATUSES = [
  "IDLE",
  "READY",
  "RUNNING",
  "PREVIEW_READY",
  "DOWNLOAD_READY",
  "UNAVAILABLE"
];
const PANEL_ACTIONS = ["none", "preview", "download"];
const ARTIFACT_FILE_ROUTE_PATTERN =
  /^\/api\/v1\/artifact-files\/([^/?#]+)\/(preview|download)(?:[?#].*)?$/;

const SENSITIVE_KEY_PARTS = [
  "api_key",
  "authorization",
  "credential",
  "database_url",
  "model_path",
  "password",
  "passwd",
  "provider_endpoint",
  "provider_url",
  "raw_prompt",
  "raw_source",
  "raw_text",
  "secret",
  "service_token",
  "source_text",
  "storage_path",
  "storage_ref",
  "token"
];

const ALLOWED_FALSE_SENSITIVE_FLAGS = [
  "browserServiceTokenIncluded",
  "databaseEndpointIncluded",
  "providerEndpointIncluded",
  "rawPromptRendered",
  "rawSourceRendered",
  "storageLocationRendered"
];

const SENSITIVE_VALUE_PATTERNS = [
  /postgresql\+?[^"'\s]+/i,
  /\/data\/nex-platform/i,
  /ed6@c496em/i,
  /nuri1004/i
];

export class ArtifactPreviewPanelError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_PREVIEW_PANEL_INVALID" } = {}
  ) {
    super(message);
    this.name = "ArtifactPreviewPanelError";
    this.status = status;
  }
}

export function artifactFileIdFromRoute(route, expectedAction = null) {
  const normalizedRoute = normalizeRoute(route);
  const match = normalizedRoute.match(ARTIFACT_FILE_ROUTE_PATTERN);
  if (!match) {
    throw new ArtifactPreviewPanelError("Artifact file route is invalid.", {
      status: "ARTIFACT_FILE_ROUTE_INVALID"
    });
  }
  const action = match[2];
  if (expectedAction && action !== expectedAction) {
    throw new ArtifactPreviewPanelError("Artifact file route action does not match.", {
      status: "ARTIFACT_FILE_ROUTE_ACTION_MISMATCH"
    });
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    throw new ArtifactPreviewPanelError("Artifact file route encoding is invalid.", {
      status: "ARTIFACT_FILE_ROUTE_ENCODING_INVALID"
    });
  }
}

export function createArtifactPreviewPanelState({
  status = "READY",
  action = "none",
  artifactId = null,
  artifactFileId = null,
  route = null,
  preview = null,
  download = null,
  errorStatus = null,
  retryable = false,
  clientMode = "mock"
} = {}) {
  const normalizedStatus = normalizeStatus(status);
  const normalizedAction = normalizeAction(action);
  const state = {
    artifact_preview_panel_schema_version:
      AE_WEB_ARTIFACT_PREVIEW_PANEL_SCHEMA_VERSION,
    status: normalizedStatus,
    action: normalizedAction,
    artifactId: normalizeOptionalText(artifactId),
    artifactFileId: normalizeOptionalText(artifactFileId),
    route: route == null ? null : normalizeRoute(route),
    preview: preview ? normalizePreview(preview) : null,
    download: download ? normalizeDownload(download) : null,
    errorStatus: normalizeOptionalText(errorStatus),
    retryable: Boolean(retryable),
    clientMode: normalizeOptionalText(clientMode) || "mock",
    metadata: safePanelMetadata({
      contentRendered: Boolean(preview),
      downloadedContentRendered: false,
      previewTextRendered: Boolean(preview)
    })
  };
  assertArtifactPreviewPanelSafe(state);
  return state;
}

export function createRunningArtifactPreviewPanelState({
  action,
  artifactId,
  artifactFileId,
  route,
  clientMode = "mock"
} = {}) {
  return createArtifactPreviewPanelState({
    status: "RUNNING",
    action,
    artifactId,
    artifactFileId,
    route,
    clientMode
  });
}

export function buildArtifactPreviewPanelStateFromPreview(
  previewSurface,
  { artifactId = null, route = null } = {}
) {
  const file = requiredArtifactFile(previewSurface);
  return createArtifactPreviewPanelState({
    status: "PREVIEW_READY",
    action: "preview",
    artifactId,
    artifactFileId: file.artifactFileId,
    route: route || previewSurface.route,
    preview: {
      fileName: file.fileName,
      format: file.format,
      contentType: previewSurface.contentType,
      textPreview: previewSurface.textPreview,
      truncated: previewSurface.truncated
    },
    clientMode: previewSurface.clientMode
  });
}

export function buildArtifactPreviewPanelStateFromDownload(
  downloadSurface,
  { artifactId = null, route = null } = {}
) {
  const file = requiredArtifactFile(downloadSurface);
  return createArtifactPreviewPanelState({
    status: "DOWNLOAD_READY",
    action: "download",
    artifactId,
    artifactFileId: file.artifactFileId,
    route: route || downloadSurface.route,
    download: {
      fileName: downloadSurface.downloadFileName || file.fileName,
      format: file.format,
      contentType: downloadSurface.contentType,
      contentHash: downloadSurface.contentHash || file.fileHash,
      contentLength: downloadSurface.contentLength,
      encodedContentLength: downloadSurface.encodedContentLength,
      contentEncoding: downloadSurface.contentEncoding,
      downloadPayloadKind: downloadSurface.downloadPayloadKind
    },
    clientMode: downloadSurface.clientMode
  });
}

export function buildArtifactPreviewPanelStateFromError(
  error,
  { action, artifactId = null, artifactFileId = null, route = null, clientMode = "mock" } = {}
) {
  return createArtifactPreviewPanelState({
    status: "UNAVAILABLE",
    action,
    artifactId,
    artifactFileId,
    route,
    errorStatus: error?.status || "ARTIFACT_PREVIEW_PANEL_ERROR",
    retryable: Boolean(error?.retryable),
    clientMode
  });
}

export function buildArtifactPreviewPanelSummary(state) {
  const current = assertArtifactPreviewPanelState(state);
  const summary = {
    artifact_preview_panel_schema_version:
      current.artifact_preview_panel_schema_version,
    status: current.status,
    action: current.action,
    artifact_id: current.artifactId,
    artifact_file_id: current.artifactFileId,
    route: current.route,
    file_name: current.preview?.fileName || current.download?.fileName || null,
    format: current.preview?.format || current.download?.format || null,
    content_type:
      current.preview?.contentType || current.download?.contentType || null,
    truncated: current.preview?.truncated || false,
    content_hash_present: Boolean(current.download?.contentHash),
    content_length: current.download?.contentLength ?? null,
    encoded_content_length: current.download?.encodedContentLength ?? null,
    content_encoding: current.download?.contentEncoding || null,
    download_payload_kind: current.download?.downloadPayloadKind || null,
    client_mode: current.clientMode,
    error_status: current.errorStatus,
    retryable: current.retryable,
    metadata: current.metadata
  };
  assertArtifactPreviewPanelSafe(summary);
  return summary;
}

export function assertArtifactPreviewPanelSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactPreviewPanelKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactPreviewPanelError(
      "Artifact preview panel contains sensitive keys.",
      { status: "ARTIFACT_PREVIEW_PANEL_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactPreviewPanelError(
      "Artifact preview panel contains sensitive values.",
      { status: "ARTIFACT_PREVIEW_PANEL_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactPreviewPanelKeys(payload) {
  const found = [];

  function visit(value, path) {
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    if (!isObject(value)) return;
    for (const [key, child] of Object.entries(value)) {
      const keyPath = path ? `${path}.${key}` : key;
      const normalized = key.toLowerCase();
      if (
        SENSITIVE_KEY_PARTS.some(part => normalized.includes(part)) &&
        !isAllowedFalseSensitiveFlag(key, child)
      ) {
        found.push(keyPath);
      }
      visit(child, keyPath);
    }
  }

  visit(payload, "");
  return found.sort();
}

function assertArtifactPreviewPanelState(value) {
  if (
    !isObject(value) ||
    value.artifact_preview_panel_schema_version !==
      AE_WEB_ARTIFACT_PREVIEW_PANEL_SCHEMA_VERSION
  ) {
    throw new ArtifactPreviewPanelError("Artifact preview panel state is invalid.", {
      status: "ARTIFACT_PREVIEW_PANEL_SCHEMA_INVALID"
    });
  }
  return createArtifactPreviewPanelState(value);
}

function requiredArtifactFile(surface) {
  if (!isObject(surface?.artifactFile)) {
    throw new ArtifactPreviewPanelError("Artifact file surface is invalid.", {
      status: "ARTIFACT_FILE_SURFACE_INVALID"
    });
  }
  return surface.artifactFile;
}

function normalizePreview(preview) {
  return {
    fileName: normalizeOptionalText(preview.fileName) || "artifact",
    format: normalizeOptionalText(preview.format) || "UNKNOWN",
    contentType: normalizeOptionalText(preview.contentType) || "text/plain",
    textPreview: normalizePreviewText(preview.textPreview),
    truncated: Boolean(preview.truncated)
  };
}

function normalizeDownload(download) {
  const downloadPayloadKind = normalizeDownloadPayloadKind(download.downloadPayloadKind);
  return {
    fileName: normalizeOptionalText(download.fileName) || "artifact",
    format: normalizeOptionalText(download.format) || "UNKNOWN",
    contentType:
      normalizeOptionalText(download.contentType) || "application/octet-stream",
    contentHash: normalizeOptionalText(download.contentHash),
    contentLength: normalizeContentLength(download.contentLength),
    encodedContentLength: normalizeContentLength(download.encodedContentLength),
    contentEncoding:
      normalizeOptionalText(download.contentEncoding) ||
      (downloadPayloadKind === "base64" ? "base64" : "utf-8"),
    downloadPayloadKind
  };
}

function normalizePreviewText(value) {
  const text = normalizeOptionalText(value) || "";
  if (text.length <= 2400) return text;
  return `${text.slice(0, 2400)}...`;
}

function normalizeContentLength(value) {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) {
    throw new ArtifactPreviewPanelError("Download content length is invalid.", {
      status: "ARTIFACT_DOWNLOAD_LENGTH_INVALID"
    });
  }
  return Math.trunc(numeric);
}

function normalizeDownloadPayloadKind(value) {
  const normalized = normalizeOptionalText(value) || "text";
  if (!["text", "base64"].includes(normalized)) {
    throw new ArtifactPreviewPanelError("Download payload kind is unsupported.", {
      status: "ARTIFACT_DOWNLOAD_PAYLOAD_KIND_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeStatus(status) {
  const normalized = normalizeOptionalText(status) || "READY";
  if (!PANEL_STATUSES.includes(normalized)) {
    throw new ArtifactPreviewPanelError("Artifact preview status is unsupported.", {
      status: "ARTIFACT_PREVIEW_STATUS_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeAction(action) {
  const normalized = normalizeOptionalText(action) || "none";
  if (!PANEL_ACTIONS.includes(normalized)) {
    throw new ArtifactPreviewPanelError("Artifact preview action is unsupported.", {
      status: "ARTIFACT_PREVIEW_ACTION_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeRoute(route) {
  if (typeof route !== "string" || !route.trim() || !route.trim().startsWith("/")) {
    throw new ArtifactPreviewPanelError("Artifact route is invalid.", {
      status: "ARTIFACT_ROUTE_INVALID"
    });
  }
  return route.trim();
}

function normalizeOptionalText(value) {
  if (value == null) return null;
  return String(value).trim();
}

function safePanelMetadata(overrides = {}) {
  return {
    rawPromptRendered: false,
    rawSourceRendered: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    storageLocationRendered: false,
    contentRendered: Boolean(overrides.contentRendered),
    previewTextRendered: Boolean(overrides.previewTextRendered),
    downloadedContentRendered: false
  };
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
