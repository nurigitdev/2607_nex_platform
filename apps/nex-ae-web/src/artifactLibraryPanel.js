import {
  AE_WEB_ARTIFACT_COLLECTION_SURFACE_SCHEMA_VERSION,
  buildArtifactCollectionSummary
} from "./artifactClient.js";

export const AE_WEB_ARTIFACT_LIBRARY_PANEL_SCHEMA_VERSION =
  "ae_web_artifact_library_panel.v1";
export const AE_WEB_ARTIFACT_LIBRARY_PANEL_RENDERER_SCHEMA_VERSION =
  "ae_web_artifact_library_panel_renderer.v1";

const PANEL_STATUSES = [
  "READY",
  "RUNNING",
  "EMPTY",
  "UNAVAILABLE"
];
const FILTER_MODES = [
  "all",
  "ready",
  "failed",
  "downloadable",
  "previewable"
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

export class ArtifactLibraryPanelError extends Error {
  constructor(message, { status = "ARTIFACT_LIBRARY_PANEL_INVALID" } = {}) {
    super(message);
    this.name = "ArtifactLibraryPanelError";
    this.status = status;
  }
}

export function createArtifactLibraryPanelState({
  status = "READY",
  route = null,
  query = {},
  filterMode = "all",
  items = [],
  errorStatus = null,
  retryable = false,
  clientMode = "mock"
} = {}) {
  const normalizedItems = normalizeItems(items);
  const state = {
    artifact_library_panel_schema_version:
      AE_WEB_ARTIFACT_LIBRARY_PANEL_SCHEMA_VERSION,
    status: normalizePanelStatus(status),
    route: route == null ? null : normalizeRoute(route),
    query: normalizeQuery(query),
    filterMode: normalizeFilterMode(filterMode),
    items: normalizedItems,
    itemCount: normalizedItems.length,
    readyCount: normalizedItems.filter(item => item.artifactStatus === "READY").length,
    failedCount: normalizedItems.filter(item => item.artifactStatus === "FAILED").length,
    downloadableCount: normalizedItems.filter(item => item.downloadReady).length,
    previewableCount: normalizedItems.filter(item => item.previewReady).length,
    clientMode: normalizeOptionalText(clientMode) || "mock",
    errorStatus: normalizeOptionalText(errorStatus),
    retryable: Boolean(retryable),
    metadata: safePanelMetadata()
  };
  assertArtifactLibraryPanelSafe(state);
  return state;
}

export function createRunningArtifactLibraryPanelState({
  route = null,
  query = {},
  clientMode = "mock"
} = {}) {
  return createArtifactLibraryPanelState({
    status: "RUNNING",
    route,
    query,
    clientMode
  });
}

export function buildArtifactLibraryPanelState(collectionSurface) {
  const collection = requiredCollectionSurface(collectionSurface);
  const collectionSummary = buildArtifactCollectionSummary(collection);
  const items = collection.items.map(buildLibraryItem);
  return createArtifactLibraryPanelState({
    status: items.length > 0 ? "READY" : "EMPTY",
    route: collection.route,
    query: collectionSummary.filter,
    items,
    clientMode: collection.clientMode
  });
}

export function buildArtifactLibraryPanelStateFromError(
  error,
  { route = null, query = {}, clientMode = "mock" } = {}
) {
  return createArtifactLibraryPanelState({
    status: "UNAVAILABLE",
    route,
    query,
    errorStatus: error?.status || "ARTIFACT_LIBRARY_PANEL_ERROR",
    retryable: Boolean(error?.retryable),
    clientMode
  });
}

export function filterArtifactLibraryPanelState(state, filterMode = "all") {
  const current = assertArtifactLibraryPanelState(state);
  const normalizedFilter = normalizeFilterMode(filterMode);
  const items = current.items.filter(item => itemMatchesFilter(item, normalizedFilter));
  return createArtifactLibraryPanelState({
    status:
      current.status === "UNAVAILABLE" || current.status === "RUNNING"
        ? current.status
        : items.length > 0
          ? "READY"
          : "EMPTY",
    route: current.route,
    query: current.query,
    filterMode: normalizedFilter,
    items,
    errorStatus: current.errorStatus,
    retryable: current.retryable,
    clientMode: current.clientMode
  });
}

export function buildArtifactLibraryPanelSummary(state) {
  const current = assertArtifactLibraryPanelState(state);
  const formats = uniqueTexts(current.items.flatMap(item => item.availableFormats));
  const statusCounts = {};
  for (const item of current.items) {
    statusCounts[item.artifactStatus] = (statusCounts[item.artifactStatus] || 0) + 1;
  }
  const summary = {
    artifact_library_panel_schema_version:
      current.artifact_library_panel_schema_version,
    status: current.status,
    route_present: Boolean(current.route),
    filter_mode: current.filterMode,
    item_count: current.itemCount,
    ready_count: current.readyCount,
    failed_count: current.failedCount,
    downloadable_count: current.downloadableCount,
    previewable_count: current.previewableCount,
    format_count: formats.length,
    formats,
    status_counts: statusCounts,
    query: current.query,
    client_mode: current.clientMode,
    error_status: current.errorStatus,
    retryable: current.retryable,
    metadata: current.metadata
  };
  assertArtifactLibraryPanelSafe(summary);
  return summary;
}

export function renderArtifactLibraryPanel(state) {
  const current = assertArtifactLibraryPanelState(state);
  const summary = buildArtifactLibraryPanelSummary(current);
  const feedback = panelFeedback(summary);
  const view = {
    artifact_library_panel_renderer_schema_version:
      AE_WEB_ARTIFACT_LIBRARY_PANEL_RENDERER_SCHEMA_VERSION,
    status: summary.status,
    severity: feedback.severity,
    feedback: feedback.message,
    summaryHtml: renderSummary(summary),
    listHtml: renderItemList(current),
    metadata: {
      htmlEscaped: true,
      contentRendered: false,
      storageLocationRendered: false
    }
  };
  assertArtifactLibraryPanelSafe(view);
  return view;
}

export function assertArtifactLibraryPanelSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactLibraryPanelKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactLibraryPanelError(
      "Artifact library panel contains sensitive keys.",
      { status: "ARTIFACT_LIBRARY_PANEL_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactLibraryPanelError(
      "Artifact library panel contains sensitive values.",
      { status: "ARTIFACT_LIBRARY_PANEL_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactLibraryPanelKeys(payload) {
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

function requiredCollectionSurface(value) {
  if (
    !isObject(value) ||
    value.artifact_collection_surface_schema_version !==
      AE_WEB_ARTIFACT_COLLECTION_SURFACE_SCHEMA_VERSION ||
    !Array.isArray(value.items)
  ) {
    throw new ArtifactLibraryPanelError("Artifact collection surface is invalid.", {
      status: "ARTIFACT_COLLECTION_SURFACE_INVALID"
    });
  }
  return value;
}

function buildLibraryItem(item) {
  if (!isObject(item)) {
    throw new ArtifactLibraryPanelError("Artifact library item is invalid.", {
      status: "ARTIFACT_LIBRARY_ITEM_INVALID"
    });
  }
  const availableFormats = uniqueTexts(item.availableFormats || []);
  const downloadableFormats = uniqueTexts(item.downloadableFormats || []);
  const previewableFormats = uniqueTexts(item.previewableFormats || []);
  const libraryItem = {
    artifactId: requiredText(item.artifactId, "ARTIFACT_LIBRARY_ARTIFACT_ID_INVALID"),
    displayTitle: normalizeOptionalText(item.displayTitle) || "Untitled artifact",
    artifactStatus: normalizeOptionalText(item.artifactStatus) || "UNKNOWN",
    artifactType: normalizeOptionalText(item.artifactType) || "generated_document",
    artifactIntent: normalizeOptionalText(item.artifactIntent),
    primaryFormat:
      normalizeOptionalText(item.primaryFormat) ||
      firstText(downloadableFormats) ||
      firstText(previewableFormats) ||
      firstText(availableFormats) ||
      "UNKNOWN",
    availableFormats,
    downloadableFormats,
    previewableFormats,
    downloadReady: downloadableFormats.length > 0,
    previewReady: previewableFormats.length > 0,
    versionCount: numberOrZero(item.versionCount),
    fileCount: numberOrZero(item.fileCount),
    linkCount: numberOrZero(item.linkCount),
    renderJobCount: numberOrZero(item.renderJobCount),
    currentVersionId: normalizeOptionalText(item.currentVersionId),
    currentVersionNo: numberOrNull(item.currentVersionNo),
    latestRenderJobStatus: normalizeOptionalText(
      item.latestRenderJobStatus || item.latestRenderJob?.jobStatus
    ),
    sourceGenerationId: normalizeOptionalText(
      item.sourceGenerationId || item.sourceSummary?.cxGenerationId
    ),
    citationStatus:
      normalizeOptionalText(item.citationStatus || item.qualitySummary?.citationStatus) ||
      "UNKNOWN",
    citationCount: numberOrZero(
      item.citationCount ?? item.qualitySummary?.citationCount
    ),
    evidenceRefCount: numberOrZero(
      item.evidenceRefCount ??
        item.qualitySummary?.evidenceRefCount ??
        item.sourceSummary?.evidenceRefCount
    ),
    ownerScope: normalizeOwnerScope(item.ownerScope),
    chatDocumentId: normalizeOptionalText(item.chatDocumentId),
    interactionId: normalizeOptionalText(item.interactionId),
    detailRoute: normalizeRoute(item.detailRoute || item.routes?.detail),
    versionsRoute: normalizeRoute(item.versionsRoute || item.routes?.versions),
    updatedAt: normalizeOptionalText(item.updatedAt),
    createdAt: normalizeOptionalText(item.createdAt)
  };
  assertArtifactLibraryPanelSafe(libraryItem);
  return libraryItem;
}

function normalizeItems(items) {
  if (!Array.isArray(items)) {
    throw new ArtifactLibraryPanelError("Artifact library items must be an array.", {
      status: "ARTIFACT_LIBRARY_ITEMS_INVALID"
    });
  }
  return items.map(buildLibraryItem);
}

function normalizeOwnerScope(scope) {
  const ownerScope = isObject(scope) ? scope : {};
  return {
    tenantId: normalizeOptionalText(ownerScope.tenantId),
    workspaceId: normalizeOptionalText(ownerScope.workspaceId),
    ownerUserId: normalizeOptionalText(ownerScope.ownerUserId)
  };
}

function normalizeQuery(query) {
  const rawQuery = isObject(query) ? query : {};
  return {
    tenantId: normalizeOptionalText(rawQuery.tenantId || rawQuery.tenant_id),
    workspaceId: normalizeOptionalText(rawQuery.workspaceId || rawQuery.workspace_id),
    ownerUserId: normalizeOptionalText(rawQuery.ownerUserId || rawQuery.owner_user_id),
    artifactStatus: normalizeOptionalText(rawQuery.artifactStatus || rawQuery.status),
    limit: numberOrNull(rawQuery.limit)
  };
}

function assertArtifactLibraryPanelState(value) {
  if (
    !isObject(value) ||
    value.artifact_library_panel_schema_version !==
      AE_WEB_ARTIFACT_LIBRARY_PANEL_SCHEMA_VERSION
  ) {
    throw new ArtifactLibraryPanelError("Artifact library panel state is invalid.", {
      status: "ARTIFACT_LIBRARY_PANEL_SCHEMA_INVALID"
    });
  }
  return createArtifactLibraryPanelState(value);
}

function itemMatchesFilter(item, filterMode) {
  if (filterMode === "ready") return item.artifactStatus === "READY";
  if (filterMode === "failed") return item.artifactStatus === "FAILED";
  if (filterMode === "downloadable") return item.downloadReady;
  if (filterMode === "previewable") return item.previewReady;
  return true;
}

function panelFeedback(summary) {
  if (summary.status === "RUNNING") {
    return {
      severity: "running",
      message: "Artifact library is loading."
    };
  }
  if (summary.status === "EMPTY") {
    return {
      severity: "pending",
      message: "No artifacts match this library view."
    };
  }
  if (summary.status === "UNAVAILABLE") {
    return {
      severity: "danger",
      message: `Artifact library is unavailable. ${summary.error_status || "ARTIFACT_LIBRARY_PANEL_ERROR"}`
    };
  }
  return {
    severity: "success",
    message: "Artifact library is ready."
  };
}

function renderSummary(summary) {
  return `
    <div>
      <dt>artifacts</dt>
      <dd>${escapeHtml(summary.item_count)}</dd>
    </div>
    <div>
      <dt>ready</dt>
      <dd>${escapeHtml(summary.ready_count)}</dd>
    </div>
    <div>
      <dt>actions</dt>
      <dd>${escapeHtml(`${summary.previewable_count} preview / ${summary.downloadable_count} download`)}</dd>
    </div>
    <div>
      <dt>formats</dt>
      <dd>${escapeHtml(summary.formats.join(", ") || "n/a")}</dd>
    </div>
    <div>
      <dt>filter</dt>
      <dd>${escapeHtml(summary.filter_mode)}</dd>
    </div>
    <div>
      <dt>client</dt>
      <dd>${escapeHtml(summary.client_mode)}</dd>
    </div>
  `;
}

function renderItemList(state) {
  if (state.status === "RUNNING") {
    return `<p class="artifact-library-empty">Loading artifact library.</p>`;
  }
  if (state.status === "UNAVAILABLE") {
    return `<p class="artifact-library-empty">Artifact library request failed.</p>`;
  }
  if (state.items.length === 0) {
    return `<p class="artifact-library-empty">No artifacts.</p>`;
  }
  return `
    <ul class="artifact-library-list" aria-label="Artifact library">
      ${state.items.map(renderLibraryItem).join("")}
    </ul>
  `;
}

function renderLibraryItem(item) {
  return `
    <li
      data-artifact-library-item="${escapeAttribute(item.artifactId)}"
      data-artifact-status="${escapeAttribute(item.artifactStatus)}"
    >
      <div class="artifact-library-row">
        <strong>${escapeHtml(item.displayTitle)}</strong>
        <span>${escapeHtml(item.artifactStatus)}</span>
      </div>
      <dl class="inline-meta slim">
        <div>
          <dt>format</dt>
          <dd>${escapeHtml(item.primaryFormat)}</dd>
        </div>
        <div>
          <dt>versions</dt>
          <dd>${escapeHtml(item.versionCount)}</dd>
        </div>
        <div>
          <dt>citations</dt>
          <dd>${escapeHtml(`${item.citationStatus} · ${item.evidenceRefCount}`)}</dd>
        </div>
        <div>
          <dt>updated</dt>
          <dd>${escapeHtml(item.updatedAt || "pending")}</dd>
        </div>
      </dl>
      <div class="artifact-library-actions">
        ${renderRouteAction("Detail", item.detailRoute, "detail")}
        ${renderRouteAction("Versions", item.versionsRoute, "versions")}
      </div>
    </li>
  `;
}

function renderRouteAction(label, route, action) {
  if (!route) {
    return `<button type="button" data-artifact-library-action="${escapeAttribute(action)}" disabled>${escapeHtml(label)}</button>`;
  }
  return `
    <a
      href="${escapeAttribute(route)}"
      data-artifact-library-action="${escapeAttribute(action)}"
      data-artifact-library-route="${escapeAttribute(route)}"
    >${escapeHtml(label)}</a>
  `;
}

function normalizePanelStatus(status) {
  if (!PANEL_STATUSES.includes(status)) {
    throw new ArtifactLibraryPanelError("Artifact library status is unsupported.", {
      status: "ARTIFACT_LIBRARY_STATUS_UNSUPPORTED"
    });
  }
  return status;
}

function normalizeFilterMode(filterMode) {
  const normalized = normalizeOptionalText(filterMode) || "all";
  if (!FILTER_MODES.includes(normalized)) {
    throw new ArtifactLibraryPanelError("Artifact library filter is unsupported.", {
      status: "ARTIFACT_LIBRARY_FILTER_UNSUPPORTED"
    });
  }
  return normalized;
}

function normalizeRoute(route) {
  const value = normalizeOptionalText(route);
  if (!value) return null;
  if (!value.startsWith("/api/v1/")) {
    throw new ArtifactLibraryPanelError("Artifact library route is invalid.", {
      status: "ARTIFACT_LIBRARY_ROUTE_INVALID"
    });
  }
  return value;
}

function numberOrZero(value) {
  if (value == null || value === "") return 0;
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue) || numberValue < 0) {
    throw new ArtifactLibraryPanelError("Artifact library number is invalid.", {
      status: "ARTIFACT_LIBRARY_NUMBER_INVALID"
    });
  }
  return numberValue;
}

function numberOrNull(value) {
  if (value == null || value === "") return null;
  return numberOrZero(value);
}

function requiredText(value, status) {
  const text = normalizeOptionalText(value);
  if (!text) {
    throw new ArtifactLibraryPanelError("Artifact library field is required.", {
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

function firstText(values) {
  if (!Array.isArray(values)) return null;
  return values.find(value => normalizeOptionalText(value)) || null;
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
    rawPromptRendered: false,
    rawSourceRendered: false,
    storageLocationRendered: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false
  };
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
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

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
