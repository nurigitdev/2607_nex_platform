export const AE_WEB_REPAIRED_RESPONSE_REVIEW_BOUNDARY_SCHEMA_VERSION =
  "ae_web_repaired_response_review_boundary.v1";

export const REPAIRED_RESPONSE_REVIEW_PRIMARY_SURFACE =
  "chat_interaction_detail";

export const REPAIRED_RESPONSE_REVIEW_SECONDARY_SURFACES = [
  "document_detail_link",
  "lineage_drilldown"
];

export const REPAIRED_RESPONSE_REVIEW_DECISION_ACTIONS = [
  "accept_repair",
  "keep_original"
];

export const REPAIRED_RESPONSE_REVIEW_SECONDARY_ACTIONS = [
  "view_original",
  "view_repaired",
  "view_lineage"
];

export const REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES = {
  collection:
    "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/review",
  detail:
    "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{repaired_response_handoff_id}/review",
  decision:
    "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{repaired_response_handoff_id}/decisions"
};

const SUPPORTED_PRIMARY_SURFACES = [REPAIRED_RESPONSE_REVIEW_PRIMARY_SURFACE];
const SUPPORTED_SECONDARY_SURFACES = [
  ...REPAIRED_RESPONSE_REVIEW_SECONDARY_SURFACES
];
const SUPPORTED_CLIENT_MODES = ["mock", "fetch"];
const SAFE_CONTRACTS = {
  handoff: "ae_repaired_response_handoff.v1",
  reviewProjection: "ae_repaired_response_review_projection.v1",
  reviewCollection: "ae_repaired_response_review_collection.v1",
  decision: "ae_repaired_response_decision.v1"
};

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
  "stores_raw_generation_output",
  "stores_raw_prompt",
  "stores_source_text",
  "stores_service_credentials",
  "rawPromptRendered",
  "rawGenerationOutputRendered",
  "rawSourceRendered",
  "serviceTokenRendered"
];

export class RepairedResponseReviewBoundaryError extends Error {
  constructor(
    message,
    { status = "REPAIRED_RESPONSE_REVIEW_BOUNDARY_INVALID" } = {}
  ) {
    super(message);
    this.name = "RepairedResponseReviewBoundaryError";
    this.status = status;
  }
}

export function buildRepairedResponseReviewBoundary({
  primarySurface = REPAIRED_RESPONSE_REVIEW_PRIMARY_SURFACE,
  secondarySurfaces = REPAIRED_RESPONSE_REVIEW_SECONDARY_SURFACES,
  decisionActions = REPAIRED_RESPONSE_REVIEW_DECISION_ACTIONS,
  secondaryActions = REPAIRED_RESPONSE_REVIEW_SECONDARY_ACTIONS,
  clientModes = SUPPORTED_CLIENT_MODES,
  reviewedAt = null
} = {}) {
  const boundary = {
    boundary_schema_version:
      AE_WEB_REPAIRED_RESPONSE_REVIEW_BOUNDARY_SCHEMA_VERSION,
    primary_surface: normalizePrimarySurface(primarySurface),
    secondary_surfaces: normalizeStringSet(
      secondarySurfaces,
      SUPPORTED_SECONDARY_SURFACES,
      "secondary_surfaces"
    ),
    route_templates: { ...REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES },
    source_contracts: { ...SAFE_CONTRACTS },
    decision_controls: {
      primary_actions: normalizeStringSet(
        decisionActions,
        REPAIRED_RESPONSE_REVIEW_DECISION_ACTIONS,
        "decision_actions"
      ),
      secondary_actions: normalizeStringSet(
        secondaryActions,
        REPAIRED_RESPONSE_REVIEW_SECONDARY_ACTIONS,
        "secondary_actions"
      ),
      duplicate_submit_policy: "disable_while_submitting",
      submitter: "chat_review"
    },
    client_modes: normalizeStringSet(clientModes, SUPPORTED_CLIENT_MODES, "client_modes"),
    browser_storage_policy: {
      stores_decision_payload_only: true,
      stores_raw_generation_output: false,
      stores_raw_prompt: false,
      stores_source_text: false,
      stores_service_credentials: false
    },
    metadata: {
      reviewed_at: reviewedAt,
      rawPromptRendered: false,
      rawGenerationOutputRendered: false,
      rawSourceRendered: false,
      serviceTokenRendered: false,
      databaseEndpointRendered: false,
      providerEndpointRendered: false,
      storageLocationRendered: false
    }
  };
  return validateRepairedResponseReviewBoundary(boundary);
}

export function buildRepairedResponseReviewBoundarySummary(boundary) {
  const validated = validateRepairedResponseReviewBoundary(boundary);
  return {
    boundary_schema_version: validated.boundary_schema_version,
    primary_surface: validated.primary_surface,
    secondary_surface_count: validated.secondary_surfaces.length,
    route_count: Object.keys(validated.route_templates).length,
    source_contract_count: Object.keys(validated.source_contracts).length,
    primary_action_count: validated.decision_controls.primary_actions.length,
    secondary_action_count: validated.decision_controls.secondary_actions.length,
    fetch_mode_supported: validated.client_modes.includes("fetch"),
    metadata: validated.metadata
  };
}

export function validateRepairedResponseReviewBoundary(boundary) {
  if (
    !isObject(boundary) ||
    boundary.boundary_schema_version !==
      AE_WEB_REPAIRED_RESPONSE_REVIEW_BOUNDARY_SCHEMA_VERSION
  ) {
    throw new RepairedResponseReviewBoundaryError(
      "AE Web repaired response review boundary schema version is invalid.",
      { status: "BOUNDARY_SCHEMA_VERSION_INVALID" }
    );
  }
  normalizePrimarySurface(boundary.primary_surface);
  normalizeStringSet(
    boundary.secondary_surfaces,
    SUPPORTED_SECONDARY_SURFACES,
    "secondary_surfaces"
  );
  const routes = requiredObject(boundary.route_templates, "route_templates");
  for (const [routeName, template] of Object.entries(
    REPAIRED_RESPONSE_REVIEW_ROUTE_TEMPLATES
  )) {
    if (routes[routeName] !== template) {
      throw new RepairedResponseReviewBoundaryError(
        "AE Web repaired response route template is invalid.",
        { status: "ROUTE_TEMPLATE_INVALID" }
      );
    }
  }
  const contracts = requiredObject(boundary.source_contracts, "source_contracts");
  for (const [contractName, schemaVersion] of Object.entries(SAFE_CONTRACTS)) {
    if (contracts[contractName] !== schemaVersion) {
      throw new RepairedResponseReviewBoundaryError(
        "AE Web repaired response source contract is invalid.",
        { status: "SOURCE_CONTRACT_INVALID" }
      );
    }
  }
  const controls = requiredObject(boundary.decision_controls, "decision_controls");
  const primaryActions = normalizeStringSet(
    controls.primary_actions,
    REPAIRED_RESPONSE_REVIEW_DECISION_ACTIONS,
    "primary_actions"
  );
  for (const action of REPAIRED_RESPONSE_REVIEW_DECISION_ACTIONS) {
    if (!primaryActions.includes(action)) {
      throw new RepairedResponseReviewBoundaryError(
        "AE Web repaired response primary decision actions are incomplete.",
        { status: "PRIMARY_ACTIONS_INCOMPLETE" }
      );
    }
  }
  normalizeStringSet(
    controls.secondary_actions,
    REPAIRED_RESPONSE_REVIEW_SECONDARY_ACTIONS,
    "secondary_actions"
  );
  if (controls.duplicate_submit_policy !== "disable_while_submitting") {
    throw new RepairedResponseReviewBoundaryError(
      "AE Web repaired response duplicate submit policy is invalid.",
      { status: "DUPLICATE_SUBMIT_POLICY_INVALID" }
    );
  }
  if (controls.submitter !== "chat_review") {
    throw new RepairedResponseReviewBoundaryError(
      "AE Web repaired response submitter is invalid.",
      { status: "SUBMITTER_INVALID" }
    );
  }
  normalizeStringSet(boundary.client_modes, SUPPORTED_CLIENT_MODES, "client_modes");
  const storagePolicy = requiredObject(
    boundary.browser_storage_policy,
    "browser_storage_policy"
  );
  for (const flag of [
    "stores_raw_generation_output",
    "stores_raw_prompt",
    "stores_source_text",
    "stores_service_credentials"
  ]) {
    if (storagePolicy[flag] !== false) {
      throw new RepairedResponseReviewBoundaryError(
        "AE Web repaired response browser storage policy is unsafe.",
        { status: "BROWSER_STORAGE_POLICY_UNSAFE" }
      );
    }
  }
  assertRepairedResponseReviewBoundarySafe(boundary);
  return {
    ...boundary,
    route_templates: { ...routes },
    source_contracts: { ...contracts },
    decision_controls: { ...controls },
    browser_storage_policy: { ...storagePolicy },
    metadata: { ...requiredObject(boundary.metadata, "metadata") }
  };
}

export function assertRepairedResponseReviewBoundarySafe(payload) {
  const sensitiveKeys = findSensitiveRepairedResponseReviewBoundaryKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new RepairedResponseReviewBoundaryError(
      "AE Web repaired response review boundary contains sensitive keys.",
      { status: "BOUNDARY_SENSITIVE_KEY" }
    );
  }
}

export function findSensitiveRepairedResponseReviewBoundaryKeys(payload) {
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

function isAllowedFalseSensitiveFlag(key, value) {
  return ALLOWED_FALSE_SENSITIVE_FLAGS.includes(key) && value === false;
}

function normalizePrimarySurface(value) {
  if (!SUPPORTED_PRIMARY_SURFACES.includes(value)) {
    throw new RepairedResponseReviewBoundaryError(
      "AE Web repaired response primary surface is unsupported.",
      { status: "PRIMARY_SURFACE_UNSUPPORTED" }
    );
  }
  return value;
}

function normalizeStringSet(values, allowed, fieldName) {
  if (!Array.isArray(values)) {
    throw new RepairedResponseReviewBoundaryError(`${fieldName} must be an array.`, {
      status: "STRING_SET_INVALID"
    });
  }
  const normalized = [];
  for (const value of values) {
    if (typeof value !== "string" || !allowed.includes(value)) {
      throw new RepairedResponseReviewBoundaryError(
        `${fieldName} contains an unsupported value.`,
        { status: "STRING_SET_UNSUPPORTED" }
      );
    }
    if (!normalized.includes(value)) normalized.push(value);
  }
  return normalized;
}

function requiredObject(value, fieldName) {
  if (!isObject(value)) {
    throw new RepairedResponseReviewBoundaryError(`${fieldName} must be an object.`, {
      status: "OBJECT_FIELD_INVALID"
    });
  }
  return value;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
