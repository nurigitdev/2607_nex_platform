export const AE_WEB_OPERATION_STATE_SCHEMA_VERSION = "ae_web_operation_state.v1";
export const AE_WEB_OPERATION_PHASES = ["idle", "running", "succeeded", "failed"];

const SAFE_OPERATION_METADATA = {
  browserServiceTokenIncluded: false,
  rawPromptRendered: false,
  rawSourceIncluded: false,
  sourcePreviewIncluded: false,
  providerEndpointIncluded: false,
  databaseEndpointIncluded: false,
  storageLocationIncluded: false
};

export class OperationStateError extends Error {
  constructor(message, { status = "OPERATION_STATE_INVALID" } = {}) {
    super(message);
    this.name = "OperationStateError";
    this.status = status;
  }
}

export function createOperationState({
  operationId,
  phase = "idle",
  status = "READY",
  label = operationId,
  retryable = false,
  attempt = 0,
  clientMode = "mock",
  route = "",
  resultStatus = null,
  errorStatus = null,
  startedAt = null,
  finishedAt = null,
  metadata = {}
} = {}) {
  const normalizedOperationId = normalizeRequiredString(
    operationId,
    "OPERATION_ID_INVALID"
  );
  const normalizedPhase = normalizePhase(phase);
  const normalizedAttempt = normalizeAttempt(attempt);

  return {
    operation_state_schema_version: AE_WEB_OPERATION_STATE_SCHEMA_VERSION,
    operationId: normalizedOperationId,
    label: normalizeOptionalString(label) || normalizedOperationId,
    phase: normalizedPhase,
    status: normalizeOptionalString(status) || "READY",
    retryable: Boolean(retryable),
    attempt: normalizedAttempt,
    clientMode: normalizeOptionalString(clientMode) || "mock",
    route: normalizeOptionalString(route),
    resultStatus: normalizeOptionalString(resultStatus),
    errorStatus: normalizeOptionalString(errorStatus),
    startedAt: normalizeOptionalString(startedAt),
    finishedAt: normalizeOptionalString(finishedAt),
    metadata: buildSafeOperationMetadata(metadata)
  };
}

export function markOperationRunning(state, overrides = {}) {
  const current = assertOperationState(state);
  return createOperationState({
    ...current,
    ...overrides,
    phase: "running",
    status: overrides.status || "RUNNING",
    retryable: false,
    attempt: overrides.attempt ?? current.attempt + 1,
    errorStatus: null,
    finishedAt: null,
    metadata: {
      ...current.metadata,
      ...overrides.metadata
    }
  });
}

export function markOperationSucceeded(state, overrides = {}) {
  const current = assertOperationState(state);
  const resultStatus = overrides.resultStatus || overrides.status || "SUCCEEDED";
  return createOperationState({
    ...current,
    ...overrides,
    phase: "succeeded",
    status: overrides.status || resultStatus,
    retryable: false,
    resultStatus,
    errorStatus: null,
    metadata: {
      ...current.metadata,
      ...overrides.metadata
    }
  });
}

export function markOperationFailed(state, { error, ...overrides } = {}) {
  const current = assertOperationState(state);
  const errorStatus =
    overrides.errorStatus ||
    overrides.status ||
    error?.status ||
    "OPERATION_FAILED";
  return createOperationState({
    ...current,
    ...overrides,
    phase: "failed",
    status: overrides.status || "UNAVAILABLE",
    retryable: Boolean(overrides.retryable ?? error?.retryable),
    resultStatus: null,
    errorStatus,
    metadata: {
      ...current.metadata,
      ...overrides.metadata
    }
  });
}

export function buildOperationStateSummary(state) {
  const current = assertOperationState(state);
  return {
    operation_state_schema_version: current.operation_state_schema_version,
    operation_id: current.operationId,
    phase: current.phase,
    status: current.status,
    retryable: current.retryable,
    attempt: current.attempt,
    client_mode: current.clientMode,
    route: current.route,
    result_status: current.resultStatus,
    error_status: current.errorStatus,
    metadata: current.metadata
  };
}

function assertOperationState(value) {
  if (
    !value ||
    value.operation_state_schema_version !== AE_WEB_OPERATION_STATE_SCHEMA_VERSION
  ) {
    throw new OperationStateError("Operation state is invalid.", {
      status: "OPERATION_STATE_SCHEMA_INVALID"
    });
  }
  return createOperationState(value);
}

function normalizePhase(phase) {
  if (!AE_WEB_OPERATION_PHASES.includes(phase)) {
    throw new OperationStateError("Operation phase is unsupported.", {
      status: "OPERATION_PHASE_UNSUPPORTED"
    });
  }
  return phase;
}

function normalizeAttempt(attempt) {
  if (!Number.isInteger(attempt) || attempt < 0) {
    throw new OperationStateError("Operation attempt must be a non-negative integer.", {
      status: "OPERATION_ATTEMPT_INVALID"
    });
  }
  return attempt;
}

function normalizeRequiredString(value, status) {
  if (typeof value !== "string" || !value.trim()) {
    throw new OperationStateError("Operation field is required.", { status });
  }
  return value.trim();
}

function normalizeOptionalString(value) {
  if (value == null) return null;
  return String(value).trim();
}

function buildSafeOperationMetadata(metadata) {
  const safeMetadata = { ...SAFE_OPERATION_METADATA };
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return safeMetadata;
  }
  for (const [key, value] of Object.entries(metadata)) {
    if (key in SAFE_OPERATION_METADATA && value === false) {
      safeMetadata[key] = Boolean(value);
    }
  }
  return safeMetadata;
}
