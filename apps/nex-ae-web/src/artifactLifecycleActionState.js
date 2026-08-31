import {
  artifactLifecycleActionRoute,
  buildArtifactLifecycleActionSummary
} from "./artifactClient.js";
import {
  buildOperationStateSummary,
  markOperationFailed,
  markOperationRunning,
  markOperationSucceeded
} from "./operationState.js";

export const AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SET_SCHEMA_VERSION =
  "ae_web_artifact_lifecycle_action_set.v1";
export const AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION =
  "ae_web_artifact_lifecycle_action_state.v1";

const LIFECYCLE_ACTIONS = ["ARCHIVE", "RESTORE", "MARK_DELETED"];
const RESTORE_TARGETS = ["DRAFT", "READY", "FAILED"];
const ARTIFACT_STATUSES = [
  "DRAFT",
  "RENDERING",
  "READY",
  "FAILED",
  "ARCHIVED",
  "DELETED"
];
const ACTION_STATE_STATUSES = ["IDLE", "RUNNING", "APPLIED", "UNAVAILABLE"];
const ACTION_LABELS = {
  ARCHIVE: "Archive",
  RESTORE: "Restore",
  MARK_DELETED: "Delete"
};

const SENSITIVE_KEY_PARTS = [
  "api_key",
  "authorization",
  "comment_body",
  "comment_text",
  "credential",
  "database_url",
  "model_path",
  "password",
  "passwd",
  "provider_endpoint",
  "provider_url",
  "raw_prompt",
  "raw_comment",
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
  "rawPromptIncluded",
  "rawSourceIncluded",
  "storageLocationIncluded"
];

const SENSITIVE_VALUE_PATTERNS = [
  /postgresql\+?[^"'\s]+/i,
  /\/data\/nex-platform/i,
  /ed6@c496em/i,
  /nuri1004/i
];

export class ArtifactLifecycleActionStateError extends Error {
  constructor(
    message,
    { status = "ARTIFACT_LIFECYCLE_ACTION_STATE_INVALID" } = {}
  ) {
    super(message);
    this.name = "ArtifactLifecycleActionStateError";
    this.status = status;
  }
}

export function buildArtifactLifecycleActionSet(
  artifact,
  { clientMode = "mock" } = {}
) {
  const artifactId = requiredText(
    artifact?.artifactId ?? artifact?.artifact_id,
    "ARTIFACT_LIFECYCLE_ARTIFACT_ID_REQUIRED"
  );
  const artifactStatus = normalizeArtifactStatus(
    artifact?.artifactStatus ?? artifact?.artifact_status
  );
  const route = artifactLifecycleActionRoute(artifactId);
  const actions = LIFECYCLE_ACTIONS.map(action =>
    buildLifecycleActionOption({ artifactId, artifactStatus, action, route, clientMode })
  );
  const enabledActions = actions.filter(action => action.enabled);
  const set = {
    artifact_lifecycle_action_set_schema_version:
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SET_SCHEMA_VERSION,
    artifactId,
    artifactStatus,
    route,
    clientMode: normalizeClientMode(clientMode),
    actions,
    enabledActionCount: enabledActions.length,
    primaryAction: choosePrimaryAction(enabledActions),
    metadata: safeLifecycleActionMetadata()
  };
  assertArtifactLifecycleActionStateSafe(set);
  return set;
}

export function buildArtifactLifecycleActionSetSummary(actionSet) {
  const current = assertActionSet(actionSet);
  const enabledActions = current.actions
    .filter(action => action.enabled)
    .map(action => action.action);
  const summary = {
    artifact_lifecycle_action_set_schema_version:
      current.artifact_lifecycle_action_set_schema_version,
    artifact_id: current.artifactId,
    artifact_status: current.artifactStatus,
    enabled_action_count: current.enabledActionCount,
    enabled_actions: enabledActions,
    primary_action: current.primaryAction,
    route_present: Boolean(current.route),
    client_mode: current.clientMode,
    metadata: current.metadata
  };
  assertArtifactLifecycleActionStateSafe(summary);
  return summary;
}

export function createArtifactLifecycleActionContext({
  artifactId,
  artifact_id,
  artifactStatus,
  artifact_status,
  action,
  restoreStatus = null,
  restore_status = null,
  route = null,
  clientMode = "mock"
} = {}) {
  const normalizedArtifactId = requiredText(
    artifactId ?? artifact_id,
    "ARTIFACT_LIFECYCLE_ARTIFACT_ID_REQUIRED"
  );
  const normalizedStatus = normalizeArtifactStatus(
    artifactStatus ?? artifact_status
  );
  const normalizedAction = normalizeLifecycleAction(action);
  const restoreStatusProvided =
    restoreStatus != null || restore_status != null;
  const normalizedRestoreStatus = normalizeRestoreStatus(
    restoreStatus ?? restore_status
  );
  if (normalizedAction !== "RESTORE" && restoreStatusProvided) {
    throw new ArtifactLifecycleActionStateError(
      "restoreStatus is only valid for RESTORE lifecycle actions.",
      { status: "ARTIFACT_LIFECYCLE_RESTORE_STATUS_UNSUPPORTED" }
    );
  }
  if (!isLifecycleActionEnabled(normalizedAction, normalizedStatus)) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action is not available for this status.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_UNAVAILABLE" }
    );
  }
  const context = {
    artifact_lifecycle_action_state_schema_version:
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION,
    artifactId: normalizedArtifactId,
    artifactStatus: normalizedStatus,
    action: normalizedAction,
    targetStatus: lifecycleTargetStatus(normalizedAction, normalizedRestoreStatus),
    restoreStatus:
      normalizedAction === "RESTORE"
        ? normalizedRestoreStatus || "READY"
        : null,
    route: normalizeRoute(route || artifactLifecycleActionRoute(normalizedArtifactId)),
    clientMode: normalizeClientMode(clientMode),
    metadata: safeLifecycleActionMetadata()
  };
  assertArtifactLifecycleActionStateSafe(context);
  return context;
}

export function createArtifactLifecycleActionState({
  status = "IDLE",
  actionSet = null,
  context = null,
  operation = null,
  result = null,
  resultSummary = null,
  errorStatus = null,
  retryable = false,
  clientMode = "mock"
} = {}) {
  const normalizedStatus = normalizeActionStateStatus(status);
  const state = {
    artifact_lifecycle_action_state_schema_version:
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION,
    status: normalizedStatus,
    actionSet: actionSet ? assertActionSet(actionSet) : null,
    context: context ? assertActionContext(context) : null,
    operation,
    result,
    resultSummary,
    errorStatus: normalizeOptionalText(errorStatus),
    retryable: Boolean(retryable),
    clientMode: normalizeClientMode(clientMode),
    metadata: safeLifecycleActionMetadata()
  };
  assertArtifactLifecycleActionStateSafe(state);
  return state;
}

export function buildArtifactLifecycleActionRunningState(operationState, context) {
  const currentContext = assertActionContext(context);
  return createArtifactLifecycleActionState({
    status: "RUNNING",
    context: currentContext,
    operation: markOperationRunning(operationState, {
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    clientMode: currentContext.clientMode
  });
}

export function buildArtifactLifecycleActionSuccessState(
  operationState,
  lifecycleSurface,
  context
) {
  const currentContext = assertActionContext(context);
  const resultSummary = buildArtifactLifecycleActionSummary(lifecycleSurface);
  if (
    lifecycleSurface.artifactId !== currentContext.artifactId ||
    lifecycleSurface.action !== currentContext.action
  ) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle result does not match the action context.",
      { status: "ARTIFACT_LIFECYCLE_RESULT_CONTEXT_MISMATCH" }
    );
  }
  return createArtifactLifecycleActionState({
    status: "APPLIED",
    context: currentContext,
    operation: markOperationSucceeded(operationState, {
      status: "APPLIED",
      resultStatus: resultSummary.artifact_status,
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    result: lifecycleSurface,
    resultSummary,
    clientMode: currentContext.clientMode
  });
}

export function buildArtifactLifecycleActionFailureState(
  operationState,
  error,
  context
) {
  const currentContext = assertActionContext(context);
  return createArtifactLifecycleActionState({
    status: "UNAVAILABLE",
    context: currentContext,
    operation: markOperationFailed(operationState, {
      error,
      clientMode: currentContext.clientMode,
      route: currentContext.route
    }),
    errorStatus: error?.status || "ARTIFACT_LIFECYCLE_ACTION_ERROR",
    retryable: Boolean(error?.retryable),
    clientMode: currentContext.clientMode
  });
}

export function buildArtifactLifecycleActionStateSummary(state) {
  const current = assertActionState(state);
  const operation = current.operation
    ? buildOperationStateSummary(current.operation)
    : null;
  const actionSetSummary = current.actionSet
    ? buildArtifactLifecycleActionSetSummary(current.actionSet)
    : null;
  const summary = {
    artifact_lifecycle_action_state_schema_version:
      current.artifact_lifecycle_action_state_schema_version,
    status: current.status,
    artifact_id:
      current.context?.artifactId || actionSetSummary?.artifact_id || null,
    artifact_status:
      current.resultSummary?.artifact_status ||
      current.context?.artifactStatus ||
      actionSetSummary?.artifact_status ||
      null,
    action: current.context?.action || null,
    target_status: current.context?.targetStatus || null,
    restore_status: current.context?.restoreStatus || null,
    enabled_action_count: actionSetSummary?.enabled_action_count || 0,
    primary_action: actionSetSummary?.primary_action || null,
    phase: operation?.phase || null,
    operation_status: operation?.status || null,
    result_status: operation?.result_status || null,
    error_status: current.errorStatus || operation?.error_status || null,
    retryable: current.retryable || Boolean(operation?.retryable),
    route_present: Boolean(current.context?.route || actionSetSummary?.route_present),
    client_mode: current.clientMode,
    transition_applied: Boolean(current.resultSummary?.transition_applied),
    metadata: current.metadata
  };
  assertArtifactLifecycleActionStateSafe(summary);
  return summary;
}

export function assertArtifactLifecycleActionStateSafe(payload) {
  const sensitiveKeys = findSensitiveArtifactLifecycleActionStateKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action state contains sensitive keys.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_STATE_SENSITIVE_KEY" }
    );
  }
  const serialized = JSON.stringify(payload);
  if (SENSITIVE_VALUE_PATTERNS.some(pattern => pattern.test(serialized))) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action state contains sensitive values.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_STATE_SENSITIVE_VALUE" }
    );
  }
}

export function findSensitiveArtifactLifecycleActionStateKeys(payload) {
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

function buildLifecycleActionOption({
  artifactId,
  artifactStatus,
  action,
  route,
  clientMode
}) {
  const enabled = isLifecycleActionEnabled(action, artifactStatus);
  return {
    action,
    label: ACTION_LABELS[action],
    enabled,
    disabledReason: enabled ? null : disabledReasonFor(action, artifactStatus),
    targetStatus: lifecycleTargetStatus(action),
    restoreTargets: action === "RESTORE" ? [...RESTORE_TARGETS] : [],
    artifactId,
    artifactStatus,
    route,
    clientMode: normalizeClientMode(clientMode),
    metadata: safeLifecycleActionMetadata()
  };
}

function assertActionSet(actionSet) {
  if (
    !isObject(actionSet) ||
    actionSet.artifact_lifecycle_action_set_schema_version !==
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SET_SCHEMA_VERSION ||
    !Array.isArray(actionSet.actions)
  ) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action set is invalid.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_SET_INVALID" }
    );
  }
  assertArtifactLifecycleActionStateSafe(actionSet);
  return actionSet;
}

function assertActionContext(context) {
  if (
    !isObject(context) ||
    context.artifact_lifecycle_action_state_schema_version !==
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION
  ) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action context is invalid.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_CONTEXT_INVALID" }
    );
  }
  assertArtifactLifecycleActionStateSafe(context);
  return context;
}

function assertActionState(state) {
  if (
    !isObject(state) ||
    state.artifact_lifecycle_action_state_schema_version !==
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION
  ) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action state is invalid.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_INVALID" }
    );
  }
  assertArtifactLifecycleActionStateSafe(state);
  return state;
}

function isLifecycleActionEnabled(action, artifactStatus) {
  if (action === "ARCHIVE") {
    return ["DRAFT", "READY", "FAILED"].includes(artifactStatus);
  }
  if (action === "RESTORE") {
    return ["ARCHIVED", "DELETED"].includes(artifactStatus);
  }
  if (action === "MARK_DELETED") {
    return ["DRAFT", "READY", "FAILED", "ARCHIVED"].includes(artifactStatus);
  }
  return false;
}

function disabledReasonFor(action, artifactStatus) {
  if (artifactStatus === "RENDERING") return "artifact_rendering";
  if (action === "ARCHIVE" && artifactStatus === "ARCHIVED") {
    return "already_archived";
  }
  if (action === "MARK_DELETED" && artifactStatus === "DELETED") {
    return "already_deleted";
  }
  if (action === "RESTORE" && !["ARCHIVED", "DELETED"].includes(artifactStatus)) {
    return "not_archived_or_deleted";
  }
  return "transition_not_available";
}

function choosePrimaryAction(enabledActions) {
  if (enabledActions.some(action => action.action === "RESTORE")) return "RESTORE";
  if (enabledActions.some(action => action.action === "ARCHIVE")) return "ARCHIVE";
  if (enabledActions.some(action => action.action === "MARK_DELETED")) {
    return "MARK_DELETED";
  }
  return null;
}

function lifecycleTargetStatus(action, restoreStatus = null) {
  const normalizedAction = normalizeLifecycleAction(action);
  const normalizedRestoreStatus = normalizeRestoreStatus(restoreStatus);
  if (normalizedAction === "ARCHIVE") return "ARCHIVED";
  if (normalizedAction === "MARK_DELETED") return "DELETED";
  return normalizedRestoreStatus || "READY";
}

function normalizeLifecycleAction(action) {
  const normalized = requiredText(
    action,
    "ARTIFACT_LIFECYCLE_ACTION_REQUIRED"
  ).toUpperCase();
  if (!LIFECYCLE_ACTIONS.includes(normalized)) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action is unsupported.",
      { status: "ARTIFACT_LIFECYCLE_ACTION_UNSUPPORTED" }
    );
  }
  return normalized;
}

function normalizeRestoreStatus(status) {
  const normalized = normalizeOptionalText(status);
  if (!normalized) return null;
  const upper = normalized.toUpperCase();
  if (!RESTORE_TARGETS.includes(upper)) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle restore status is unsupported.",
      { status: "ARTIFACT_LIFECYCLE_RESTORE_STATUS_UNSUPPORTED" }
    );
  }
  return upper;
}

function normalizeArtifactStatus(status) {
  const normalized = requiredText(
    status,
    "ARTIFACT_LIFECYCLE_ARTIFACT_STATUS_REQUIRED"
  ).toUpperCase();
  if (!ARTIFACT_STATUSES.includes(normalized)) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle status is unsupported.",
      { status: "ARTIFACT_LIFECYCLE_ARTIFACT_STATUS_UNSUPPORTED" }
    );
  }
  return normalized;
}

function normalizeActionStateStatus(status) {
  const normalized = requiredText(
    status,
    "ARTIFACT_LIFECYCLE_STATE_STATUS_REQUIRED"
  ).toUpperCase();
  if (!ACTION_STATE_STATUSES.includes(normalized)) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle state status is unsupported.",
      { status: "ARTIFACT_LIFECYCLE_STATE_STATUS_UNSUPPORTED" }
    );
  }
  return normalized;
}

function normalizeRoute(route) {
  const normalized = requiredText(route, "ARTIFACT_LIFECYCLE_ROUTE_REQUIRED");
  if (!normalized.startsWith("/api/v1/")) {
    throw new ArtifactLifecycleActionStateError(
      "Artifact lifecycle action route is not browser safe.",
      { status: "ARTIFACT_LIFECYCLE_ROUTE_UNSAFE" }
    );
  }
  return normalized;
}

function normalizeClientMode(clientMode) {
  return normalizeOptionalText(clientMode) === "fetch" ? "fetch" : "mock";
}

function safeLifecycleActionMetadata() {
  return {
    contentIncluded: false,
    binaryContentIncluded: false,
    previewTextIncluded: false,
    renderedPayloadIncluded: false,
    storageLocationIncluded: false,
    physicalDeleteRequested: false,
    physicalDeleteExecuted: false,
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    browserServiceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false
  };
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function requiredText(value, status) {
  const normalized = normalizeOptionalText(value);
  if (!normalized) {
    throw new ArtifactLifecycleActionStateError("Artifact lifecycle field is required.", {
      status
    });
  }
  return normalized;
}

function normalizeOptionalText(value) {
  if (value == null) return null;
  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : null;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
