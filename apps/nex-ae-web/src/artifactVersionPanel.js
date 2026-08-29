export const AE_WEB_ARTIFACT_VERSION_PANEL_SCHEMA_VERSION =
  "ae_web_artifact_version_panel.v1";

const PANEL_STATUSES = [
  "READY",
  "RUNNING",
  "VERSION_READY",
  "EMPTY",
  "UNAVAILABLE"
];

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

export class ArtifactVersionPanelError extends Error {
  constructor(message, { status = "ARTIFACT_VERSION_PANEL_INVALID" } = {}) {
    super(message);
    this.name = "ArtifactVersionPanelError";
    this.status = status;
  }
}

export function createArtifactVersionPanelState({
  status = "READY",
  artifactId = null,
  displayTitle = null,
  currentVersionId = null,
  route = null,
  versions = [],
  files = [],
  errorStatus = null,
  retryable = false,
  clientMode = "mock"
} = {}) {
  const normalizedVersions = normalizeVersions(versions, currentVersionId);
  const normalizedFiles = normalizeFiles(files);
  const normalizedCurrentVersionId =
    normalizeOptionalText(currentVersionId) ||
    normalizedVersions.find(version => version.current)?.artifactVersionId ||
    null;
  const state = {
    artifact_version_panel_schema_version:
      AE_WEB_ARTIFACT_VERSION_PANEL_SCHEMA_VERSION,
    status: normalizeStatus(status),
    artifactId: normalizeOptionalText(artifactId),
    displayTitle: normalizeOptionalText(displayTitle),
    currentVersionId: normalizedCurrentVersionId,
    route: route == null ? null : normalizeRoute(route),
    versions: normalizedVersions.map(version => ({
      ...version,
      current:
        Boolean(version.current) ||
        (Boolean(normalizedCurrentVersionId) &&
          version.artifactVersionId === normalizedCurrentVersionId)
    })),
    files: normalizedFiles,
    errorStatus: normalizeOptionalText(errorStatus),
    retryable: Boolean(retryable),
    clientMode: normalizeOptionalText(clientMode) || "mock",
    metadata: safePanelMetadata()
  };
  assertArtifactVersionPanelSafe(state);
  return state;
}

export function createRunningArtifactVersionPanelState({
  artifactId = null,
  displayTitle = null,
  currentVersionId = null,
  route = null,
  clientMode = "mock"
} = {}) {
  return createArtifactVersionPanelState({
    status: "RUNNING",
    artifactId,
    displayTitle,
    currentVersionId,
    route,
    clientMode
  });
}

export function buildArtifactVersionPanelState({
  artifactSurface,
  versionsSurface
} = {}) {
  const artifact = requiredArtifactSurface(artifactSurface);
  const versions = requiredVersionsSurface(versionsSurface);
  const artifactFiles = Array.isArray(artifact.files) ? artifact.files : [];
  const artifactLinks = Array.isArray(artifact.links) ? artifact.links : [];
  const currentVersionId =
    versions.currentVersionId || artifact.artifactVersionId || null;
  const files = artifactFiles.map(file =>
    buildVersionPanelFile(file, artifactLinks)
  );
  const versionRows = versions.versions.map(version => ({
    artifactVersionId: version.artifactVersionId,
    versionNo: version.versionNo,
    current:
      Boolean(currentVersionId) && version.artifactVersionId === currentVersionId,
    renderedFormats: version.renderedFormats,
    sourceContentHashPresent: Boolean(version.sourceContentHash),
    artifactContentHashPresent: Boolean(version.artifactContentHash),
    files: files.filter(
      file =>
        file.artifactVersionId &&
        version.artifactVersionId &&
        file.artifactVersionId === version.artifactVersionId
    )
  }));
  const state = createArtifactVersionPanelState({
    status: versionRows.length > 0 ? "VERSION_READY" : "EMPTY",
    artifactId: artifact.artifactId,
    displayTitle: artifact.displayTitle,
    currentVersionId,
    route: versions.route,
    versions: versionRows,
    files,
    clientMode: artifact.clientMode || versions.clientMode
  });
  assertArtifactVersionPanelSafe(state);
  return state;
}

export function buildArtifactVersionPanelStateFromError(
  error,
  { artifactId = null, displayTitle = null, currentVersionId = null, route = null, clientMode = "mock" } = {}
) {
  return createArtifactVersionPanelState({
    status: "UNAVAILABLE",
    artifactId,
    displayTitle,
    currentVersionId,
    route,
    errorStatus: error?.status || "ARTIFACT_VERSION_PANEL_ERROR",
    retryable: Boolean(error?.retryable),
    clientMode
  });
}

export function buildArtifactVersionPanelSummary(state) {
  const current = assertArtifactVersionPanelState(state);
  const formats = uniqueTexts([
    ...current.files.map(file => file.format),
    ...current.versions.flatMap(version => version.renderedFormats)
  ]);
  const summary = {
    artifact_version_panel_schema_version:
      current.artifact_version_panel_schema_version,
    status: current.status,
    artifact_id: current.artifactId,
    current_version_id: current.currentVersionId,
    route: current.route,
    version_count: current.versions.length,
    file_count: current.files.length,
    format_count: formats.length,
    formats,
    current_version_found: current.versions.some(version => version.current),
    preview_route_count: current.files.filter(file => file.previewRoute).length,
    download_route_count: current.files.filter(file => file.downloadRoute).length,
    hash_presence_count:
      current.versions.filter(version => version.artifactContentHashPresent).length +
      current.files.filter(file => file.fileHashPresent).length,
    client_mode: current.clientMode,
    error_status: current.errorStatus,
    retryable: current.retryable,
    metadata: current.metadata
  };
  assertArtifactVersionPanelSafe(summary);
  return summary;
}

export function renderArtifactVersionPanel(state) {
  const current = assertArtifactVersionPanelState(state);
  const summary = buildArtifactVersionPanelSummary(current);
  const feedback = panelFeedback(summary);
  const view = {
    artifact_version_panel_renderer_schema_version:
      "ae_web_artifact_version_panel_renderer.v1",
    status: summary.status,
    severity: feedback.severity,
    feedback: feedback.message,
    summaryHtml: renderSummary(summary),
    listHtml: renderVersionList(current),
    metadata: {
      htmlEscaped: true,
      contentRendered: false,
      storageLocationRendered: false
    }
  };
  assertArtifactVersionPanelSafe(view);
  return view;
}

export function assertArtifactVersionPanelSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactVersionPanelKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactVersionPanelError(
      "Artifact version panel contains sensitive keys.",
      { status: "ARTIFACT_VERSION_PANEL_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactVersionPanelError(
      "Artifact version panel contains sensitive values.",
      { status: "ARTIFACT_VERSION_PANEL_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactVersionPanelKeys(payload) {
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

function requiredArtifactSurface(value) {
  if (!isObject(value) || !value.artifactId) {
    throw new ArtifactVersionPanelError("Artifact surface is invalid.", {
      status: "ARTIFACT_SURFACE_INVALID"
    });
  }
  return value;
}

function requiredVersionsSurface(value) {
  if (!isObject(value) || !Array.isArray(value.versions)) {
    throw new ArtifactVersionPanelError("Artifact versions surface is invalid.", {
      status: "ARTIFACT_VERSIONS_SURFACE_INVALID"
    });
  }
  return value;
}

function buildVersionPanelFile(file, links) {
  const normalizedFile = normalizeFile(file);
  return {
    ...normalizedFile,
    previewRoute: linkRouteForFile(links, normalizedFile.artifactFileId, "preview"),
    downloadRoute: linkRouteForFile(links, normalizedFile.artifactFileId, "download")
  };
}

function normalizeVersions(versions, currentVersionId) {
  if (!Array.isArray(versions)) {
    throw new ArtifactVersionPanelError("Artifact versions must be an array.", {
      status: "ARTIFACT_VERSIONS_INVALID"
    });
  }
  return versions.map(version => normalizeVersion(version, currentVersionId));
}

function normalizeVersion(version, currentVersionId) {
  if (!isObject(version)) {
    throw new ArtifactVersionPanelError("Artifact version is invalid.", {
      status: "ARTIFACT_VERSION_INVALID"
    });
  }
  const artifactVersionId = normalizeOptionalText(
    version.artifactVersionId || version.artifact_version_id
  );
  return {
    artifactVersionId,
    versionNo: numberOrNull(version.versionNo ?? version.version_no),
    current:
      Boolean(version.current) ||
      (Boolean(currentVersionId) && artifactVersionId === currentVersionId),
    renderedFormats: uniqueTexts(
      version.renderedFormats || version.rendered_formats || []
    ),
    sourceContentHashPresent: Boolean(
      version.sourceContentHashPresent ||
        version.source_content_hash_present ||
        version.sourceContentHash ||
        version.source_content_hash
    ),
    artifactContentHashPresent: Boolean(
      version.artifactContentHashPresent ||
        version.artifact_content_hash_present ||
        version.artifactContentHash ||
        version.artifact_content_hash
    ),
    files: normalizeFiles(version.files || [])
  };
}

function normalizeFiles(files) {
  if (!Array.isArray(files)) {
    throw new ArtifactVersionPanelError("Artifact files must be an array.", {
      status: "ARTIFACT_FILES_INVALID"
    });
  }
  return files.map(normalizeFile);
}

function normalizeFile(file) {
  if (!isObject(file)) {
    throw new ArtifactVersionPanelError("Artifact file is invalid.", {
      status: "ARTIFACT_FILE_INVALID"
    });
  }
  return {
    artifactFileId: requiredText(
      file.artifactFileId || file.artifact_file_id,
      "ARTIFACT_FILE_ID_INVALID"
    ),
    artifactVersionId: normalizeOptionalText(
      file.artifactVersionId || file.artifact_version_id
    ),
    format: normalizeOptionalText(file.format) || "UNKNOWN",
    mimeType:
      normalizeOptionalText(file.mimeType || file.mime_type) ||
      "application/octet-stream",
    fileName: normalizeOptionalText(file.fileName || file.file_name) || "artifact",
    fileSizeBytes: numberOrNull(file.fileSizeBytes ?? file.file_size_bytes),
    fileHashPresent: Boolean(
      file.fileHashPresent ||
        file.file_hash_present ||
        file.fileHash ||
        file.file_hash
    ),
    sourceVersionHashPresent: Boolean(
      file.sourceVersionHashPresent ||
        file.source_version_hash_present ||
        file.sourceVersionHash ||
        file.source_version_hash
    ),
    previewRoute: safeRoute(file.previewRoute || file.preview_route),
    downloadRoute: safeRoute(file.downloadRoute || file.download_route)
  };
}

function linkRouteForFile(links, artifactFileId, linkType) {
  if (!Array.isArray(links)) return null;
  const found = links.find(
    link =>
      (link.artifactFileId || link.artifact_file_id) === artifactFileId &&
      (link.linkType || link.link_type) === linkType
  );
  return safeRoute(found?.linkRoute || found?.link_route);
}

function panelFeedback(summary) {
  if (summary.status === "RUNNING") {
    return {
      severity: "running",
      message: "Artifact version metadata is loading."
    };
  }
  if (summary.status === "VERSION_READY") {
    return {
      severity: "success",
      message: "Artifact versions and generated files are ready."
    };
  }
  if (summary.status === "EMPTY") {
    return {
      severity: "pending",
      message: "No rendered artifact version has been recorded yet."
    };
  }
  if (summary.status === "UNAVAILABLE") {
    return {
      severity: "danger",
      message: `Artifact version metadata is unavailable. ${summary.error_status || "ARTIFACT_VERSION_PANEL_ERROR"}`
    };
  }
  return {
    severity: "neutral",
    message: "Artifact version metadata is ready to load."
  };
}

function renderSummary(summary) {
  return `
    <div>
      <dt>versions</dt>
      <dd>${escapeHtml(summary.version_count)}</dd>
    </div>
    <div>
      <dt>files</dt>
      <dd>${escapeHtml(summary.file_count)}</dd>
    </div>
    <div>
      <dt>formats</dt>
      <dd>${escapeHtml(summary.formats.join(", ") || "n/a")}</dd>
    </div>
    <div>
      <dt>current</dt>
      <dd>${escapeHtml(summary.current_version_id || "pending")}</dd>
    </div>
    <div>
      <dt>actions</dt>
      <dd>${escapeHtml(`${summary.preview_route_count} preview · ${summary.download_route_count} download`)}</dd>
    </div>
    <div>
      <dt>client</dt>
      <dd>${escapeHtml(summary.client_mode)}</dd>
    </div>
  `;
}

function renderVersionList(state) {
  if (state.status === "RUNNING") {
    return `<p class="artifact-version-empty">Loading version metadata.</p>`;
  }
  if (state.status === "UNAVAILABLE") {
    return `<p class="artifact-version-empty">Version metadata request failed.</p>`;
  }
  if (state.versions.length === 0) {
    return `<p class="artifact-version-empty">No rendered versions.</p>`;
  }
  return `
    <ul class="artifact-version-list" aria-label="Artifact versions">
      ${state.versions.map(renderVersionItem).join("")}
    </ul>
  `;
}

function renderVersionItem(version) {
  const label =
    version.versionNo == null
      ? version.artifactVersionId || "pending"
      : `v${version.versionNo}`;
  return `
    <li data-current="${version.current ? "true" : "false"}">
      <div class="artifact-version-row">
        <strong>${escapeHtml(label)}</strong>
        <span>${escapeHtml(version.current ? "current" : "archived")}</span>
      </div>
      <dl class="inline-meta slim">
        <div>
          <dt>formats</dt>
          <dd>${escapeHtml(version.renderedFormats.join(", ") || "n/a")}</dd>
        </div>
        <div>
          <dt>hash</dt>
          <dd>${escapeHtml(version.artifactContentHashPresent ? "present" : "missing")}</dd>
        </div>
        <div>
          <dt>files</dt>
          <dd>${escapeHtml(version.files.length)}</dd>
        </div>
      </dl>
      ${renderVersionFiles(version.files)}
    </li>
  `;
}

function renderVersionFiles(files) {
  if (files.length === 0) return "";
  return `
    <ul class="artifact-file-list" aria-label="Artifact files">
      ${files.map(renderFileItem).join("")}
    </ul>
  `;
}

function renderFileItem(file) {
  const size =
    file.fileSizeBytes == null ? "n/a" : `${file.fileSizeBytes.toLocaleString()} B`;
  const actions = [
    file.previewRoute ? "preview" : null,
    file.downloadRoute ? "download" : null
  ].filter(Boolean);
  return `
    <li>
      <span>${escapeHtml(file.fileName)}</span>
      <em>${escapeHtml(`${file.format} · ${size} · ${actions.join("/") || "no action"}`)}</em>
    </li>
  `;
}

function assertArtifactVersionPanelState(value) {
  if (
    !value ||
    value.artifact_version_panel_schema_version !==
      AE_WEB_ARTIFACT_VERSION_PANEL_SCHEMA_VERSION
  ) {
    throw new ArtifactVersionPanelError("Artifact version panel state is invalid.", {
      status: "ARTIFACT_VERSION_PANEL_SCHEMA_INVALID"
    });
  }
  return createArtifactVersionPanelState(value);
}

function normalizeStatus(status) {
  if (!PANEL_STATUSES.includes(status)) {
    throw new ArtifactVersionPanelError("Artifact version status is unsupported.", {
      status: "ARTIFACT_VERSION_STATUS_UNSUPPORTED"
    });
  }
  return status;
}

function normalizeRoute(route) {
  const value = normalizeOptionalText(route);
  if (!value) return null;
  if (!value.startsWith("/api/v1/")) {
    throw new ArtifactVersionPanelError("Artifact version route is invalid.", {
      status: "ARTIFACT_VERSION_ROUTE_INVALID"
    });
  }
  return value;
}

function safeRoute(route) {
  if (!route) return null;
  return normalizeRoute(route);
}

function numberOrNull(value) {
  if (value == null || value === "") return null;
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue) || numberValue < 0) {
    throw new ArtifactVersionPanelError("Artifact version number is invalid.", {
      status: "ARTIFACT_NUMBER_INVALID"
    });
  }
  return numberValue;
}

function requiredText(value, status) {
  const text = normalizeOptionalText(value);
  if (!text) {
    throw new ArtifactVersionPanelError("Artifact version panel field is required.", {
      status
    });
  }
  return text;
}

function normalizeOptionalText(value) {
  if (value == null) return null;
  const text = String(value).trim();
  return text || null;
}

function uniqueTexts(values) {
  return [
    ...new Set(
      (Array.isArray(values) ? values : [])
        .map(value => String(value || "").trim())
        .filter(Boolean)
    )
  ];
}

function safePanelMetadata() {
  return {
    contentRendered: false,
    fileHashRendered: false,
    sourceHashRendered: false,
    storageLocationRendered: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    rawPromptRendered: false,
    rawSourceRendered: false
  };
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
