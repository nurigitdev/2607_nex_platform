export const AE_WEB_GROUNDED_RESPONSE_QUALITY_SURFACE_SCHEMA_VERSION =
  "ae_web_grounded_response_quality_surface.v1";

export const AE_CHAT_GROUNDED_RESPONSE_QUALITY_SCHEMA_VERSION =
  "ae_chat_grounded_response_quality.v1";

export const GROUNDED_RESPONSE_QUALITY_ACTIONS = [
  "proceed",
  "proceed_with_caveat",
  "show_error"
];

export const GROUNDED_RESPONSE_QUALITY_BOUNDARY_STATUSES = [
  "PASS",
  "WARN",
  "FAIL",
  "NOT_REQUIRED",
  "UNKNOWN"
];

const ACTION_COPY = {
  proceed: {
    title: "인용 품질 정상",
    message: "응답 인용 검증이 통과했습니다.",
    severity: "success"
  },
  proceed_with_caveat: {
    title: "인용 품질 주의",
    message: "응답 인용 또는 근거 연결 상태를 확인하세요.",
    severity: "warning"
  },
  show_error: {
    title: "인용 품질 차단",
    message: "응답 인용 품질 경계에서 생성 결과를 사용할 수 없습니다.",
    severity: "danger"
  }
};

export class GroundedResponseQualitySurfaceError extends Error {
  constructor(
    message,
    { status = "GROUNDED_RESPONSE_QUALITY_SURFACE_INVALID" } = {}
  ) {
    super(message);
    this.name = "GroundedResponseQualitySurfaceError";
    this.status = status;
  }
}

export function buildGroundedResponseQualitySurface(source = {}) {
  const quality = extractGroundedResponseQuality(source);
  const action = normalizeAction(quality?.recommended_action);
  const boundaryStatus = normalizeBoundaryStatus(quality?.boundary_status);
  const citationStatus = normalizeCitationStatus(
    quality?.citation_status,
    boundaryStatus
  );
  const issueCount = normalizeCount(quality?.issue_count);
  const groundingRequired = Boolean(quality?.grounding_required);
  const copy = ACTION_COPY[action];
  const visible =
    groundingRequired ||
    action !== "proceed" ||
    boundaryStatus === "WARN" ||
    boundaryStatus === "FAIL" ||
    issueCount > 0;

  return {
    quality_surface_schema_version:
      AE_WEB_GROUNDED_RESPONSE_QUALITY_SURFACE_SCHEMA_VERSION,
    source_schema_version:
      quality?.contract_schema_version ||
      AE_CHAT_GROUNDED_RESPONSE_QUALITY_SCHEMA_VERSION,
    source_audit_schema_version:
      typeof quality?.source_audit_schema_version === "string"
        ? quality.source_audit_schema_version
        : null,
    recommended_action: action,
    title: copy.title,
    message: copy.message,
    severity: copy.severity,
    visible,
    boundary_status: boundaryStatus,
    citation_status: citationStatus,
    issue_count: issueCount,
    grounding_required: groundingRequired,
    retrieval_package_id_present: hasText(quality?.retrieval_package_id),
    retrieval_package_hash_present: hasText(quality?.retrieval_package_hash),
    structured_draft_id_present: hasText(quality?.structured_draft_id),
    metadata: {
      rawOutputIncluded: false,
      evidenceTextIncluded: false,
      promptTextIncluded: false,
      providerDetailIncluded: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false
    }
  };
}

export function buildGroundedResponseQualitySummary(surface) {
  if (!isQualitySurface(surface)) {
    throw new GroundedResponseQualitySurfaceError(
      "Grounded response quality surface is invalid.",
      { status: "GROUNDED_RESPONSE_QUALITY_SUMMARY_INVALID" }
    );
  }

  return {
    quality_surface_schema_version: surface.quality_surface_schema_version,
    recommended_action: surface.recommended_action,
    severity: surface.severity,
    visible: surface.visible,
    boundary_status: surface.boundary_status,
    citation_status: surface.citation_status,
    issue_count: surface.issue_count,
    grounding_required: surface.grounding_required,
    retrieval_package_id_present: surface.retrieval_package_id_present,
    retrieval_package_hash_present: surface.retrieval_package_hash_present,
    structured_draft_id_present: surface.structured_draft_id_present,
    metadata: surface.metadata
  };
}

export function extractGroundedResponseQuality(source = {}) {
  if (!source || typeof source !== "object" || Array.isArray(source)) return null;
  if (
    source.contract_schema_version ===
      AE_CHAT_GROUNDED_RESPONSE_QUALITY_SCHEMA_VERSION ||
    GROUNDED_RESPONSE_QUALITY_ACTIONS.includes(source.recommended_action)
  ) {
    return source;
  }
  if (isQualityContract(source.groundedResponseQuality)) {
    return source.groundedResponseQuality;
  }
  if (isQualityContract(source.grounded_response_quality)) {
    return source.grounded_response_quality;
  }
  if (isQualityContract(source.generation?.groundedResponseQuality)) {
    return source.generation.groundedResponseQuality;
  }
  if (isQualityContract(source.generation?.grounded_response_quality)) {
    return source.generation.grounded_response_quality;
  }
  if (isQualityContract(source.chatInteraction?.generation?.grounded_response_quality)) {
    return source.chatInteraction.generation.grounded_response_quality;
  }
  return buildFallbackGroundedResponseQuality(source);
}

function buildFallbackGroundedResponseQuality(source) {
  const qualitySummary = source.qualitySummary || source.quality_summary || null;
  if (qualitySummary && typeof qualitySummary === "object") {
    const groundingRequired = Boolean(
      qualitySummary.groundingRequired || qualitySummary.grounding_required
    );
    const citationStatus =
      qualitySummary.citationStatus || qualitySummary.citation_status;
    return {
      contract_schema_version: AE_CHAT_GROUNDED_RESPONSE_QUALITY_SCHEMA_VERSION,
      source_audit_schema_version: null,
      boundary_status:
        citationStatus === "VALIDATED"
          ? "PASS"
          : groundingRequired
            ? "UNKNOWN"
            : "NOT_REQUIRED",
      citation_status: citationStatus,
      issue_count: 0,
      recommended_action:
        citationStatus === "VALIDATED" || !groundingRequired
          ? "proceed"
          : "proceed_with_caveat",
      grounding_required: groundingRequired,
      retrieval_package_id: null,
      retrieval_package_hash: null,
      structured_draft_id: null,
      raw_output_included: false,
      evidence_text_included: false,
      prompt_text_included: false,
      provider_detail_included: false
    };
  }
  return null;
}

function isQualitySurface(value) {
  return (
    value &&
    value.quality_surface_schema_version ===
      AE_WEB_GROUNDED_RESPONSE_QUALITY_SURFACE_SCHEMA_VERSION &&
    GROUNDED_RESPONSE_QUALITY_ACTIONS.includes(value.recommended_action) &&
    GROUNDED_RESPONSE_QUALITY_BOUNDARY_STATUSES.includes(value.boundary_status)
  );
}

function isQualityContract(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeAction(action) {
  if (GROUNDED_RESPONSE_QUALITY_ACTIONS.includes(action)) return action;
  return "proceed";
}

function normalizeBoundaryStatus(status) {
  if (GROUNDED_RESPONSE_QUALITY_BOUNDARY_STATUSES.includes(status)) return status;
  return "NOT_REQUIRED";
}

function normalizeCitationStatus(status, boundaryStatus) {
  if (["VALIDATED", "INVALID", "NOT_REQUIRED", "UNKNOWN"].includes(status)) {
    return status;
  }
  if (boundaryStatus === "NOT_REQUIRED") return "NOT_REQUIRED";
  return "UNKNOWN";
}

function normalizeCount(value) {
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function hasText(value) {
  return typeof value === "string" && value.trim().length > 0;
}
