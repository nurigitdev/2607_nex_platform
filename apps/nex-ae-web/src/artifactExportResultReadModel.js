export const AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION =
  "ae_web_artifact_export_result_read_model.v1";

const READ_MODEL_STATUSES = [
  "READY",
  "EXPORT_PENDING",
  "EXPORT_READY",
  "DOWNLOAD_READY",
  "SAVED",
  "UNAVAILABLE"
];

const SENSITIVE_KEY_NAMES = new Set([
  "content",
  "content_base64",
  "contentbase64",
  "raw",
  "raw_content",
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

export class ArtifactExportResultReadModelError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_EXPORT_RESULT_READ_MODEL_INVALID" } = {}
  ) {
    super(message);
    this.name = "ArtifactExportResultReadModelError";
    this.status = status;
  }
}

export function buildArtifactExportResultReadModel({
  artifactRef = null,
  exportSurface = null,
  downloadSaveSummary = null,
  clientMode = null
} = {}) {
  const artifact = isObject(artifactRef) ? artifactRef : {};
  const exportResult = isObject(exportSurface) ? exportSurface : {};
  const artifactSurface = isObject(exportResult.artifactSurface)
    ? exportResult.artifactSurface
    : {};
  const saveSummary = isObject(downloadSaveSummary) ? downloadSaveSummary : null;
  const downloadRoutes = firstObject(
    artifactSurface.downloadRoutes,
    artifact.downloadRoutes
  );
  const requestedFormats = normalizeFormats(
    exportResult.requestedFormats ||
      artifact.targetFormats ||
      [artifact.primaryFormat].filter(Boolean)
  );
  const renderedFormats = normalizeFormats(
    exportResult.renderedFormats ||
      artifactSurface.availableFormats ||
      artifact.availableFormats ||
      requestedFormats
  );
  const downloadableFormats = normalizeFormats(Object.keys(downloadRoutes));
  const model = {
    artifact_export_result_read_model_schema_version:
      AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
    status: deriveStatus({
      artifactStatus: exportResult.jobStatus || artifact.artifactStatus,
      downloadableFormats,
      saveSummary
    }),
    artifactId:
      normalizeOptionalText(exportResult.artifactId) ||
      normalizeOptionalText(artifactSurface.artifactId) ||
      normalizeOptionalText(artifact.artifactId),
    artifactVersionId:
      normalizeOptionalText(exportResult.artifactVersionId) ||
      normalizeOptionalText(artifactSurface.artifactVersionId) ||
      normalizeOptionalText(artifact.artifactVersionId),
    displayTitle:
      normalizeOptionalText(artifactSurface.displayTitle) ||
      normalizeOptionalText(artifact.displayTitle) ||
      "Untitled artifact",
    renderJobId: normalizeOptionalText(exportResult.renderJobId),
    jobStatus: normalizeOptionalText(exportResult.jobStatus),
    currentStage: normalizeOptionalText(exportResult.currentStage),
    requestedFormats,
    renderedFormats,
    downloadableFormats,
    primaryDownloadFormat:
      normalizeOptionalText(artifact.primaryFormat) ||
      downloadableFormats[0] ||
      renderedFormats[0] ||
      null,
    downloadReady: downloadableFormats.length > 0,
    latestSaveStatus: normalizeOptionalText(saveSummary?.status),
    browserSaveAvailable: Boolean(saveSummary?.browser_save_available),
    fileName: normalizeOptionalText(saveSummary?.file_name),
    contentType: normalizeOptionalText(saveSummary?.content_type),
    payloadKind: normalizeOptionalText(saveSummary?.payload_kind),
    clientMode:
      normalizeOptionalText(clientMode) ||
      normalizeOptionalText(exportResult.clientMode) ||
      normalizeOptionalText(artifactSurface.clientMode) ||
      "mock",
    metadata: safeExportResultMetadata({
      browserSaveAttempted: Boolean(saveSummary),
      browserSaveSucceeded: saveSummary?.status === "SAVED"
    })
  };
  assertArtifactExportResultReadModelSafe(model);
  return model;
}

export function buildArtifactExportResultSummary(model) {
  const current = assertArtifactExportResultReadModel(model);
  const summary = {
    artifact_export_result_read_model_schema_version:
      current.artifact_export_result_read_model_schema_version,
    status: current.status,
    artifact_id: current.artifactId,
    artifact_version_id: current.artifactVersionId,
    render_job_id: current.renderJobId,
    job_status: current.jobStatus,
    current_stage: current.currentStage,
    requested_format_count: current.requestedFormats.length,
    rendered_format_count: current.renderedFormats.length,
    downloadable_format_count: current.downloadableFormats.length,
    downloadable_formats: current.downloadableFormats,
    primary_download_format: current.primaryDownloadFormat,
    download_ready: current.downloadReady,
    latest_save_status: current.latestSaveStatus,
    browser_save_available: current.browserSaveAvailable,
    file_name: current.fileName,
    content_type: current.contentType,
    payload_kind: current.payloadKind,
    client_mode: current.clientMode,
    metadata: current.metadata
  };
  assertArtifactExportResultReadModelSafe(summary);
  return summary;
}

export function renderArtifactExportResultReadModel(model) {
  const current = assertArtifactExportResultReadModel(model);
  const summary = buildArtifactExportResultSummary(current);
  const view = {
    artifact_export_result_renderer_schema_version:
      "ae_web_artifact_export_result_renderer.v1",
    status: current.status,
    severity: severityForStatus(current.status),
    feedback: feedbackForSummary(summary),
    summaryHtml: renderSummary(summary),
    metadata: {
      htmlEscaped: true,
      rawDownloadContentRendered: false,
      rawBase64PayloadRendered: false,
      storageLocationRendered: false
    }
  };
  assertArtifactExportResultReadModelSafe(view);
  return view;
}

export function assertArtifactExportResultReadModelSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactExportResultReadModelKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactExportResultReadModelError(
      "Artifact export result read-model contains sensitive keys.",
      { status: "ARTIFACT_EXPORT_RESULT_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactExportResultReadModelError(
      "Artifact export result read-model contains sensitive values.",
      { status: "ARTIFACT_EXPORT_RESULT_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactExportResultReadModelKeys(payload) {
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

function assertArtifactExportResultReadModel(value) {
  if (
    !isObject(value) ||
    value.artifact_export_result_read_model_schema_version !==
      AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION
  ) {
    throw new ArtifactExportResultReadModelError(
      "Artifact export result read-model is invalid.",
      { status: "ARTIFACT_EXPORT_RESULT_SCHEMA_INVALID" }
    );
  }
  return createNormalizedReadModel(value);
}

function createNormalizedReadModel(value) {
  const status = normalizeStatus(value.status);
  const model = {
    artifact_export_result_read_model_schema_version:
      AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
    status,
    artifactId: normalizeOptionalText(value.artifactId),
    artifactVersionId: normalizeOptionalText(value.artifactVersionId),
    displayTitle: normalizeOptionalText(value.displayTitle) || "Untitled artifact",
    renderJobId: normalizeOptionalText(value.renderJobId),
    jobStatus: normalizeOptionalText(value.jobStatus),
    currentStage: normalizeOptionalText(value.currentStage),
    requestedFormats: normalizeFormats(value.requestedFormats),
    renderedFormats: normalizeFormats(value.renderedFormats),
    downloadableFormats: normalizeFormats(value.downloadableFormats),
    primaryDownloadFormat: normalizeOptionalText(value.primaryDownloadFormat),
    downloadReady: Boolean(value.downloadReady),
    latestSaveStatus: normalizeOptionalText(value.latestSaveStatus),
    browserSaveAvailable: Boolean(value.browserSaveAvailable),
    fileName: normalizeOptionalText(value.fileName),
    contentType: normalizeOptionalText(value.contentType),
    payloadKind: normalizeOptionalText(value.payloadKind),
    clientMode: normalizeOptionalText(value.clientMode) || "mock",
    metadata: safeExportResultMetadata(value.metadata)
  };
  assertArtifactExportResultReadModelSafe(model);
  return model;
}

function deriveStatus({ artifactStatus, downloadableFormats, saveSummary }) {
  if (saveSummary?.status === "SAVED") return "SAVED";
  if (saveSummary?.status === "PREPARED") return "DOWNLOAD_READY";
  const normalizedArtifactStatus = normalizeOptionalText(artifactStatus);
  if (
    normalizedArtifactStatus &&
    !["READY", "COMPLETED", "SUCCEEDED"].includes(normalizedArtifactStatus)
  ) {
    return normalizedArtifactStatus === "FAILED" ? "UNAVAILABLE" : "EXPORT_PENDING";
  }
  if (downloadableFormats.length > 0) return "DOWNLOAD_READY";
  if (normalizedArtifactStatus) return "EXPORT_READY";
  return "READY";
}

function normalizeStatus(value) {
  const normalized = normalizeOptionalText(value) || "READY";
  if (!READ_MODEL_STATUSES.includes(normalized)) {
    throw new ArtifactExportResultReadModelError(
      "Artifact export result status is unsupported.",
      { status: "ARTIFACT_EXPORT_RESULT_STATUS_UNSUPPORTED" }
    );
  }
  return normalized;
}

function normalizeFormats(value) {
  const values = Array.isArray(value) ? value : [];
  return [
    ...new Set(
      values
        .map(item => normalizeOptionalText(item))
        .filter(Boolean)
        .map(item => item.toUpperCase())
    )
  ];
}

function firstObject(...candidates) {
  return candidates.find(isObject) || {};
}

function safeExportResultMetadata(overrides = {}) {
  return {
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    rawDownloadContentIncluded: false,
    rawBase64PayloadIncluded: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    storageLocationIncluded: false,
    browserSaveAttempted: Boolean(overrides.browserSaveAttempted),
    browserSaveSucceeded: Boolean(overrides.browserSaveSucceeded)
  };
}

function severityForStatus(status) {
  if (["SAVED", "DOWNLOAD_READY"].includes(status)) return "success";
  if (["EXPORT_PENDING", "EXPORT_READY"].includes(status)) return "running";
  if (status === "UNAVAILABLE") return "danger";
  return "idle";
}

function feedbackForSummary(summary) {
  if (summary.status === "SAVED") {
    return `Downloaded ${summary.file_name || "artifact"} from ${
      summary.primary_download_format || "artifact"
    }.`;
  }
  if (summary.status === "DOWNLOAD_READY") {
    return `${summary.downloadable_format_count} artifact download format(s) ready.`;
  }
  if (summary.status === "EXPORT_PENDING") {
    return `Export ${summary.render_job_id || "job"} is still preparing.`;
  }
  if (summary.status === "UNAVAILABLE") {
    return "Artifact export result is unavailable.";
  }
  return "Artifact export result is ready for a download action.";
}

function renderSummary(summary) {
  return [
    ["export", summary.status],
    ["formats", summary.downloadable_formats.join(", ") || "n/a"],
    ["render job", summary.render_job_id || "n/a"],
    ["stage", summary.current_stage || summary.job_status || "n/a"],
    ["save", summary.latest_save_status || "not attempted"],
    ["file", summary.file_name || "n/a"]
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

function normalizeOptionalText(value) {
  if (value == null) return null;
  return String(value).trim();
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
