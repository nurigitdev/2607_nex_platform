export const AE_WEB_RETRIEVAL_QUALITY_WARNING_SURFACE_SCHEMA_VERSION =
  "ae_web_retrieval_quality_warning_surface.v1";

export const AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION =
  "ae_chat_retrieval_quality_warning.v1";

export const RETRIEVAL_QUALITY_WARNING_ACTIONS = [
  "proceed",
  "proceed_with_caveat",
  "ask_confirmation",
  "show_no_answer",
  "show_error"
];

const ACTION_COPY = {
  proceed: {
    title: "검색 품질 정상",
    message: "검색 품질 경고가 없습니다.",
    severity: "success",
    visible: false
  },
  proceed_with_caveat: {
    title: "검색 품질 주의",
    message: "검색 결과에 주의할 점이 있습니다. 근거와 함께 확인하세요.",
    severity: "warning",
    visible: true
  },
  ask_confirmation: {
    title: "검색 품질 확인 필요",
    message: "근거 신뢰도가 낮습니다. 문서 범위와 점수를 확인하세요.",
    severity: "warning",
    visible: true
  },
  show_no_answer: {
    title: "근거 부족",
    message: "선택 범위에서 충분한 근거를 찾지 못했습니다.",
    severity: "pending",
    visible: true
  },
  show_error: {
    title: "검색 품질 차단",
    message: "검색 품질 경계에서 생성이 차단되었습니다.",
    severity: "danger",
    visible: true
  }
};

export class RetrievalQualityWarningSurfaceError extends Error {
  constructor(message, { status = "RETRIEVAL_QUALITY_WARNING_SURFACE_INVALID" } = {}) {
    super(message);
    this.name = "RetrievalQualityWarningSurfaceError";
    this.status = status;
  }
}

export function buildRetrievalQualityWarningSurface(source = {}) {
  const qualityWarnings = extractRetrievalQualityWarnings(source);
  const action = normalizeAction(qualityWarnings?.recommended_action);
  const copy = ACTION_COPY[action];
  const warningKinds = normalizeKinds(qualityWarnings?.warning_kinds);
  const qualityFlagKinds = normalizeKinds(qualityWarnings?.quality_flag_kinds);
  const warningCount = normalizeCount(
    qualityWarnings?.warning_count,
    warningKinds.length
  );
  const qualityFlagCount = normalizeCount(
    qualityWarnings?.quality_flag_count,
    qualityFlagKinds.length
  );
  const visible =
    copy.visible ||
    warningCount > 0 ||
    qualityFlagCount > 0 ||
    Boolean(qualityWarnings?.best_score_below_threshold) ||
    Boolean(qualityWarnings?.status_caveat_required);

  return {
    warning_surface_schema_version:
      AE_WEB_RETRIEVAL_QUALITY_WARNING_SURFACE_SCHEMA_VERSION,
    source_schema_version:
      qualityWarnings?.contract_schema_version ||
      AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION,
    recommended_action: action,
    title: copy.title,
    message: copy.message,
    severity: copy.severity,
    visible,
    warning_count: warningCount,
    warning_kinds: warningKinds,
    quality_flag_count: qualityFlagCount,
    quality_flag_kinds: qualityFlagKinds,
    low_confidence_threshold: normalizeThreshold(
      qualityWarnings?.low_confidence_threshold
    ),
    best_score_below_threshold: Boolean(
      qualityWarnings?.best_score_below_threshold
    ),
    status_caveat_required: Boolean(qualityWarnings?.status_caveat_required),
    metadata: {
      rawWarningDetailsIncluded: false,
      rawPromptRendered: false,
      rawSourceIncluded: false,
      browserServiceTokenIncluded: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false
    }
  };
}

export function buildRetrievalQualityWarningSummary(surface) {
  if (!isWarningSurface(surface)) {
    throw new RetrievalQualityWarningSurfaceError(
      "Retrieval quality warning surface is invalid.",
      { status: "RETRIEVAL_QUALITY_WARNING_SUMMARY_INVALID" }
    );
  }

  return {
    warning_surface_schema_version: surface.warning_surface_schema_version,
    recommended_action: surface.recommended_action,
    severity: surface.severity,
    visible: surface.visible,
    warning_count: surface.warning_count,
    warning_kinds: surface.warning_kinds,
    quality_flag_count: surface.quality_flag_count,
    quality_flag_kinds: surface.quality_flag_kinds,
    low_confidence_threshold: surface.low_confidence_threshold,
    best_score_below_threshold: surface.best_score_below_threshold,
    status_caveat_required: surface.status_caveat_required,
    metadata: surface.metadata
  };
}

export function extractRetrievalQualityWarnings(source = {}) {
  if (!source || typeof source !== "object" || Array.isArray(source)) return null;
  if (
    source.contract_schema_version ===
      AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION ||
    RETRIEVAL_QUALITY_WARNING_ACTIONS.includes(source.recommended_action)
  ) {
    return source;
  }
  if (isQualityWarnings(source.qualityWarnings)) return source.qualityWarnings;
  if (isQualityWarnings(source.retrievalQualityWarnings)) {
    return source.retrievalQualityWarnings;
  }
  if (isQualityWarnings(source.quality_warnings)) return source.quality_warnings;
  if (isQualityWarnings(source.retrieval?.quality_warnings)) {
    return source.retrieval.quality_warnings;
  }
  if (isQualityWarnings(source.retrieval?.qualityWarnings)) {
    return source.retrieval.qualityWarnings;
  }
  if (isQualityWarnings(source.retrievalResult?.qualityWarnings)) {
    return source.retrievalResult.qualityWarnings;
  }
  return buildFallbackQualityWarnings(source);
}

function isWarningSurface(value) {
  return (
    value &&
    value.warning_surface_schema_version ===
      AE_WEB_RETRIEVAL_QUALITY_WARNING_SURFACE_SCHEMA_VERSION &&
    RETRIEVAL_QUALITY_WARNING_ACTIONS.includes(value.recommended_action)
  );
}

function isQualityWarnings(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function buildFallbackQualityWarnings(source) {
  const warningKinds = [
    ...normalizeKinds(source.warnings),
    ...normalizeKinds(source.retrieval?.warnings)
  ];
  if (warningKinds.length > 0) {
    return {
      contract_schema_version: AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION,
      warning_count: warningKinds.length,
      warning_kinds: warningKinds,
      quality_flag_count: 0,
      quality_flag_kinds: [],
      low_confidence_threshold: null,
      best_score_below_threshold: false,
      status_caveat_required: true,
      recommended_action: "proceed_with_caveat",
      raw_warning_details_included: false
    };
  }

  const status = source.cxStatus || source.cx_status || source.status;
  if (status === "NO_ANSWER") {
    return {
      contract_schema_version: AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION,
      warning_count: 0,
      warning_kinds: [],
      quality_flag_count: 0,
      quality_flag_kinds: [],
      low_confidence_threshold: null,
      best_score_below_threshold: false,
      status_caveat_required: true,
      recommended_action: "show_no_answer",
      raw_warning_details_included: false
    };
  }

  if (status === "FAILED" || status === "UNAVAILABLE") {
    return {
      contract_schema_version: AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION,
      warning_count: 0,
      warning_kinds: [],
      quality_flag_count: 0,
      quality_flag_kinds: [],
      low_confidence_threshold: null,
      best_score_below_threshold: false,
      status_caveat_required: true,
      recommended_action: "show_error",
      raw_warning_details_included: false
    };
  }

  return null;
}

function normalizeAction(action) {
  if (RETRIEVAL_QUALITY_WARNING_ACTIONS.includes(action)) return action;
  return "proceed";
}

function normalizeKinds(kinds) {
  if (!Array.isArray(kinds)) return [];
  const normalized = [];
  for (const kind of kinds) {
    const value = normalizeKind(kind);
    if (value && !normalized.includes(value)) {
      normalized.push(value);
    }
  }
  return normalized;
}

function normalizeKind(kind) {
  if (typeof kind !== "string") return "";
  return kind.split(":", 1)[0].trim();
}

function normalizeCount(value, fallback) {
  return Number.isInteger(value) && value >= 0 ? value : fallback;
}

function normalizeThreshold(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}
