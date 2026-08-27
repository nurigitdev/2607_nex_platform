export const AE_WEB_REPAIRED_RESPONSE_DECISION_STATE_SCHEMA_VERSION =
  "ae_web_repaired_response_decision_state.v1";

export const REPAIRED_RESPONSE_DECISION_UI_STATUSES = [
  "READY_FOR_DECISION",
  "SUBMITTING",
  "RECORDED",
  "FAILED"
];

export function createRepairedResponseDecisionState({
  status = "READY_FOR_DECISION",
  action = null,
  decisionId = null,
  errorStatus = null,
  clientMode = "mock"
} = {}) {
  const normalizedStatus = normalizeStatus(status);
  return {
    decision_state_schema_version:
      AE_WEB_REPAIRED_RESPONSE_DECISION_STATE_SCHEMA_VERSION,
    status: normalizedStatus,
    action: normalizeAction(action),
    decisionId: optionalText(decisionId),
    errorStatus: optionalText(errorStatus),
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: {
      rawPromptRendered: false,
      rawGenerationOutputRendered: false,
      rawSourceRendered: false,
      serviceTokenRendered: false
    }
  };
}

export function markRepairedResponseDecisionSubmitting(state, action, clientMode) {
  const current = assertDecisionState(state);
  return createRepairedResponseDecisionState({
    ...current,
    status: "SUBMITTING",
    action,
    decisionId: null,
    errorStatus: null,
    clientMode: clientMode || current.clientMode
  });
}

export function markRepairedResponseDecisionRecorded(state, result) {
  const current = assertDecisionState(state);
  return createRepairedResponseDecisionState({
    ...current,
    status: "RECORDED",
    action: result?.action || current.action,
    decisionId: result?.repairedResponseDecisionId || current.decisionId,
    errorStatus: null,
    clientMode: result?.clientMode || current.clientMode
  });
}

export function markRepairedResponseDecisionFailed(state, action, error, clientMode) {
  const current = assertDecisionState(state);
  return createRepairedResponseDecisionState({
    ...current,
    status: "FAILED",
    action,
    decisionId: current.decisionId,
    errorStatus: error?.status || "REPAIRED_RESPONSE_DECISION_FAILED",
    clientMode: clientMode || current.clientMode
  });
}

export function buildRepairedResponseDecisionStateSummary(state) {
  const current = assertDecisionState(state);
  return {
    decision_state_schema_version: current.decision_state_schema_version,
    status: current.status,
    action: current.action,
    decision_id_present: Boolean(current.decisionId),
    error_status: current.errorStatus,
    client_mode: current.clientMode,
    metadata: current.metadata
  };
}

export function assertDecisionState(state) {
  if (
    !state ||
    state.decision_state_schema_version !==
      AE_WEB_REPAIRED_RESPONSE_DECISION_STATE_SCHEMA_VERSION
  ) {
    throw new Error("Repaired response decision state is invalid.");
  }
  return state;
}

function normalizeStatus(status) {
  const value = optionalText(status) || "READY_FOR_DECISION";
  return REPAIRED_RESPONSE_DECISION_UI_STATUSES.includes(value)
    ? value
    : "READY_FOR_DECISION";
}

function normalizeAction(action) {
  const value = optionalText(action);
  if (value === "accept_repair" || value === "keep_original") return value;
  return null;
}

function optionalText(value) {
  if (value == null) return null;
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}
