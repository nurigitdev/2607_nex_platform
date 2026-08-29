import {
  AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION,
  buildArtifactClientSummary
} from "./artifactClient.js";

export const AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION =
  "ae_web_artifact_card_read_model.v1";
export const AE_WEB_ARTIFACT_CARD_COLLECTION_SCHEMA_VERSION =
  "ae_web_artifact_card_collection.v1";

const READY_STATUSES = new Set(["READY", "COMPLETED"]);
const FAILED_STATUSES = new Set(["FAILED", "ERROR"]);

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

export class ArtifactCardReadModelError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_CARD_READ_MODEL_INVALID" } = {}
  ) {
    super(message);
    this.name = "ArtifactCardReadModelError";
    this.status = status;
  }
}

export function buildArtifactCardViewModel(
  artifactRef,
  { artifactSurface = null } = {}
) {
  const normalized = normalizeArtifactCardSource(artifactRef, artifactSurface);
  const previewAction = buildPreviewAction(normalized);
  const downloadActions = buildDownloadActions(normalized);
  const secondaryActions = buildSecondaryActions(normalized);
  const warnings = buildWarnings(normalized, previewAction, downloadActions);
  const viewModel = {
    artifact_card_schema_version:
      AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION,
    artifact_client_schema_version: normalized.artifactClientSchemaVersion,
    artifactId: normalized.artifactId,
    artifactVersionId: normalized.artifactVersionId,
    displayTitle: normalized.displayTitle,
    artifactType: normalized.artifactType,
    artifactStatus: normalized.artifactStatus,
    primaryFormat: normalized.primaryFormat,
    availableFormats: normalized.availableFormats,
    sourceGenerationId: normalized.sourceGenerationId,
    sourceContentHash: normalized.sourceContentHash,
    qualitySummary: normalized.qualitySummary,
    previewAction,
    downloadActions,
    secondaryActions,
    warningStatus: warnings.length > 0 ? "WARNING" : "CLEAR",
    warnings,
    clientMode: normalized.clientMode,
    route: normalized.route,
    metadata: {
      rawPromptRendered: false,
      rawSourceRendered: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false,
      storageLocationRendered: false,
      contentRendered: false
    }
  };
  assertArtifactCardReadModelSafe(viewModel);
  return viewModel;
}

export function buildArtifactCardCollectionReadModel(
  artifactRefs,
  { artifactSurfaces = [] } = {}
) {
  if (!Array.isArray(artifactRefs)) {
    throw new ArtifactCardReadModelError("Artifact refs must be an array.", {
      status: "ARTIFACT_REFS_INVALID"
    });
  }
  const surfacesByArtifactId = new Map(
    artifactSurfaces
      .filter(isObject)
      .map(surface => [surface.artifactId || surface.artifact_id, surface])
      .filter(([artifactId]) => optionalText(artifactId))
  );
  const items = artifactRefs.map(ref =>
    buildArtifactCardViewModel(ref, {
      artifactSurface:
        surfacesByArtifactId.get(ref.artifactId || ref.artifact_id) || null
    })
  );
  const collection = {
    artifact_card_collection_schema_version:
      AE_WEB_ARTIFACT_CARD_COLLECTION_SCHEMA_VERSION,
    items,
    itemCount: items.length,
    readyCount: items.filter(item => READY_STATUSES.has(item.artifactStatus)).length,
    failedCount: items.filter(item => FAILED_STATUSES.has(item.artifactStatus)).length,
    actionableCount: items.filter(
      item =>
        item.previewAction.enabled ||
        item.downloadActions.some(action => action.enabled) ||
        item.secondaryActions.some(action => action.enabled)
    ).length,
    metadata: {
      rawPromptRendered: false,
      rawSourceRendered: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false,
      storageLocationRendered: false,
      contentRendered: false
    }
  };
  assertArtifactCardReadModelSafe(collection);
  return collection;
}

export function buildArtifactCardReadModelSummary(source) {
  const viewModel =
    source?.artifact_card_schema_version ===
    AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION
      ? source
      : buildArtifactCardViewModel(source);
  const summary = {
    artifact_card_schema_version: viewModel.artifact_card_schema_version,
    artifact_id: viewModel.artifactId,
    artifact_version_id: viewModel.artifactVersionId,
    artifact_status: viewModel.artifactStatus,
    primary_format: viewModel.primaryFormat,
    preview_enabled: viewModel.previewAction.enabled,
    download_action_count: viewModel.downloadActions.length,
    enabled_download_action_count: viewModel.downloadActions.filter(
      action => action.enabled
    ).length,
    secondary_action_count: viewModel.secondaryActions.length,
    warning_count: viewModel.warnings.length,
    warning_status: viewModel.warningStatus,
    client_mode: viewModel.clientMode,
    metadata: viewModel.metadata
  };
  assertArtifactCardReadModelSafe(summary);
  return summary;
}

export function buildArtifactCardCollectionSummary(collection) {
  if (
    !isObject(collection) ||
    collection.artifact_card_collection_schema_version !==
      AE_WEB_ARTIFACT_CARD_COLLECTION_SCHEMA_VERSION
  ) {
    throw new ArtifactCardReadModelError("Artifact card collection is invalid.", {
      status: "ARTIFACT_CARD_COLLECTION_INVALID"
    });
  }
  const summary = {
    artifact_card_collection_schema_version:
      collection.artifact_card_collection_schema_version,
    item_count: collection.itemCount,
    ready_count: collection.readyCount,
    failed_count: collection.failedCount,
    actionable_count: collection.actionableCount,
    warning_count: collection.items.reduce(
      (total, item) => total + item.warnings.length,
      0
    ),
    metadata: collection.metadata
  };
  assertArtifactCardReadModelSafe(summary);
  return summary;
}

export function assertArtifactCardReadModelSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactCardReadModelKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactCardReadModelError(
      "Artifact card read model contains sensitive keys.",
      { status: "ARTIFACT_CARD_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactCardReadModelError(
      "Artifact card read model contains sensitive values.",
      { status: "ARTIFACT_CARD_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactCardReadModelKeys(payload) {
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

function normalizeArtifactCardSource(artifactRef, artifactSurface) {
  if (!isObject(artifactRef) && !isObject(artifactSurface)) {
    throw new ArtifactCardReadModelError("Artifact ref is invalid.", {
      status: "ARTIFACT_REF_INVALID"
    });
  }
  const ref = isObject(artifactRef) ? artifactRef : {};
  const surface = isObject(artifactSurface) ? artifactSurface : {};
  const clientSummary =
    surface.artifact_client_schema_version === AE_WEB_ARTIFACT_CLIENT_SCHEMA_VERSION
      ? buildArtifactClientSummary(surface)
      : null;
  const artifactId = firstText(surface.artifactId, ref.artifactId, ref.artifact_id);
  const artifactVersionId = firstText(
    surface.artifactVersionId,
    ref.artifactVersionId,
    ref.artifact_version_id
  );
  const downloadRoutes = normalizeDownloadRoutes(
    firstObject(surface.downloadRoutes, ref.downloadRoutes, ref.download_routes)
  );
  const availableFormats = normalizeFormats(
    firstArray(surface.availableFormats, ref.availableFormats, ref.available_formats),
    downloadRoutes
  );
  const artifactStatus = normalizeStatus(
    firstText(surface.artifactStatus, ref.artifactStatus, ref.artifact_status)
  );
  return {
    artifactClientSchemaVersion:
      surface.artifact_client_schema_version || ref.artifact_client_schema_version || null,
    artifactId: requiredText(artifactId, "artifact_id"),
    artifactVersionId: artifactVersionId || null,
    displayTitle:
      firstText(surface.displayTitle, ref.displayTitle, ref.display_title) ||
      "Untitled artifact",
    artifactType:
      firstText(surface.artifactType, ref.artifactType, ref.artifact_type) ||
      "generated_document",
    artifactStatus,
    primaryFormat:
      firstText(surface.primaryFormat, ref.primaryFormat, ref.primary_format) ||
      availableFormats[0] ||
      "UNKNOWN",
    availableFormats,
    sourceGenerationId:
      firstText(surface.sourceGenerationId, ref.sourceGenerationId, ref.source_generation_id) ||
      null,
    sourceContentHash:
      firstText(surface.sourceContentHash, ref.sourceContentHash, ref.source_content_hash) ||
      null,
    previewRoute: optionalRoute(
      firstText(surface.previewRoute, ref.previewRoute, ref.preview_route)
    ),
    downloadRoutes,
    actions: normalizeActions(firstArray(surface.actions, ref.actions)),
    clientMode: surface.clientMode || ref.clientMode || ref.client_mode || "mock",
    route: surface.route || ref.route || null,
    qualitySummary: normalizeQualitySummary(
      firstObject(surface.qualitySummary, ref.qualitySummary, ref.quality_summary)
    ),
    clientSummary
  };
}

function buildPreviewAction(source) {
  const enabled = READY_STATUSES.has(source.artifactStatus) && Boolean(source.previewRoute);
  return {
    action: "preview",
    label: "Preview",
    route: source.previewRoute,
    enabled,
    reason: enabled
      ? "ready"
      : !source.previewRoute
        ? "missing_preview_route"
        : "artifact_not_ready"
  };
}

function buildDownloadActions(source) {
  return Object.entries(source.downloadRoutes).map(([format, route]) => {
    const enabled = READY_STATUSES.has(source.artifactStatus) && Boolean(route);
    return {
      action: `download_${format.toLowerCase()}`,
      label: format,
      format,
      route,
      enabled,
      reason: enabled ? "ready" : "artifact_not_ready"
    };
  });
}

function buildSecondaryActions(source) {
  const actions = new Set(source.actions);
  const secondary = [];
  if (source.sourceGenerationId || actions.has("view_sources")) {
    secondary.push({
      action: "view_sources",
      label: "Sources",
      enabled: Boolean(source.sourceGenerationId),
      reason: source.sourceGenerationId ? "ready" : "missing_source_generation"
    });
  }
  if (source.sourceGenerationId || actions.has("view_lineage")) {
    secondary.push({
      action: "view_lineage",
      label: "Lineage",
      enabled: Boolean(source.sourceGenerationId),
      reason: source.sourceGenerationId ? "ready" : "missing_source_generation"
    });
  }
  if (FAILED_STATUSES.has(source.artifactStatus) || actions.has("retry_render")) {
    secondary.push({
      action: "retry_render",
      label: "Retry",
      enabled: FAILED_STATUSES.has(source.artifactStatus),
      reason: FAILED_STATUSES.has(source.artifactStatus)
        ? "failed_artifact"
        : "artifact_not_failed"
    });
  }
  return secondary;
}

function buildWarnings(source, previewAction, downloadActions) {
  const warnings = [];
  if (!source.artifactVersionId) {
    warnings.push({
      kind: "missing_version",
      severity: "warning",
      message: "Artifact version is not ready."
    });
  }
  if (!previewAction.enabled) {
    warnings.push({
      kind: previewAction.reason,
      severity: previewAction.reason === "artifact_not_ready" ? "info" : "warning",
      message: "Artifact preview action is not available."
    });
  }
  if (downloadActions.length === 0) {
    warnings.push({
      kind: "missing_download_route",
      severity: "warning",
      message: "Artifact download action is not available."
    });
  }
  if (FAILED_STATUSES.has(source.artifactStatus)) {
    warnings.push({
      kind: "artifact_failed",
      severity: "danger",
      message: "Artifact rendering failed."
    });
  }
  return warnings;
}

function normalizeQualitySummary(value) {
  const summary = isObject(value) ? value : {};
  return {
    citationStatus:
      firstText(summary.citationStatus, summary.citation_status) || "UNKNOWN",
    citationCount: numberOrZero(summary.citationCount ?? summary.citation_count),
    evidenceRefCount: numberOrZero(
      summary.evidenceRefCount ?? summary.evidence_ref_count
    ),
    groundingRequired: Boolean(
      summary.groundingRequired ?? summary.grounding_required
    ),
    retrievalPackageId:
      firstText(summary.retrievalPackageId, summary.retrieval_package_id) || null
  };
}

function normalizeDownloadRoutes(value) {
  if (!isObject(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .map(([format, route]) => [String(format).toUpperCase(), optionalRoute(route)])
      .filter(([, route]) => route)
  );
}

function normalizeFormats(values, downloadRoutes) {
  const formats = Array.isArray(values) ? values.map(format => String(format)) : [];
  if (formats.length === 0) {
    formats.push(...Object.keys(downloadRoutes));
  }
  return [...new Set(formats.filter(format => format.trim().length > 0))];
}

function normalizeActions(values) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map(value => String(value)).filter(Boolean))];
}

function normalizeStatus(value) {
  const status = optionalText(value);
  return status ? status.toUpperCase() : "UNKNOWN";
}

function requiredText(value, fieldName) {
  const text = optionalText(value);
  if (!text) {
    throw new ArtifactCardReadModelError(`${fieldName} is required.`, {
      status: "ARTIFACT_CARD_FIELD_REQUIRED"
    });
  }
  return text;
}

function optionalRoute(value) {
  const route = optionalText(value);
  if (!route) return null;
  if (!route.startsWith("/api/v1/")) {
    throw new ArtifactCardReadModelError("Artifact route is not browser safe.", {
      status: "ARTIFACT_CARD_ROUTE_UNSAFE"
    });
  }
  return route;
}

function firstText(...values) {
  for (const value of values) {
    const text = optionalText(value);
    if (text) return text;
  }
  return null;
}

function firstObject(...values) {
  return values.find(isObject) || {};
}

function firstArray(...values) {
  return values.find(Array.isArray) || [];
}

function optionalText(value) {
  if (value == null) return null;
  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : null;
}

function numberOrZero(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
