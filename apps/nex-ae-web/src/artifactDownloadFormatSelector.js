import {
  artifactFileIdFromRoute
} from "./artifactPreviewPanel.js";

export const AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION =
  "ae_web_artifact_download_format_selector.v1";

const SENSITIVE_KEY_NAMES = new Set([
  "access_token",
  "authorization",
  "content",
  "content_base64",
  "contentbase64",
  "database_url",
  "password",
  "provider_url",
  "raw_payload",
  "service_token",
  "storage_path",
  "storage_ref"
]);

const SENSITIVE_VALUE_PATTERNS = [
  /postgresql(?:\+\w+)?:\/\/[^"'\s]+/i,
  /\/data\/nex-platform/i,
  /ed6@c496em/i,
  /nuri1004/i,
  /JVBERi0xLjQKJQ==/
];

export class ArtifactDownloadFormatSelectorError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_INVALID" } = {}
  ) {
    super(message);
    this.name = "ArtifactDownloadFormatSelectorError";
    this.status = status;
  }
}

export function buildArtifactDownloadFormatSelector({
  artifactRef = null,
  selectedFormat = null,
  clientMode = "mock"
} = {}) {
  const artifact = normalizeArtifactRef(artifactRef);
  const routes = normalizeDownloadRoutes(artifact.downloadRoutes);
  const formats = normalizeFormats([
    artifact.primaryFormat,
    ...(artifact.availableFormats || []),
    ...Object.keys(routes)
  ]);
  const enabledFormats = formats.filter(format => Boolean(routes[format]));
  const requestedSelected = normalizeOptionalText(selectedFormat)?.toUpperCase();
  const preferredSelected =
    requestedSelected ||
    (enabledFormats.includes(artifact.primaryFormat) ? artifact.primaryFormat : null) ||
    enabledFormats[0] ||
    formats[0] ||
    null;
  const selectedFormatValue = enabledFormats.includes(preferredSelected)
    ? preferredSelected
    : enabledFormats[0] || null;
  const selector = {
    artifact_download_format_selector_schema_version:
      AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION,
    artifactId: artifact.artifactId,
    artifactVersionId: artifact.artifactVersionId,
    displayTitle: artifact.displayTitle,
    status: enabledFormats.length > 0 ? "READY" : "UNAVAILABLE",
    selectedFormat: selectedFormatValue,
    primaryFormat: artifact.primaryFormat,
    options: formats.map(format => {
      const route = routes[format] || null;
      return {
        format,
        label: `Download ${format}`,
        route,
        artifactFileId: route ? artifactFileIdFromRoute(route, "download") : null,
        enabled: Boolean(route),
        selected: Boolean(route && format === selectedFormatValue)
      };
    }),
    clientMode: normalizeOptionalText(clientMode) || artifact.clientMode || "mock",
    metadata: safeSelectorMetadata()
  };
  assertArtifactDownloadFormatSelectorSafe(selector);
  return selector;
}

export function buildArtifactDownloadFormatSelectorSummary(selector) {
  const current = assertArtifactDownloadFormatSelector(selector);
  const enabledOptions = current.options.filter(option => option.enabled);
  const selectedOption = current.options.find(option => option.selected) || null;
  const summary = {
    artifact_download_format_selector_schema_version:
      current.artifact_download_format_selector_schema_version,
    status: current.status,
    artifact_id: current.artifactId,
    artifact_version_id: current.artifactVersionId,
    primary_format: current.primaryFormat,
    selected_format: current.selectedFormat,
    option_count: current.options.length,
    enabled_option_count: enabledOptions.length,
    disabled_option_count: current.options.length - enabledOptions.length,
    selected_route_present: Boolean(selectedOption?.route),
    selected_artifact_file_id: selectedOption?.artifactFileId || null,
    client_mode: current.clientMode,
    metadata: current.metadata
  };
  assertArtifactDownloadFormatSelectorSafe(summary);
  return summary;
}

export function renderArtifactDownloadFormatSelector(selector) {
  const current = assertArtifactDownloadFormatSelector(selector);
  const summary = buildArtifactDownloadFormatSelectorSummary(current);
  const view = {
    artifact_download_format_selector_renderer_schema_version:
      "ae_web_artifact_download_format_selector_renderer.v1",
    status: summary.status,
    selectedFormat: summary.selected_format,
    optionCount: summary.option_count,
    enabledOptionCount: summary.enabled_option_count,
    html: `
      <div
        class="artifact-download-selector"
        data-artifact-download-selector-status="${escapeAttribute(summary.status)}"
        data-artifact-download-selected-format="${escapeAttribute(summary.selected_format || "")}"
        aria-label="아티팩트 다운로드 포맷"
      >
        ${current.options.map(renderOption).join("")}
      </div>
    `,
    metadata: {
      ...safeSelectorMetadata(),
      htmlEscaped: true
    }
  };
  assertArtifactDownloadFormatSelectorSafe(view);
  return view;
}

export function assertArtifactDownloadFormatSelectorSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactDownloadFormatSelectorKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactDownloadFormatSelectorError(
      "Artifact download format selector contains sensitive keys.",
      { status: "ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactDownloadFormatSelectorError(
      "Artifact download format selector contains sensitive values.",
      { status: "ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactDownloadFormatSelectorKeys(payload) {
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

function assertArtifactDownloadFormatSelector(value) {
  if (
    !isObject(value) ||
    value.artifact_download_format_selector_schema_version !==
      AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION
  ) {
    throw new ArtifactDownloadFormatSelectorError(
      "Artifact download format selector is invalid.",
      { status: "ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_INVALID" }
    );
  }
  const normalized = {
    artifact_download_format_selector_schema_version:
      AE_WEB_ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_SCHEMA_VERSION,
    artifactId: requiredText(value.artifactId, "ARTIFACT_ID_MISSING"),
    artifactVersionId: normalizeOptionalText(value.artifactVersionId),
    displayTitle: normalizeOptionalText(value.displayTitle) || "Untitled artifact",
    status:
      normalizeOptionalText(value.status) === "UNAVAILABLE"
        ? "UNAVAILABLE"
        : "READY",
    selectedFormat: normalizeOptionalText(value.selectedFormat),
    primaryFormat: normalizeOptionalText(value.primaryFormat) || null,
    options: normalizeOptions(value.options),
    clientMode: normalizeOptionalText(value.clientMode) || "mock",
    metadata: safeSelectorMetadata(value.metadata)
  };
  assertArtifactDownloadFormatSelectorSafe(normalized);
  return normalized;
}

function normalizeArtifactRef(artifactRef) {
  if (!isObject(artifactRef)) {
    throw new ArtifactDownloadFormatSelectorError("Artifact ref is invalid.", {
      status: "ARTIFACT_DOWNLOAD_FORMAT_SELECTOR_REF_INVALID"
    });
  }
  return {
    artifactId: requiredText(
      artifactRef.artifactId || artifactRef.artifact_id,
      "ARTIFACT_ID_MISSING"
    ),
    artifactVersionId: normalizeOptionalText(
      artifactRef.artifactVersionId || artifactRef.artifact_version_id
    ),
    displayTitle:
      normalizeOptionalText(artifactRef.displayTitle || artifactRef.display_title) ||
      "Untitled artifact",
    primaryFormat:
      normalizeOptionalText(artifactRef.primaryFormat || artifactRef.primary_format)
        ?.toUpperCase() || null,
    availableFormats: normalizeFormats(
      artifactRef.availableFormats || artifactRef.available_formats || []
    ),
    downloadRoutes:
      firstObject(artifactRef.downloadRoutes, artifactRef.download_routes) || {},
    clientMode: normalizeOptionalText(artifactRef.clientMode || artifactRef.client_mode)
  };
}

function normalizeDownloadRoutes(downloadRoutes) {
  const source = isObject(downloadRoutes) ? downloadRoutes : {};
  const normalized = {};
  for (const [format, route] of Object.entries(source)) {
    const normalizedFormat = normalizeOptionalText(format)?.toUpperCase();
    const normalizedRoute = normalizeOptionalText(route);
    if (!normalizedFormat || !normalizedRoute) continue;
    artifactFileIdFromRoute(normalizedRoute, "download");
    normalized[normalizedFormat] = normalizedRoute;
  }
  return normalized;
}

function normalizeOptions(options) {
  if (!Array.isArray(options)) {
    throw new ArtifactDownloadFormatSelectorError(
      "Artifact download format options are invalid.",
      { status: "ARTIFACT_DOWNLOAD_FORMAT_OPTIONS_INVALID" }
    );
  }
  return options.map(option => {
    if (!isObject(option)) {
      throw new ArtifactDownloadFormatSelectorError(
        "Artifact download format option is invalid.",
        { status: "ARTIFACT_DOWNLOAD_FORMAT_OPTION_INVALID" }
      );
    }
    const format = requiredText(option.format, "ARTIFACT_DOWNLOAD_FORMAT_MISSING")
      .toUpperCase();
    const route = normalizeOptionalText(option.route);
    if (route) {
      artifactFileIdFromRoute(route, "download");
    }
    return {
      format,
      label: normalizeOptionalText(option.label) || `Download ${format}`,
      route,
      artifactFileId: route
        ? artifactFileIdFromRoute(route, "download")
        : normalizeOptionalText(option.artifactFileId),
      enabled: Boolean(option.enabled && route),
      selected: Boolean(option.selected && option.enabled && route)
    };
  });
}

function normalizeFormats(values) {
  return [
    ...new Set(
      (Array.isArray(values) ? values : [])
        .map(value => normalizeOptionalText(value))
        .filter(Boolean)
        .map(value => value.toUpperCase())
    )
  ];
}

function renderOption(option) {
  if (!option.enabled) {
    return `
      <button
        type="button"
        data-artifact-download-format="${escapeAttribute(option.format)}"
        aria-disabled="true"
        disabled
      >${escapeHtml(option.label)}</button>
    `;
  }
  return `
    <a
      href="${escapeAttribute(option.route)}"
      role="button"
      aria-pressed="${option.selected ? "true" : "false"}"
      data-artifact-action="download"
      data-artifact-download-format="${escapeAttribute(option.format)}"
      data-artifact-download-route="${escapeAttribute(option.route)}"
    >${escapeHtml(option.label)}</a>
  `;
}

function safeSelectorMetadata(overrides = {}) {
  return {
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    rawDownloadContentIncluded: false,
    rawBase64PayloadIncluded: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    storageLocationIncluded: false,
    htmlEscaped: Boolean(overrides.htmlEscaped)
  };
}

function firstObject(...candidates) {
  return candidates.find(isObject) || null;
}

function requiredText(value, status) {
  const text = normalizeOptionalText(value);
  if (!text) {
    throw new ArtifactDownloadFormatSelectorError(
      "Artifact download format selector field is required.",
      { status }
    );
  }
  return text;
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
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
