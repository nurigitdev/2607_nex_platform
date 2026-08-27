import {
  REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES
} from "./repairedResponseReviewBoundary.js";

export const AE_WEB_REPAIRED_RESPONSE_REVIEW_CLIENT_SCHEMA_VERSION =
  "ae_web_repaired_response_review_client.v1";

export const AE_WEB_REPAIRED_RESPONSE_REVIEW_SURFACE_SCHEMA_VERSION =
  "ae_web_repaired_response_review_surface.v1";

export const AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION =
  "ae_repaired_response_review_projection.v1";

export const AE_REPAIRED_RESPONSE_REVIEW_COLLECTION_SCHEMA_VERSION =
  "ae_repaired_response_review_collection.v1";

const REVIEW_ACTIONS = [
  "accept_repair",
  "keep_original",
  "view_original",
  "view_repaired",
  "view_lineage"
];

const SENSITIVE_KEY_PARTS = [
  "api_key",
  "authorization",
  "credential",
  "database_url",
  "password",
  "passwd",
  "provider_url",
  "raw_evidence",
  "raw_generation_output",
  "raw_output",
  "raw_prompt",
  "raw_source",
  "raw_text",
  "secret",
  "service_token",
  "source_text",
  "storage_path",
  "token"
];

const ALLOWED_FALSE_SENSITIVE_FLAGS = [
  "raw_output_included",
  "raw_prompt_included",
  "raw_source_text_included",
  "evidence_text_included",
  "provider_detail_included",
  "storage_path_included",
  "rawPromptRendered",
  "rawGenerationOutputRendered",
  "rawSourceRendered",
  "serviceTokenRendered"
];

const SAFE_USAGE_TOKEN_KEYS = [
  "completion_tokens",
  "input_tokens",
  "output_tokens",
  "prompt_tokens",
  "total_tokens"
];

export class RepairedResponseReviewClientError extends Error {
  constructor(
    message,
    { status = "REPAIRED_RESPONSE_REVIEW_CLIENT_ERROR", retryable = false } = {}
  ) {
    super(message);
    this.name = "RepairedResponseReviewClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function repairedResponseReviewCollectionRoute(interactionId) {
  return REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES.collection.replace(
    "{interaction_id}",
    encodeURIComponent(requiredText(interactionId, "interaction_id"))
  );
}

export function repairedResponseReviewDetailRoute(interactionId, handoffId) {
  return REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES.detail
    .replace("{interaction_id}", encodeURIComponent(requiredText(interactionId, "interaction_id")))
    .replace(
      "{repaired_response_handoff_id}",
      encodeURIComponent(requiredText(handoffId, "repaired_response_handoff_id"))
    );
}

export function createMockRepairedResponseReviewClient({
  projections = [],
  responseFactory
} = {}) {
  const surfacesByInteraction = new Map();
  for (const projection of projections) {
    const surface = buildRepairedResponseReviewSurfaceFromProjection(projection, {
      clientMode: "mock"
    });
    const list = surfacesByInteraction.get(surface.interactionId) || [];
    list.push(surface);
    surfacesByInteraction.set(surface.interactionId, list);
  }

  return {
    clientMode: "mock",
    async listRepairedResponseReviews(interactionId) {
      const route = repairedResponseReviewCollectionRoute(interactionId);
      if (responseFactory) {
        return buildRepairedResponseReviewCollectionSurface(
          responseFactory({ interactionId, route, method: "list" }),
          { clientMode: "mock", route }
        );
      }
      return buildMockCollectionSurface(
        surfacesByInteraction.get(String(interactionId)) || [],
        { interactionId, route }
      );
    },
    async getRepairedResponseReview(interactionId, handoffId) {
      const route = repairedResponseReviewDetailRoute(interactionId, handoffId);
      if (responseFactory) {
        return buildRepairedResponseReviewSurfaceFromProjection(
          responseFactory({ interactionId, handoffId, route, method: "detail" }),
          { clientMode: "mock", route }
        );
      }
      const surface = (surfacesByInteraction.get(String(interactionId)) || []).find(
        item => item.repairedResponseHandoffId === String(handoffId)
      );
      if (!surface) {
        throw new RepairedResponseReviewClientError(
          "Repaired response review was not found.",
          { status: "NOT_FOUND" }
        );
      }
      return { ...surface, route };
    }
  };
}

export function createFetchRepairedResponseReviewClient({
  baseUrl = "",
  fetchImpl
} = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new RepairedResponseReviewClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return {
    clientMode: "fetch",
    async listRepairedResponseReviews(interactionId) {
      const route = repairedResponseReviewCollectionRoute(interactionId);
      const payload = await fetchJson(request, `${baseUrl}${route}`);
      return buildRepairedResponseReviewCollectionSurface(payload, {
        clientMode: "fetch",
        route
      });
    },
    async getRepairedResponseReview(interactionId, handoffId) {
      const route = repairedResponseReviewDetailRoute(interactionId, handoffId);
      const payload = await fetchJson(request, `${baseUrl}${route}`);
      return buildRepairedResponseReviewSurfaceFromProjection(payload, {
        clientMode: "fetch",
        route
      });
    }
  };
}

export function buildRepairedResponseReviewCollectionSurface(
  payload,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(payload) ||
    payload.collection_schema_version !==
      AE_REPAIRED_RESPONSE_REVIEW_COLLECTION_SCHEMA_VERSION ||
    !Array.isArray(payload.items)
  ) {
    throw new RepairedResponseReviewClientError(
      "Repaired response review collection is invalid.",
      { status: "REVIEW_COLLECTION_INVALID" }
    );
  }
  const items = payload.items.map(item =>
    buildRepairedResponseReviewSurfaceFromProjection(item, { clientMode, route: null })
  );
  return buildMockCollectionSurface(items, {
    interactionId: payload.interaction_id,
    route,
    checkedAt: payload.checked_at,
    clientMode
  });
}

export function buildRepairedResponseReviewSurfaceFromProjection(
  projection,
  { clientMode = "mock", route = null } = {}
) {
  if (
    !isObject(projection) ||
    projection.projection_schema_version !==
      AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION
  ) {
    throw new RepairedResponseReviewClientError(
      "Repaired response review projection is invalid.",
      { status: "REVIEW_PROJECTION_INVALID" }
    );
  }
  assertRepairedResponseReviewPayloadSafe(projection);
  const ownerScope = requiredObject(projection.owner_scope, "owner_scope");
  const conversationScope = requiredObject(
    projection.conversation_scope,
    "conversation_scope"
  );
  const reviewCard = requiredObject(projection.review_card, "review_card");
  const repaired = requiredObject(
    projection.repaired_response_summary,
    "repaired_response_summary"
  );
  const original = requiredObject(
    projection.original_response_ref,
    "original_response_ref"
  );
  const lineage = requiredObject(projection.lineage_summary, "lineage_summary");
  const controls = requiredObject(projection.decision_controls, "decision_controls");
  const links = requiredObject(projection.links, "links");
  const primaryActions = normalizeActions(controls.primary_actions);
  if (
    !primaryActions.includes("accept_repair") ||
    !primaryActions.includes("keep_original")
  ) {
    throw new RepairedResponseReviewClientError(
      "Repaired response review primary actions are incomplete.",
      { status: "REVIEW_PRIMARY_ACTIONS_INCOMPLETE" }
    );
  }

  const surface = {
    review_surface_schema_version:
      AE_WEB_REPAIRED_RESPONSE_REVIEW_SURFACE_SCHEMA_VERSION,
    projection_schema_version: projection.projection_schema_version,
    projectionStatus: projection.projection_status || "READY_FOR_DECISION",
    repairedResponseHandoffId: requiredText(
      projection.repaired_response_handoff_id,
      "repaired_response_handoff_id"
    ),
    handoffRequestId: requiredText(
      projection.handoff_request_id,
      "handoff_request_id"
    ),
    tenantId: requiredText(ownerScope.tenant_id, "tenant_id"),
    workspaceId: requiredText(ownerScope.workspace_id, "workspace_id"),
    ownerUserId: requiredText(ownerScope.owner_user_id, "owner_user_id"),
    chatDocumentId: requiredText(conversationScope.chat_document_id, "chat_document_id"),
    interactionId: requiredText(conversationScope.interaction_id, "interaction_id"),
    title: requiredText(reviewCard.title, "review_card.title"),
    presentationMode: requiredText(
      reviewCard.presentation_mode,
      "review_card.presentation_mode"
    ),
    originalGenerationId: requiredText(
      original.cx_generation_id,
      "original_response_ref.cx_generation_id"
    ),
    repairedGenerationId: requiredText(
      repaired.cx_generation_id,
      "repaired_response_summary.cx_generation_id"
    ),
    repairedStatus: repaired.status || "UNKNOWN",
    repairedOutputPreview: optionalText(repaired.output_preview) || "",
    repairedOutputHashPresent: hasText(repaired.output_hash),
    lineageStatus: lineage.lineage_status || "UNKNOWN",
    remediationActionId: requiredText(
      lineage.remediation_action_id,
      "lineage_summary.remediation_action_id"
    ),
    decisionRoute: requiredText(
      controls.decision_submit_path,
      "decision_controls.decision_submit_path"
    ),
    availableActions: normalizeActions(controls.available_actions),
    primaryActions,
    secondaryActions: normalizeActions(controls.secondary_actions),
    links: {
      handoff: requiredText(links.handoff, "links.handoff"),
      originalGeneration: requiredText(
        links.original_generation,
        "links.original_generation"
      ),
      repairedGeneration: requiredText(
        links.repaired_generation,
        "links.repaired_generation"
      ),
      remediationExecution: requiredText(
        links.remediation_execution,
        "links.remediation_execution"
      )
    },
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    route,
    checkedAt: projection.checked_at || null,
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
  assertRepairedResponseReviewPayloadSafe(surface);
  return surface;
}

export function buildRepairedResponseReviewSurfaceSummary(surface) {
  if (
    !isObject(surface) ||
    surface.review_surface_schema_version !==
      AE_WEB_REPAIRED_RESPONSE_REVIEW_SURFACE_SCHEMA_VERSION
  ) {
    throw new RepairedResponseReviewClientError(
      "Repaired response review surface is invalid.",
      { status: "REVIEW_SURFACE_INVALID" }
    );
  }
  return {
    review_surface_schema_version: surface.review_surface_schema_version,
    repaired_response_handoff_id: surface.repairedResponseHandoffId,
    interaction_id: surface.interactionId,
    chat_document_id: surface.chatDocumentId,
    projection_status: surface.projectionStatus,
    presentation_mode: surface.presentationMode,
    original_generation_id: surface.originalGenerationId,
    repaired_generation_id: surface.repairedGenerationId,
    repaired_status: surface.repairedStatus,
    repaired_output_preview_present: hasText(surface.repairedOutputPreview),
    repaired_output_hash_present: surface.repairedOutputHashPresent,
    lineage_status: surface.lineageStatus,
    decision_route: surface.decisionRoute,
    primary_action_count: surface.primaryActions.length,
    secondary_action_count: surface.secondaryActions.length,
    client_mode: surface.clientMode,
    route: surface.route,
    metadata: surface.metadata
  };
}

export function assertRepairedResponseReviewPayloadSafe(payload) {
  const sensitiveKeys = findSensitiveRepairedResponseReviewKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new RepairedResponseReviewClientError(
      "Repaired response review payload contains sensitive keys.",
      { status: "REVIEW_PAYLOAD_SENSITIVE_KEY" }
    );
  }
}

export function findSensitiveRepairedResponseReviewKeys(payload) {
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
        !isAllowedFalseSensitiveFlag(key, child) &&
        !isSafeUsageTokenCount(key, child)
      ) {
        found.push(keyPath);
      }
      visit(child, keyPath);
    }
  }

  visit(payload, "");
  return found.sort();
}

async function fetchJson(request, url) {
  let response;
  try {
    response = await request(url, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json"
      }
    });
  } catch {
    throw new RepairedResponseReviewClientError(
      "Repaired response review request failed.",
      { status: "NETWORK_ERROR", retryable: true }
    );
  }
  const payload = await safeJson(response);
  if (!response.ok) {
    throw new RepairedResponseReviewClientError(
      payload.detail ||
        `Repaired response review request failed with HTTP ${response.status}.`,
      {
        status: payload.error_code || `HTTP_${response.status}`,
        retryable: Boolean(payload.retryable)
      }
    );
  }
  return payload;
}

function buildMockCollectionSurface(
  items,
  { interactionId, route = null, checkedAt = null, clientMode = "mock" } = {}
) {
  const selectedInteractionId = requiredText(interactionId, "interaction_id");
  return {
    review_client_schema_version:
      AE_WEB_REPAIRED_RESPONSE_REVIEW_CLIENT_SCHEMA_VERSION,
    collection_schema_version: AE_REPAIRED_RESPONSE_REVIEW_COLLECTION_SCHEMA_VERSION,
    interactionId: selectedInteractionId,
    itemCount: items.length,
    items: items.map(item => ({ ...item })),
    clientMode: clientMode === "fetch" ? "fetch" : "mock",
    route,
    checkedAt,
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

async function safeJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}

function normalizeActions(values) {
  if (!Array.isArray(values)) return [];
  const normalized = [];
  for (const value of values) {
    if (typeof value === "string" && REVIEW_ACTIONS.includes(value)) {
      if (!normalized.includes(value)) normalized.push(value);
    }
  }
  return normalized;
}

function requiredObject(value, fieldName) {
  if (!isObject(value)) {
    throw new RepairedResponseReviewClientError(`${fieldName} must be an object.`, {
      status: "REVIEW_OBJECT_INVALID"
    });
  }
  return value;
}

function requiredText(value, fieldName) {
  const normalized = optionalText(value);
  if (!normalized) {
    throw new RepairedResponseReviewClientError(`${fieldName} is required.`, {
      status: "REVIEW_FIELD_REQUIRED"
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

function hasText(value) {
  return optionalText(value) !== null;
}

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function isSafeUsageTokenCount(key, value) {
  return (
    SAFE_USAGE_TOKEN_KEYS.includes(key) &&
    Number.isInteger(value) &&
    value >= 0
  );
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
