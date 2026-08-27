import {
  REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES
} from "./repairedResponseReviewBoundary.js";
import {
  buildRepairedResponseReviewSurfaceSummary
} from "./repairedResponseReviewClient.js";

export const AE_WEB_REPAIRED_RESPONSE_DECISION_CLIENT_SCHEMA_VERSION =
  "ae_web_repaired_response_decision_client.v1";

export const AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION =
  "ae_repaired_response_decision.v1";

export const REPAIRED_RESPONSE_DECISION_ACTIONS = [
  "accept_repair",
  "keep_original"
];

export const REPAIRED_RESPONSE_DECISION_REASON_CODES = [
  "citation_fixed",
  "answer_improved",
  "prefer_repaired",
  "prefer_original",
  "repair_not_needed",
  "repair_unsatisfactory",
  "other"
];

const DEFAULT_REASON_BY_ACTION = {
  accept_repair: "prefer_repaired",
  keep_original: "prefer_original"
};

const SUBMITTERS = ["chat_review", "document_detail", "operator_replay"];
const MAX_DECISION_COMMENT_LENGTH = 240;

const SENSITIVE_KEY_PARTS = [
  "api_key",
  "authorization",
  "credential",
  "database_url",
  "messages",
  "model_path",
  "password",
  "passwd",
  "provider_endpoint",
  "provider_url",
  "raw_evidence",
  "raw_generation_output",
  "raw_output",
  "raw_prompt",
  "raw_source",
  "raw_text",
  "secret",
  "source_text",
  "storage_path",
  "token"
];

const ALLOWED_FALSE_SENSITIVE_FLAGS = [
  "raw_prompt_stored",
  "raw_generation_output_stored",
  "raw_source_text_stored",
  "raw_evidence_stored",
  "rawPromptIncluded",
  "rawGenerationOutputIncluded",
  "rawSourceIncluded",
  "browserServiceTokenIncluded",
  "databaseEndpointIncluded",
  "providerEndpointIncluded",
  "storageLocationIncluded"
];

export class RepairedResponseDecisionClientError extends Error {
  constructor(
    message,
    { status = "REPAIRED_RESPONSE_DECISION_CLIENT_ERROR", retryable = false } = {}
  ) {
    super(message);
    this.name = "RepairedResponseDecisionClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function repairedResponseDecisionRoute(interactionId, handoffId) {
  return REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES.decision
    .replace("{interaction_id}", encodeURIComponent(requiredText(interactionId, "interaction_id")))
    .replace(
      "{repaired_response_handoff_id}",
      encodeURIComponent(requiredText(handoffId, "repaired_response_handoff_id"))
    );
}

export function buildRepairedResponseDecisionRequest({
  reviewSurface,
  action,
  reasonCodes = null,
  decisionComment = null,
  decisionRequestId = null,
  actorClaimsRef = null,
  submittedVia = "chat_review"
} = {}) {
  const summary = buildRepairedResponseReviewSurfaceSummary(
    requiredObject(reviewSurface, "review_surface")
  );
  const selectedAction = requiredChoice(
    action,
    "decision_action",
    REPAIRED_RESPONSE_DECISION_ACTIONS
  );
  const route =
    optionalText(reviewSurface.decisionRoute) ||
    repairedResponseDecisionRoute(
      summary.interaction_id,
      summary.repaired_response_handoff_id
    );
  const actor = normalizeActorClaims(actorClaimsRef, reviewSurface);
  const payload = {
    tenant_id: requiredText(reviewSurface.tenantId, "tenant_id"),
    workspace_id: requiredText(reviewSurface.workspaceId, "workspace_id"),
    owner_user_id: requiredText(reviewSurface.ownerUserId, "owner_user_id"),
    chat_document_id: requiredText(summary.chat_document_id, "chat_document_id"),
    interaction_id: requiredText(summary.interaction_id, "interaction_id"),
    repaired_response_handoff_id: requiredText(
      summary.repaired_response_handoff_id,
      "repaired_response_handoff_id"
    ),
    decision_action: selectedAction,
    decision_request_id:
      optionalText(decisionRequestId) ||
      defaultDecisionRequestId(summary, selectedAction, actor.actor_id),
    decision_reason_codes: normalizeReasonCodes(reasonCodes, selectedAction),
    submitted_via: requiredChoice(submittedVia, "submitted_via", SUBMITTERS),
    actor_claims_ref: actor
  };
  const comment = optionalText(decisionComment);
  if (comment) {
    if (comment.length > MAX_DECISION_COMMENT_LENGTH) {
      throw new RepairedResponseDecisionClientError(
        "Decision comment is too long.",
        { status: "DECISION_COMMENT_TOO_LONG" }
      );
    }
    payload.decision_comment = comment;
  }
  assertRepairedResponseDecisionPayloadSafe(payload);
  return {
    decision_client_schema_version:
      AE_WEB_REPAIRED_RESPONSE_DECISION_CLIENT_SCHEMA_VERSION,
    method: "POST",
    route,
    payload,
    metadata: {
      rawPromptIncluded: false,
      rawGenerationOutputIncluded: false,
      rawSourceIncluded: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false,
      storageLocationIncluded: false
    }
  };
}

export function createMockRepairedResponseDecisionClient({
  responseFactory
} = {}) {
  return {
    clientMode: "mock",
    async submitRepairedResponseDecision(decisionRequest) {
      const response = responseFactory
        ? responseFactory(decisionRequest.payload)
        : buildMockDecisionResponse(decisionRequest.payload);
      return buildRepairedResponseDecisionSubmissionResult(response, {
        clientMode: "mock",
        route: decisionRequest.route
      });
    }
  };
}

export function createFetchRepairedResponseDecisionClient({
  baseUrl = "",
  fetchImpl
} = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new RepairedResponseDecisionClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async submitRepairedResponseDecision(decisionRequest) {
      let response;
      try {
        response = await request(`${baseUrl}${decisionRequest.route}`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify(decisionRequest.payload)
        });
      } catch {
        throw new RepairedResponseDecisionClientError(
          "Repaired response decision request failed.",
          { status: "NETWORK_ERROR", retryable: true }
        );
      }
      const payload = await safeJson(response);
      if (!response.ok) {
        throw new RepairedResponseDecisionClientError(
          payload.detail ||
            `Repaired response decision failed with HTTP ${response.status}.`,
          {
            status: payload.error_code || `HTTP_${response.status}`,
            retryable: Boolean(payload.retryable)
          }
        );
      }
      return buildRepairedResponseDecisionSubmissionResult(payload, {
        clientMode: "fetch",
        route: decisionRequest.route
      });
    }
  };
}

export function buildRepairedResponseDecisionSubmissionResult(
  decision,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(decision) ||
    decision.decision_schema_version !==
      AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION
  ) {
    throw new RepairedResponseDecisionClientError(
      "Repaired response decision response is invalid.",
      { status: "DECISION_RESPONSE_INVALID" }
    );
  }
  assertRepairedResponseDecisionPayloadSafe(decision);
  return {
    decision_client_schema_version:
      AE_WEB_REPAIRED_RESPONSE_DECISION_CLIENT_SCHEMA_VERSION,
    decision_schema_version: decision.decision_schema_version,
    repairedResponseDecisionId:
      optionalText(decision.repaired_response_decision_id) || null,
    repairedResponseHandoffId:
      optionalText(decision.repaired_response_handoff_id) || null,
    interactionId: optionalText(decision.interaction_id) || null,
    chatDocumentId: optionalText(decision.chat_document_id) || null,
    status: optionalText(decision.decision_status) || "RECORDED",
    action: requiredChoice(
      decision.decision_action,
      "decision_action",
      REPAIRED_RESPONSE_DECISION_ACTIONS
    ),
    selectedGenerationId:
      optionalText(decision.selected_cx_generation_id) || null,
    rejectedGenerationId:
      optionalText(decision.rejected_cx_generation_id) || null,
    reasonCount: Array.isArray(decision.decision_reason_codes)
      ? decision.decision_reason_codes.length
      : 0,
    commentPreviewPresent: Boolean(optionalText(decision.decision_comment_preview)),
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    route,
    createdAt: optionalText(decision.created_at),
    metadata: {
      rawPromptRendered: false,
      rawGenerationOutputRendered: false,
      rawSourceRendered: false,
      serviceTokenRendered: false,
      databaseEndpointRendered: false,
      providerEndpointRendered: false,
      storageLocationRendered: false
    }
  };
}

export function assertRepairedResponseDecisionPayloadSafe(payload) {
  const sensitiveKeys = findSensitiveRepairedResponseDecisionKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new RepairedResponseDecisionClientError(
      "Repaired response decision payload contains sensitive keys.",
      { status: "DECISION_PAYLOAD_SENSITIVE_KEY" }
    );
  }
}

export function findSensitiveRepairedResponseDecisionKeys(payload) {
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

function buildMockDecisionResponse(payload) {
  const selected =
    payload.decision_action === "accept_repair"
      ? "cx-gen-repair-local"
      : "cx-gen-parent-local";
  const rejected =
    payload.decision_action === "accept_repair"
      ? "cx-gen-parent-local"
      : "cx-gen-repair-local";
  return {
    decision_schema_version: AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
    repaired_response_decision_id: `decision-${payload.decision_request_id}`,
    decision_request_id: payload.decision_request_id,
    decision_status: "RECORDED",
    decision_action: payload.decision_action,
    repaired_response_handoff_id: payload.repaired_response_handoff_id,
    handoff_request_id: "request-local-repair-001",
    trace_id: "trace-local-repair",
    request_id: "ae-web-decision-local",
    tenant_id: payload.tenant_id,
    workspace_id: payload.workspace_id,
    owner_user_id: payload.owner_user_id,
    chat_document_id: payload.chat_document_id,
    interaction_id: payload.interaction_id,
    actor_claims_ref: payload.actor_claims_ref,
    parent_cx_generation_id: "cx-gen-parent-local",
    repair_cx_generation_id: "cx-gen-repair-local",
    selected_cx_generation_id: selected,
    rejected_cx_generation_id: rejected,
    remediation_action_id: "remediation-local-001",
    decision_reason_codes: payload.decision_reason_codes,
    decision_comment_hash: payload.decision_comment ? "b".repeat(64) : null,
    decision_comment_preview: payload.decision_comment ? "stored-preview" : null,
    metadata: {
      submitted_via: payload.submitted_via,
      raw_prompt_stored: false,
      raw_generation_output_stored: false,
      raw_source_text_stored: false,
      raw_evidence_stored: false,
      free_text_comment_storage: "hash_and_short_preview_only",
      parent_generation_mutated: false
    },
    created_at: "2026-08-27T00:03:00Z",
    updated_at: "2026-08-27T00:03:00Z"
  };
}

function normalizeActorClaims(actorClaimsRef, surface) {
  const claims = isObject(actorClaimsRef) ? actorClaimsRef : {};
  return {
    actor_type: optionalText(claims.actor_type) || "user",
    actor_id: optionalText(claims.actor_id) || requiredText(surface.ownerUserId, "actor_id"),
    tenant_id: optionalText(claims.tenant_id) || requiredText(surface.tenantId, "tenant_id")
  };
}

function normalizeReasonCodes(reasonCodes, action) {
  if (reasonCodes == null || reasonCodes === "") {
    return [DEFAULT_REASON_BY_ACTION[action]];
  }
  if (!Array.isArray(reasonCodes)) {
    throw new RepairedResponseDecisionClientError(
      "Decision reason codes must be an array.",
      { status: "DECISION_REASON_CODES_INVALID" }
    );
  }
  const normalized = [];
  for (const code of reasonCodes) {
    const value = optionalText(code);
    if (!value) continue;
    if (!REPAIRED_RESPONSE_DECISION_REASON_CODES.includes(value)) {
      throw new RepairedResponseDecisionClientError(
        `Unsupported repaired response decision reason code: ${value}`,
        { status: "DECISION_REASON_CODE_UNSUPPORTED" }
      );
    }
    if (!normalized.includes(value)) normalized.push(value);
  }
  return normalized.length > 0
    ? normalized
    : [DEFAULT_REASON_BY_ACTION[action]];
}

function defaultDecisionRequestId(summary, action, actorId) {
  return [
    "ae-web",
    summary.repaired_response_handoff_id,
    summary.interaction_id,
    actorId,
    action
  ].join(":");
}

async function safeJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}

function requiredObject(value, fieldName) {
  if (!isObject(value)) {
    throw new RepairedResponseDecisionClientError(`${fieldName} must be an object.`, {
      status: "DECISION_OBJECT_INVALID"
    });
  }
  return value;
}

function requiredChoice(value, fieldName, choices) {
  const text = requiredText(value, fieldName);
  if (!choices.includes(text)) {
    throw new RepairedResponseDecisionClientError(`${fieldName} is unsupported.`, {
      status: `${fieldName.toUpperCase()}_UNSUPPORTED`
    });
  }
  return text;
}

function requiredText(value, fieldName) {
  const normalized = optionalText(value);
  if (!normalized) {
    throw new RepairedResponseDecisionClientError(`${fieldName} is required.`, {
      status: "DECISION_FIELD_REQUIRED"
    });
  }
  return normalized;
}

function optionalText(value) {
  if (value == null) return null;
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
