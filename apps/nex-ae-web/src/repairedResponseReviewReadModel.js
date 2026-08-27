import {
  buildRepairedResponseReviewCardSummary
} from "./repairedResponseReviewCard.js";

export const AE_WEB_REPAIRED_RESPONSE_REVIEW_READ_MODEL_SCHEMA_VERSION =
  "ae_web_repaired_response_review_read_model.v1";

export const REPAIRED_RESPONSE_REVIEW_FILTERS = [
  "all",
  "actionable",
  "ready",
  "submitting",
  "recorded",
  "failed"
];

const TERMINAL_DECISION_STATUSES = new Set(["RECORDED", "ACCEPTED", "KEPT"]);

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
  "rawPromptRendered",
  "rawGenerationOutputRendered",
  "rawSourceRendered",
  "serviceTokenRendered",
  "databaseEndpointRendered",
  "providerEndpointRendered",
  "storageLocationRendered"
];

export class RepairedResponseReviewReadModelError extends Error {
  constructor(
    message,
    { status = "REPAIRED_RESPONSE_REVIEW_READ_MODEL_INVALID" } = {}
  ) {
    super(message);
    this.name = "RepairedResponseReviewReadModelError";
    this.status = status;
  }
}

export function buildRepairedResponseReviewReadModel(
  source,
  { filter = "all", selectedHandoffId = null, decisionEnabled = true } = {}
) {
  const filterMode = normalizeFilter(filter);
  const selectedId = optionalText(selectedHandoffId);
  const items = normalizeReviewItems(source).map((surface, index) =>
    buildReadModelItem(surface, {
      index,
      selectedHandoffId: selectedId,
      decisionEnabled
    })
  );
  const filteredItems = filterReadModelItems(items, filterMode);
  const decisionStatusCounts = countBy(items, item => item.decisionStatus);
  const model = {
    read_model_schema_version:
      AE_WEB_REPAIRED_RESPONSE_REVIEW_READ_MODEL_SCHEMA_VERSION,
    filter: filterMode,
    selected_handoff_id: selectedId,
    total_count: items.length,
    filtered_count: filteredItems.length,
    actionable_count: items.filter(item => item.actionable).length,
    terminal_count: items.filter(item => item.terminal).length,
    failed_count: items.filter(item => item.decisionStatus === "FAILED").length,
    selected_index: items.findIndex(item => item.selected),
    decision_status_counts: decisionStatusCounts,
    items: filteredItems,
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
  assertRepairedResponseReviewReadModelSafe(model);
  return model;
}

export function filterRepairedResponseReviewReadModel(readModel, filter) {
  const validated = validateRepairedResponseReviewReadModel(readModel);
  return {
    ...validated,
    filter: normalizeFilter(filter),
    filtered_count: filterReadModelItems(validated.items, normalizeFilter(filter))
      .length,
    items: filterReadModelItems(validated.items, normalizeFilter(filter))
  };
}

export function buildRepairedResponseReviewReadModelSummary(readModel) {
  const validated = validateRepairedResponseReviewReadModel(readModel);
  return {
    read_model_schema_version: validated.read_model_schema_version,
    filter: validated.filter,
    total_count: validated.total_count,
    filtered_count: validated.filtered_count,
    actionable_count: validated.actionable_count,
    terminal_count: validated.terminal_count,
    failed_count: validated.failed_count,
    selected_handoff_id: validated.selected_handoff_id,
    selected_index: validated.selected_index,
    decision_status_counts: { ...validated.decision_status_counts },
    metadata: { ...validated.metadata }
  };
}

export function validateRepairedResponseReviewReadModel(readModel) {
  if (
    !isObject(readModel) ||
    readModel.read_model_schema_version !==
      AE_WEB_REPAIRED_RESPONSE_REVIEW_READ_MODEL_SCHEMA_VERSION ||
    !Array.isArray(readModel.items)
  ) {
    throw new RepairedResponseReviewReadModelError(
      "AE Web repaired response review read model is invalid.",
      { status: "READ_MODEL_INVALID" }
    );
  }
  assertRepairedResponseReviewReadModelSafe(readModel);
  return readModel;
}

export function assertRepairedResponseReviewReadModelSafe(payload) {
  const sensitiveKeys = findSensitiveRepairedResponseReviewReadModelKeys(payload);
  if (sensitiveKeys.length > 0) {
    throw new RepairedResponseReviewReadModelError(
      "AE Web repaired response review read model contains sensitive keys.",
      { status: "READ_MODEL_SENSITIVE_KEY" }
    );
  }
}

export function findSensitiveRepairedResponseReviewReadModelKeys(payload) {
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

function buildReadModelItem(
  surface,
  { index, selectedHandoffId, decisionEnabled }
) {
  const summary = buildRepairedResponseReviewCardSummary(surface, {
    decisionEnabled,
    decisionState: surface.decisionState
  });
  const decisionStatus = summary.decision_status;
  const terminal = TERMINAL_DECISION_STATUSES.has(decisionStatus);
  return {
    index,
    repaired_response_handoff_id: summary.repaired_response_handoff_id,
    interaction_id: summary.interaction_id,
    projection_status: summary.projection_status,
    repaired_status: summary.repaired_status,
    lineage_status: summary.lineage_status,
    decision_status: decisionStatus,
    decisionStatus,
    enabled_action_count: summary.enabled_action_count,
    actionable: summary.enabled_action_count > 0 && !terminal,
    terminal,
    selected:
      selectedHandoffId != null &&
      selectedHandoffId === summary.repaired_response_handoff_id,
    client_mode: summary.client_mode
  };
}

function normalizeReviewItems(source) {
  if (Array.isArray(source)) return source;
  if (isObject(source) && Array.isArray(source.items)) return source.items;
  throw new RepairedResponseReviewReadModelError(
    "AE Web repaired response review items are invalid.",
    { status: "READ_MODEL_ITEMS_INVALID" }
  );
}

function filterReadModelItems(items, filterMode) {
  if (filterMode === "all") return items.map(item => ({ ...item }));
  if (filterMode === "actionable") {
    return items.filter(item => item.actionable).map(item => ({ ...item }));
  }
  if (filterMode === "ready") {
    return items
      .filter(item => item.decisionStatus === "READY_FOR_DECISION")
      .map(item => ({ ...item }));
  }
  if (filterMode === "submitting") {
    return items
      .filter(item => item.decisionStatus === "SUBMITTING")
      .map(item => ({ ...item }));
  }
  if (filterMode === "recorded") {
    return items
      .filter(item => TERMINAL_DECISION_STATUSES.has(item.decisionStatus))
      .map(item => ({ ...item }));
  }
  return items
    .filter(item => item.decisionStatus === "FAILED")
    .map(item => ({ ...item }));
}

function countBy(items, selectKey) {
  return items.reduce((counts, item) => {
    const key = selectKey(item);
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
}

function normalizeFilter(filter) {
  const value = optionalText(filter) || "all";
  return REPAIRED_RESPONSE_REVIEW_FILTERS.includes(value) ? value : "all";
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
