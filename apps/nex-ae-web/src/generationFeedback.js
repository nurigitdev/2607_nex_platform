export const AE_WEB_GENERATION_FEEDBACK_CLIENT_SCHEMA_VERSION =
  "ae_web_generation_feedback_client.v1";
export const AE_WEB_GENERATION_FEEDBACK_SURFACE_SCHEMA_VERSION =
  "ae_web_generation_feedback_surface.v1";
export const AE_GENERATION_FEEDBACK_SCHEMA_VERSION = "ae_generation_feedback.v1";
export const AE_GENERATION_FEEDBACK_ROUTE_TEMPLATE =
  "/api/v1/chat/interactions/{interaction_id}/feedback";

export const GENERATION_FEEDBACK_VALUES = ["positive", "negative", "neutral"];
export const GENERATION_FEEDBACK_REASONS = [
  "helpful",
  "not_helpful",
  "incorrect",
  "citation_issue",
  "irrelevant",
  "incomplete",
  "unsafe",
  "slow",
  "other"
];

const SENSITIVE_KEY_PARTS = [
  "api_key",
  "authorization",
  "credential",
  "password",
  "passwd",
  "raw_generation_output",
  "raw_output",
  "raw_prompt",
  "raw_source",
  "raw_text",
  "raw_user_message",
  "secret",
  "source_text",
  "token"
];

export class GenerationFeedbackError extends Error {
  constructor(message, { status = "GENERATION_FEEDBACK_INVALID", retryable = false } = {}) {
    super(message);
    this.name = "GenerationFeedbackError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function generationFeedbackRoute(interactionId) {
  const normalizedInteractionId = requiredText(interactionId, "interaction_id");
  return AE_GENERATION_FEEDBACK_ROUTE_TEMPLATE.replace(
    "{interaction_id}",
    encodeURIComponent(normalizedInteractionId)
  );
}

export function buildGenerationFeedbackRequest({
  tenantId,
  userId,
  interactionId,
  chatDocumentId = null,
  cxGenerationId = null,
  feedbackValue,
  feedbackReasons = [],
  feedbackComment = null,
  qualityIssueRefs = [],
  submittedVia = "ae-web",
  ...extraFields
} = {}) {
  const payload = {
    ...Object.fromEntries(
      Object.entries(extraFields).filter(([, value]) => value !== undefined)
    ),
    tenant_id: requiredText(tenantId, "tenant_id"),
    user_id: requiredText(userId, "user_id"),
    interaction_id: requiredText(interactionId, "interaction_id"),
    chat_document_id: optionalText(chatDocumentId),
    cx_generation_id: optionalText(cxGenerationId),
    feedback_value: requiredChoice(
      feedbackValue,
      "feedback_value",
      GENERATION_FEEDBACK_VALUES
    ),
    feedback_reasons: normalizeReasons(feedbackReasons),
    quality_issue_refs: normalizeQualityIssueRefs(qualityIssueRefs),
    submitted_via: optionalText(submittedVia) || "ae-web"
  };
  const comment = optionalText(feedbackComment);
  if (comment) payload.feedback_comment = comment;
  assertGenerationFeedbackPayloadSafe(payload);
  return {
    feedback_client_schema_version:
      AE_WEB_GENERATION_FEEDBACK_CLIENT_SCHEMA_VERSION,
    method: "POST",
    route: generationFeedbackRoute(payload.interaction_id),
    payload,
    metadata: {
      rawPromptIncluded: false,
      rawGenerationOutputIncluded: false,
      rawSourceIncluded: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false
    }
  };
}

export function createMockGenerationFeedbackClient({ responseFactory } = {}) {
  return {
    clientMode: "mock",
    async submitGenerationFeedback(request) {
      const response = responseFactory
        ? responseFactory(request.payload)
        : buildMockGenerationFeedbackResponse(request.payload);
      return buildGenerationFeedbackSubmissionResult(response, {
        clientMode: "mock",
        route: request.route
      });
    }
  };
}

export function createFetchGenerationFeedbackClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new GenerationFeedbackError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async submitGenerationFeedback(feedbackRequest) {
      let response;
      try {
        response = await request(`${baseUrl}${feedbackRequest.route}`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify(feedbackRequest.payload)
        });
      } catch {
        throw new GenerationFeedbackError("Generation feedback request failed.", {
          status: "NETWORK_ERROR",
          retryable: true
        });
      }

      const responsePayload = await safeJson(response);
      if (!response.ok) {
        throw new GenerationFeedbackError(
          responsePayload.detail ||
            `Generation feedback failed with HTTP ${response.status}.`,
          {
            status: responsePayload.error_code || `HTTP_${response.status}`,
            retryable: Boolean(responsePayload.retryable)
          }
        );
      }
      return buildGenerationFeedbackSubmissionResult(responsePayload, {
        clientMode: "fetch",
        route: feedbackRequest.route
      });
    }
  };
}

export function buildGenerationFeedbackSubmissionResult(
  feedback,
  { clientMode = "mock", route = null } = {}
) {
  if (!feedback || feedback.feedback_schema_version !== AE_GENERATION_FEEDBACK_SCHEMA_VERSION) {
    throw new GenerationFeedbackError("Generation feedback response is invalid.", {
      status: "GENERATION_FEEDBACK_RESPONSE_INVALID"
    });
  }
  return {
    feedback_client_schema_version:
      AE_WEB_GENERATION_FEEDBACK_CLIENT_SCHEMA_VERSION,
    feedback_schema_version: feedback.feedback_schema_version,
    clientMode,
    route,
    feedbackId: feedback.feedback_id || null,
    status: feedback.status || "RECORDED",
    tenantId: feedback.tenant_id || null,
    userId: feedback.user_id || null,
    interactionId: feedback.interaction_id || null,
    chatDocumentId: feedback.chat_document_id || null,
    cxGenerationId: feedback.cx_generation_id || null,
    feedbackValue: feedback.feedback_value || "neutral",
    reasonCount: Array.isArray(feedback.feedback_reasons)
      ? feedback.feedback_reasons.length
      : 0,
    qualityIssueRefCount: Array.isArray(feedback.quality_issue_refs)
      ? feedback.quality_issue_refs.length
      : 0,
    createdAt: feedback.created_at || null,
    metadata: {
      rawCommentRendered: false,
      rawPromptRendered: false,
      rawGenerationOutputRendered: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false
    }
  };
}

export function createGenerationFeedbackSurfaceState({
  interactionId,
  chatDocumentId = null,
  cxGenerationId = null,
  feedbackValue = "neutral",
  selectedReasons = [],
  status = "READY",
  reason = "feedback_ready",
  route = null,
  feedbackId = null,
  errorStatus = null,
  clientMode = "mock"
} = {}) {
  const normalizedInteractionId = requiredText(interactionId, "interaction_id");
  return {
    feedback_surface_schema_version:
      AE_WEB_GENERATION_FEEDBACK_SURFACE_SCHEMA_VERSION,
    interaction_id: normalizedInteractionId,
    chat_document_id: optionalText(chatDocumentId),
    cx_generation_id: optionalText(cxGenerationId),
    route: route || generationFeedbackRoute(normalizedInteractionId),
    feedback_value: requiredChoice(
      feedbackValue,
      "feedback_value",
      GENERATION_FEEDBACK_VALUES
    ),
    selected_reasons: normalizeReasons(selectedReasons),
    status: normalizeSurfaceStatus(status),
    reason: optionalText(reason) || "feedback_ready",
    feedback_id: optionalText(feedbackId),
    error_status: optionalText(errorStatus),
    client_mode: clientMode === "fetch" ? "fetch" : "mock",
    metadata: {
      rawCommentRendered: false,
      rawPromptRendered: false,
      rawGenerationOutputRendered: false,
      serviceTokenRendered: false,
      databaseEndpointRendered: false,
      providerEndpointRendered: false
    }
  };
}

export function buildGenerationFeedbackSurfaceSummary(surface) {
  if (
    !surface ||
    surface.feedback_surface_schema_version !==
      AE_WEB_GENERATION_FEEDBACK_SURFACE_SCHEMA_VERSION
  ) {
    throw new GenerationFeedbackError("Generation feedback surface is invalid.", {
      status: "GENERATION_FEEDBACK_SURFACE_INVALID"
    });
  }
  return {
    feedback_surface_schema_version: surface.feedback_surface_schema_version,
    interaction_id: surface.interaction_id,
    cx_generation_id: surface.cx_generation_id,
    route: surface.route,
    feedback_value: surface.feedback_value,
    selected_reason_count: surface.selected_reasons.length,
    status: surface.status,
    reason: surface.reason,
    feedback_id_present: Boolean(surface.feedback_id),
    error_status: surface.error_status,
    client_mode: surface.client_mode,
    metadata: surface.metadata
  };
}

export function assertGenerationFeedbackPayloadSafe(payload) {
  const sensitiveKeys = findSensitiveGenerationFeedbackKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new GenerationFeedbackError("Generation feedback payload contains sensitive keys.", {
      status: "GENERATION_FEEDBACK_PAYLOAD_SENSITIVE",
      retryable: false
    });
  }
}

export function findSensitiveGenerationFeedbackKeys(value, path = "") {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      findSensitiveGenerationFeedbackKeys(item, `${path}[${index}]`)
    );
  }
  if (!value || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, child]) => {
    const childPath = path ? `${path}.${key}` : key;
    const matches = isSensitiveKey(key) ? [childPath] : [];
    return matches.concat(findSensitiveGenerationFeedbackKeys(child, childPath));
  });
}

function buildMockGenerationFeedbackResponse(payload) {
  return {
    feedback_schema_version: AE_GENERATION_FEEDBACK_SCHEMA_VERSION,
    feedback_id: `ae-feedback-${payload.interaction_id}-${payload.feedback_value}`,
    status: "RECORDED",
    tenant_id: payload.tenant_id,
    user_id: payload.user_id,
    interaction_id: payload.interaction_id,
    chat_document_id: payload.chat_document_id,
    cx_generation_id: payload.cx_generation_id,
    trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
    request_id: "ae-web-feedback-local",
    feedback_value: payload.feedback_value,
    feedback_reasons: payload.feedback_reasons,
    feedback_comment_hash: payload.feedback_comment ? "a".repeat(64) : null,
    feedback_comment_preview: payload.feedback_comment ? "stored-preview" : null,
    quality_issue_refs: payload.quality_issue_refs,
    metadata: {
      submitted_via: payload.submitted_via,
      raw_prompt_stored: false,
      raw_generation_output_stored: false,
      free_text_comment_storage: "hash_and_short_preview_only"
    },
    created_at: "2026-08-25T00:00:00Z"
  };
}

function normalizeReasons(reasons) {
  if (reasons == null) return [];
  if (!Array.isArray(reasons)) {
    throw new GenerationFeedbackError("feedback_reasons must be an array.", {
      status: "GENERATION_FEEDBACK_REASONS_INVALID"
    });
  }
  const normalized = [];
  for (const reason of reasons) {
    const value = requiredChoice(reason, "feedback_reason", GENERATION_FEEDBACK_REASONS);
    if (!normalized.includes(value)) normalized.push(value);
  }
  return normalized;
}

function normalizeQualityIssueRefs(refs) {
  if (refs == null) return [];
  if (!Array.isArray(refs)) {
    throw new GenerationFeedbackError("quality_issue_refs must be an array.", {
      status: "GENERATION_FEEDBACK_QUALITY_REFS_INVALID"
    });
  }
  return refs.map(ref => {
    if (!ref || typeof ref !== "object" || Array.isArray(ref)) {
      throw new GenerationFeedbackError("quality issue ref must be an object.", {
        status: "GENERATION_FEEDBACK_QUALITY_REF_INVALID"
      });
    }
    return {
      source_service: requiredText(ref.source_service, "source_service"),
      issue_type: requiredText(ref.issue_type, "issue_type"),
      issue_code: requiredText(ref.issue_code, "issue_code"),
      issue_ref_id: optionalText(ref.issue_ref_id)
    };
  });
}

function normalizeSurfaceStatus(status) {
  if (["READY", "SUBMITTING", "RECORDED", "FAILED"].includes(status)) {
    return status;
  }
  return "READY";
}

function requiredChoice(value, fieldName, choices) {
  const text = requiredText(value, fieldName);
  if (!choices.includes(text)) {
    throw new GenerationFeedbackError(`${fieldName} is unsupported.`, {
      status: `${fieldName.toUpperCase()}_UNSUPPORTED`
    });
  }
  return text;
}

function requiredText(value, fieldName) {
  const text = optionalText(value);
  if (!text) {
    throw new GenerationFeedbackError(`${fieldName} is required.`, {
      status: `${fieldName.toUpperCase()}_REQUIRED`
    });
  }
  return text;
}

function optionalText(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function isSensitiveKey(key) {
  const normalized = String(key).trim().toLowerCase();
  return SENSITIVE_KEY_PARTS.some(part => normalized.includes(part));
}

async function safeJson(response) {
  try {
    const payload = await response.json();
    return payload && typeof payload === "object" && !Array.isArray(payload)
      ? payload
      : {};
  } catch {
    return {};
  }
}
