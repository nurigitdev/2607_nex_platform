export const AE_PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION =
  "p8.project_membership_batch_result_projection.v1";

const OUTCOME_LABELS = {
  ADDED: "추가됨",
  REACTIVATED: "다시 활성화됨",
  ALREADY_ACTIVE: "이미 참여 중",
  SUBJECT_INACTIVE: "비활성 직원",
  ROLE_CONFLICT: "기존 역할과 충돌",
  NOT_ELIGIBLE: "프로젝트 참여 불가",
  INVALID_EMPLOYEE_ID: "사번 형식 오류",
  EMPLOYEE_NOT_FOUND: "직원을 찾을 수 없음",
  NAME_MISMATCH: "사번과 이름 불일치",
  DUPLICATE_INPUT: "중복 입력",
  DUPLICATE_SUBJECT: "동일 직원 중복"
};

const FORBIDDEN_KEYS = new Set([
  "api_key",
  "authorization",
  "credential",
  "database_url",
  "password",
  "provider_endpoint",
  "raw_prompt",
  "service_token"
]);

export class ProjectMembershipBatchResultError extends Error {
  constructor(message, { status = "PROJECT_MEMBERSHIP_BATCH_RESULT_INVALID" } = {}) {
    super(message);
    this.name = "ProjectMembershipBatchResultError";
    this.status = status;
  }
}

export function buildProjectMembershipBatchResultSurface(projection) {
  if (
    !projection ||
    Array.isArray(projection) ||
    projection.schema_version !== AE_PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION ||
    projection.operation_id !== "PROJECT.MEMBERSHIP.ADD_MANY"
  ) {
    throw new ProjectMembershipBatchResultError("Batch result projection is invalid.");
  }
  assertSafe(projection);
  const summary = requiredObject(projection.summary, "summary");
  const items = requiredArray(projection.items, "items").map((item, index) => {
    const record = requiredObject(item, `items[${index}]`);
    const outcome = requiredText(record.outcome, `items[${index}].outcome`);
    if (!(outcome in OUTCOME_LABELS)) {
      throw new ProjectMembershipBatchResultError("Batch result outcome is unsupported.");
    }
    return Object.freeze({
      stage: requiredText(record.stage, `items[${index}].stage`),
      inputIndex: optionalInteger(record.input_index),
      subjectId: optionalText(record.subject_id),
      employeeId: optionalText(record.normalized_employee_id),
      outcome,
      outcomeLabel: OUTCOME_LABELS[outcome],
      applied: record.applied === true
    });
  });
  const requestedCount = nonNegativeInteger(summary.requested_count, "requested_count");
  const appliedCount = nonNegativeInteger(summary.applied_count, "applied_count");
  const rejectedCount = nonNegativeInteger(
    summary.total_rejected_count,
    "total_rejected_count"
  );
  if (requestedCount !== items.length || requestedCount !== appliedCount + rejectedCount) {
    throw new ProjectMembershipBatchResultError("Batch result counts are inconsistent.");
  }
  return Object.freeze({
    schemaVersion: projection.schema_version,
    operationId: projection.operation_id,
    projectId: requiredText(projection.project_id, "project_id"),
    memberRole: requiredText(projection.member_role, "member_role"),
    overallStatus: requiredText(projection.overall_status, "overall_status"),
    businessResultRef: requiredText(
      projection.business_result_ref,
      "business_result_ref"
    ),
    requestedCount,
    admittedCount: nonNegativeInteger(summary.admitted_count, "admitted_count"),
    appliedCount,
    rejectedCount,
    items,
    metadata: Object.freeze({
      rawPromptIncluded: false,
      credentialsIncluded: false,
      providerConfigurationIncluded: false,
      modelAuthority: false
    })
  });
}

function assertSafe(value) {
  if (Array.isArray(value)) {
    value.forEach(assertSafe);
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, item] of Object.entries(value)) {
    if (FORBIDDEN_KEYS.has(String(key).toLowerCase())) {
      throw new ProjectMembershipBatchResultError("Batch result contains private data.");
    }
    assertSafe(item);
  }
}

function requiredObject(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ProjectMembershipBatchResultError(`${field} must be an object.`);
  }
  return value;
}
function requiredArray(value, field) {
  if (!Array.isArray(value)) {
    throw new ProjectMembershipBatchResultError(`${field} must be an array.`);
  }
  return value;
}

function requiredText(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new ProjectMembershipBatchResultError(`${field} must be text.`);
  }
  return value.trim();
}

function optionalText(value) {
  return value == null ? null : requiredText(value, "optional text");
}

function optionalInteger(value) {
  if (value == null) return null;
  return nonNegativeInteger(value, "optional integer");
}

function nonNegativeInteger(value, field) {
  if (!Number.isInteger(value) || value < 0) {
    throw new ProjectMembershipBatchResultError(`${field} must be non-negative.`);
  }
  return value;
}
