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
      contentLength: downloadSurface.contentLength
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
    client_mode: current.clientMode,
    error_status: current.errorStatus,
    retryable: current.retryable,
    metadata: current.metadata
  };
  assertArtifactPreviewPanelSafe(summary);
  return summary;
}

export function renderArtifactPreviewPanel(state) {
  const summary = buildArtifactPreviewPanelSummary(state);
  const current = assertArtifactPreviewPanelState(state);
  const feedback = panelFeedback(summary);
  const view = {
    artifact_preview_panel_renderer_schema_version:
      "ae_web_artifact_preview_panel_renderer.v1",
    status: summary.status,
    severity: feedback.severity,
    feedback: feedback.message,
    summaryHtml: renderSummary(summary),
    bodyText: panelBodyText(current),
    bodyMode: panelBodyMode(current),
    metadata: {
      htmlEscaped: true,
      contentRendered: current.status === "PREVIEW_READY",
      downloadedContentRendered: false
    }
  };
  assertArtifactPreviewPanelSafe(view);
  return view;
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
  return {
    fileName: normalizeOptionalText(download.fileName) || "artifact",
    format: normalizeOptionalText(download.format) || "UNKNOWN",
    contentType:
      normalizeOptionalText(download.contentType) || "application/octet-stream",
    contentHash: normalizeOptionalText(download.contentHash),
    contentLength: normalizeContentLength(download.contentLength)
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

function panelFeedback(summary) {
  if (summary.status === "RUNNING") {
    return { severity: "running", message: "아티팩트 요청을 처리하고 있습니다." };
  }
  if (summary.status === "PREVIEW_READY") {
    return { severity: "success", message: "아티팩트 미리보기가 준비되었습니다." };
  }
  if (summary.status === "DOWNLOAD_READY") {
    return { severity: "success", message: "다운로드 파일 메타데이터가 준비되었습니다." };
  }
  if (summary.status === "UNAVAILABLE") {
    return {
      severity: "danger",
      message: `아티팩트 요청을 완료하지 못했습니다. ${summary.error_status || "UNAVAILABLE"}`
    };
  }
  return { severity: "idle", message: "아티팩트 미리보기와 다운로드를 선택할 수 있습니다." };
}

function panelBodyText(state) {
  if (state.status === "PREVIEW_READY") {
    return state.preview?.textPreview || "Preview is empty.";
  }
  if (state.status === "DOWNLOAD_READY") {
    const fileName = state.download?.fileName || "artifact";
    const length = state.download?.contentLength ?? 0;
    return `Download prepared: ${fileName}\nContent length: ${length} bytes\nDownloaded content is not rendered in the browser panel.`;
  }
  if (state.status === "RUNNING") return "Loading artifact surface...";
  if (state.status === "UNAVAILABLE") {
    return `Request failed: ${state.errorStatus || "UNAVAILABLE"}`;
  }
  return "Select Preview or Download from an artifact card.";
}

function panelBodyMode(state) {
  if (state.status === "PREVIEW_READY") return "preview";
  if (state.status === "DOWNLOAD_READY") return "download";
  if (state.status === "RUNNING") return "loading";
  if (state.status === "UNAVAILABLE") return "error";
  return "empty";
}

function renderSummary(summary) {
  return [
    ["status", summary.status],
    ["action", summary.action],
    ["file", summary.file_name || "n/a"],
    ["format", summary.format || "n/a"],
    ["route", summary.route || "n/a"],
    ["client", summary.client_mode],
    [
      "content",
      summary.action === "download"
        ? `${summary.content_hash_present ? "hash present" : "hash empty"} · ${
            summary.content_length ?? 0
          } bytes`
        : summary.truncated
          ? "preview truncated"
          : "preview"
    ]
  ]
    .map(
      ([term, value]) => `
      <div>
        <dt>${escapeHtml(term)}</dt>
        <dd>${escapeHtml(value)}</dd>
      </div>
    `
    )
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
