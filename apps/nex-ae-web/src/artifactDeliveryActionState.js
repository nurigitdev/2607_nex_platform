import {
  artifactFileIdFromRoute,
  buildArtifactPreviewPanelStateFromDownload,
  buildArtifactPreviewPanelStateFromError,
  buildArtifactPreviewPanelStateFromPreview,
  buildArtifactPreviewPanelSummary,
  createRunningArtifactPreviewPanelState
} from "./artifactPreviewPanel.js";
import {
  buildArtifactDownloadSaveSummary,
  saveArtifactDownload
} from "./artifactDownloadSaveAdapter.js";
import {
  buildOperationStateSummary,
  markOperationFailed,
  markOperationRunning,
  markOperationSucceeded
} from "./operationState.js";

export const AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION =
  "ae_web_artifact_delivery_action_state.v1";

const ACTIONS = ["preview", "download"];
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
  /nuri1004/i
];

export class ArtifactDeliveryActionStateError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_DELIVERY_ACTION_STATE_INVALID" } = {}
  ) {
    super(message);
    this.name = "ArtifactDeliveryActionStateError";
    this.status = status;
  }
}

export function createArtifactDeliveryActionContext({
  action,
  artifactId = null,
  artifactFileId = null,
  route,
  clientMode = "mock"
} = {}) {
  const normalizedAction = normalizeAction(action);
  const normalizedRoute = normalizeRequiredText(
    route,
    "ARTIFACT_DELIVERY_ROUTE_MISSING"
  );
  const routeFileId = artifactFileIdFromRoute(normalizedRoute, normalizedAction);
  const context = {
    artifact_delivery_action_state_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
    action: normalizedAction,
    artifactId: normalizeOptionalText(artifactId),
    artifactFileId: normalizeOptionalText(artifactFileId) || routeFileId,
    route: normalizedRoute,
    clientMode: normalizeOptionalText(clientMode) || "mock",
    metadata: safeActionMetadata()
  };
  assertArtifactDeliveryActionStateSafe(context);
  return context;
}

export function buildArtifactDeliveryActionRunningState(operationState, context) {
  const currentContext = assertActionContext(context);
  const state = {
    artifact_delivery_action_state_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
    status: "RUNNING",
    context: currentContext,
    operation: markOperationRunning(operationState, {
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    panel: createRunningArtifactPreviewPanelState(currentContext),
    metadata: safeActionMetadata()
  };
  assertArtifactDeliveryActionStateSafe(state);
  return state;
}

export function buildArtifactDeliveryPreviewSuccess(
  operationState,
  previewSurface,
  context
) {
  const currentContext = assertActionContext(context, "preview");
  const panel = buildArtifactPreviewPanelStateFromPreview(
    previewSurface,
    currentContext
  );
  const state = {
    artifact_delivery_action_state_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
    status: "PREVIEW_READY",
    context: currentContext,
    operation: markOperationSucceeded(operationState, {
      status: "PREVIEW_READY",
      resultStatus: "PREVIEW_READY",
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    panel,
    metadata: safeActionMetadata()
  };
  assertArtifactDeliveryActionStateSafe(state);
  return state;
}

export function buildArtifactDeliveryDownloadSuccess(
  operationState,
  downloadSurface,
  context,
  { saveDownload = saveArtifactDownload } = {}
) {
  const currentContext = assertActionContext(context, "download");
  const panel = buildArtifactPreviewPanelStateFromDownload(
    downloadSurface,
    currentContext
  );
  const downloadSaveResult = saveDownload(downloadSurface);
  const downloadSaveSummary = buildArtifactDownloadSaveSummary(downloadSaveResult);
  const state = {
    artifact_delivery_action_state_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
    status: "DOWNLOAD_READY",
    context: currentContext,
    operation: markOperationSucceeded(operationState, {
      status: "DOWNLOAD_READY",
      resultStatus: downloadSaveSummary.status || "READY",
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    panel,
    downloadSaveResult,
    downloadSaveSummary,
    metadata: safeActionMetadata()
  };
  assertArtifactDeliveryActionStateSafe(state);
  return state;
}

export function buildArtifactDeliveryFailure(
  operationState,
  error,
  context,
  { fallbackRoute = null } = {}
) {
  const currentContext = normalizeFailureContext(context, { fallbackRoute });
  const state = {
    artifact_delivery_action_state_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
    status: "UNAVAILABLE",
    context: currentContext,
    operation: markOperationFailed(operationState, {
      error,
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    panel: buildArtifactPreviewPanelStateFromError(error, currentContext),
    ...(currentContext.action === "download" ? { downloadSaveResult: null } : {}),
    metadata: safeActionMetadata()
  };
  assertArtifactDeliveryActionStateSafe(state);
  return state;
}

export function buildArtifactDeliveryActionSummary(state) {
  if (
    !isObject(state) ||
    state.artifact_delivery_action_state_schema_version !==
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION
  ) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action state is invalid.",
      { status: "ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_INVALID" }
    );
  }
  const operation = buildOperationStateSummary(state.operation);
  const panel = buildArtifactPreviewPanelSummary(state.panel);
  const summary = {
    artifact_delivery_action_state_schema_version:
      state.artifact_delivery_action_state_schema_version,
    status: normalizeRequiredText(state.status, "ARTIFACT_DELIVERY_STATUS_MISSING"),
    action: panel.action,
    phase: operation.phase,
    operation_status: operation.status,
    result_status: operation.result_status,
    error_status: operation.error_status || panel.error_status,
    retryable: operation.retryable || panel.retryable,
    artifact_id: panel.artifact_id,
    artifact_file_id: panel.artifact_file_id,
    route: panel.route,
    client_mode: operation.client_mode,
    download_save_status: state.downloadSaveSummary?.status || null,
    metadata: safeActionMetadata()
  };
  assertArtifactDeliveryActionStateSafe(summary);
  return summary;
}

export function assertArtifactDeliveryActionStateSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactDeliveryActionKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action state contains sensitive keys.",
      { status: "ARTIFACT_DELIVERY_ACTION_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action state contains sensitive values.",
      { status: "ARTIFACT_DELIVERY_ACTION_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactDeliveryActionKeys(payload) {
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

function assertActionContext(context, expectedAction = null) {
  if (
    !isObject(context) ||
    context.artifact_delivery_action_state_schema_version !==
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION
  ) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action context is invalid.",
      { status: "ARTIFACT_DELIVERY_ACTION_CONTEXT_INVALID" }
    );
  }
  const normalized = createArtifactDeliveryActionContext(context);
  if (expectedAction && normalized.action !== expectedAction) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action context action does not match.",
      { status: "ARTIFACT_DELIVERY_ACTION_MISMATCH" }
    );
  }
  return normalized;
}

function normalizeFailureContext(context, { fallbackRoute = null } = {}) {
  if (isObject(context) && context.route) {
    return createArtifactDeliveryActionContext({
      ...context,
      action: ACTIONS.includes(context.action) ? context.action : "preview"
    });
  }
  const safeRoute =
    normalizeOptionalText(context?.route) ||
    normalizeOptionalText(fallbackRoute) ||
    "/api/v1/artifact-files/unavailable/preview";
  return {
    artifact_delivery_action_state_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
    action: ACTIONS.includes(context?.action) ? context.action : "preview",
    artifactId: normalizeOptionalText(context?.artifactId),
    artifactFileId: normalizeOptionalText(context?.artifactFileId),
    route: safeRoute,
    clientMode: normalizeOptionalText(context?.clientMode) || "mock",
    metadata: safeActionMetadata()
  };
}

function safeActionMetadata() {
  return {
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    rawDownloadContentIncluded: false,
    rawBase64PayloadIncluded: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    storageLocationIncluded: false
  };
}

function normalizeAction(value) {
  const normalized = normalizeRequiredText(
    value,
    "ARTIFACT_DELIVERY_ACTION_MISSING"
  );
  if (!ACTIONS.includes(normalized)) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action is unsupported.",
      { status: "ARTIFACT_DELIVERY_ACTION_UNSUPPORTED" }
    );
  }
  return normalized;
}

function normalizeRequiredText(value, status) {
  const text = normalizeOptionalText(value);
  if (!text) {
    throw new ArtifactDeliveryActionStateError(
      "Artifact delivery action field is required.",
      { status }
    );
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
