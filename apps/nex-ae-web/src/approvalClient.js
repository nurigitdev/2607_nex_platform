export const WC_APPROVAL_INBOX_SCHEMA_VERSION = "wc_approval_inbox.v1";
export const WC_APPROVAL_GATE_DETAIL_SCHEMA_VERSION =
  "wc_approval_gate_detail.v1";
export const WC_APPROVAL_DECISION_REQUEST_SCHEMA_VERSION =
  "wc_approval_decision_request.v1";
export const HUMAN_GATE_VIEW_SCHEMA_VERSION = "human_gate_view.p8.v1";

export const APPROVAL_DOMAINS = [
  "NSL_WRITE",
  "AGENT_FORMAL",
  "BUSINESS_FORMAL"
];

const GATE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DECISIONS = new Set(["APPROVE", "REJECT"]);
const HASH_REF = /^sha256:[0-9a-f]{64}$/;
const SENSITIVE_KEY_PARTS = [
  "access_token",
  "api_key",
  "authorization_header",
  "credential",
  "database_url",
  "password",
  "protected_request",
  "raw_payload",
  "raw_authorization",
  "raw_prompt",
  "resume_target_ref",
  "semantic_hash",
  "service_token",
  "source_ref",
  "storage_path"
];

export class ApprovalClientError extends Error {
  constructor(
    message,
    { status = "APPROVAL_CLIENT_ERROR", httpStatus = 0, retryable = false } = {}
  ) {
    super(message);
    this.name = "ApprovalClientError";
    this.status = status;
    this.httpStatus = httpStatus;
    this.retryable = retryable;
  }
}

export function approvalInboxRoute(limit = 50) {
  const admitted = boundedLimit(limit);
  return `/api/v1/approval-gates?limit=${admitted}`;
}

export function approvalGateRoute(gateId) {
  return `/api/v1/approval-gates/${encodeURIComponent(requiredGateId(gateId))}`;
}

export function approvalDecisionRoute(gateId) {
  return `${approvalGateRoute(gateId)}/decisions`;
}

export function buildApprovalDecisionRequest({
  decision,
  decisionComment = null,
  correlationId = null,
  causationId = null
} = {}) {
  if (!DECISIONS.has(decision)) {
    throw new ApprovalClientError("Approval decision action is invalid.", {
      status: "APPROVAL_DECISION_INVALID"
    });
  }
  const comment = optionalText(decisionComment);
  if (comment != null && comment.length > 2000) {
    throw new ApprovalClientError("Approval decision comment is too long.", {
      status: "APPROVAL_DECISION_COMMENT_INVALID"
    });
  }
  return {
    schema_version: WC_APPROVAL_DECISION_REQUEST_SCHEMA_VERSION,
    decision,
    decision_comment: comment,
    correlation_id: optionalText(correlationId),
    causation_id: optionalText(causationId)
  };
}

export function createFetchApprovalClient({ baseUrl = "", fetchImpl } = {}) {
  const request = requiredFetch(fetchImpl);
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  return {
    clientMode: "fetch",
    async listApprovalGates({ limit = 50 } = {}) {
      const route = approvalInboxRoute(limit);
      const payload = await fetchJson(request, `${normalizedBaseUrl}${route}`);
      return normalizeApprovalInbox(payload, { clientMode: "fetch", route });
    },
    async getApprovalGate(gateId) {
      const route = approvalGateRoute(gateId);
      const payload = await fetchJson(request, `${normalizedBaseUrl}${route}`);
      return normalizeApprovalGateDetail(payload, { clientMode: "fetch", route });
    },
    async submitApprovalDecision(gateId, requestPayload) {
      const route = approvalDecisionRoute(gateId);
      const payload = await fetchJson(request, `${normalizedBaseUrl}${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(normalizeDecisionRequest(requestPayload))
      });
      return normalizeApprovalDecision(payload, { clientMode: "fetch", route });
    }
  };
}

export function createMockApprovalClient({
  inbox = buildDefaultMockApprovalInbox(),
  deniedGateIds = ["42000000-0000-4000-8000-000000000002"],
  now = () => new Date(),
  decisionDelayMs = 0
} = {}) {
  const initial = normalizeApprovalInbox(inbox, {
    clientMode: "mock",
    route: approvalInboxRoute(inbox.limit || 50)
  });
  const records = new Map(initial.gates.map(gate => [gate.gate_id, structuredClone(gate)]));
  const decisions = new Map();
  const denied = new Set(deniedGateIds);
  let decisionCallCount = 0;

  return {
    clientMode: "mock",
    async listApprovalGates({ limit = 50 } = {}) {
      const admitted = boundedLimit(limit);
      const gates = [...records.values()]
        .filter(gate => gate.state === "PENDING")
        .slice(0, admitted)
        .map(gate => structuredClone(gate));
      return normalizeApprovalInbox(
        {
          ...initial,
          gates,
          returned_count: gates.length,
          limit: admitted
        },
        { clientMode: "mock", route: approvalInboxRoute(admitted) }
      );
    },
    async getApprovalGate(gateId) {
      const admittedId = requiredGateId(gateId);
      const gate = records.get(admittedId);
      if (!gate) {
        throw new ApprovalClientError("Approval gate was not found.", {
          status: "APPROVAL_GATE_NOT_FOUND",
          httpStatus: 404
        });
      }
      return normalizeApprovalGateDetail(
        {
          schema_version: WC_APPROVAL_GATE_DETAIL_SCHEMA_VERSION,
          gate: structuredClone(gate),
          created_at: "2026-10-22T08:00:00Z",
          version: 1,
          decision_options: ["APPROVE", "REJECT"]
        },
        { clientMode: "mock", route: approvalGateRoute(admittedId) }
      );
    },
    async submitApprovalDecision(gateId, requestPayload) {
      decisionCallCount += 1;
      const admittedId = requiredGateId(gateId);
      const request = normalizeDecisionRequest(requestPayload);
      const gate = records.get(admittedId);
      if (!gate) {
        throw new ApprovalClientError("Approval gate was not found.", {
          status: "APPROVAL_GATE_NOT_FOUND",
          httpStatus: 404
        });
      }
      if (decisionDelayMs > 0) {
        await new Promise(resolve => setTimeout(resolve, decisionDelayMs));
      }
      if (denied.has(admittedId)) {
        throw new ApprovalClientError("Current approval authority was denied.", {
          status: "APPROVAL_DECISION_UNAUTHORIZED",
          httpStatus: 403
        });
      }
      if (isApprovalGateExpired(gate, now())) {
        throw new ApprovalClientError("Approval gate has expired.", {
          status: "APPROVAL_EXPIRED",
          httpStatus: 409
        });
      }
      const existing = decisions.get(admittedId);
      if (existing) {
        if (existing.decision !== request.decision) {
          throw new ApprovalClientError("Approval decision conflicts with terminal state.", {
            status: "APPROVAL_DECISION_CONFLICT",
            httpStatus: 409
          });
        }
        return structuredClone(existing);
      }
      const decision = normalizeApprovalDecision(
        {
          schema_version: "wc_approval_decision.v1",
          tenant_id: initial.tenant_id,
          decision_id: mockDecisionId(admittedId),
          approval_work_item_id: admittedId,
          decision: request.decision,
          decided_by: initial.subject_ref.id,
          decision_comment: request.decision_comment,
          decision_version: 1,
          authorized_by_oa: true,
          oa_decision_ref: `oa-decision-${admittedId.slice(0, 8)}`,
          authorization_revision_hash: `sha256:${"a".repeat(64)}`,
          authorization_checked_at: "2026-10-22T09:00:00Z",
          decided_at: "2026-10-22T09:00:00Z"
        },
        { clientMode: "mock", route: approvalDecisionRoute(admittedId) }
      );
      decisions.set(admittedId, decision);
      const terminalState =
        request.decision === "APPROVE" ? "APPROVED" : "REJECTED";
      records.set(admittedId, {
        ...gate,
        state: terminalState,
        ...(gate.formal_approval
          ? {
              formal_approval: {
                ...gate.formal_approval,
                terminal_state: terminalState
              }
            }
          : {})
      });
      return structuredClone(decision);
    },
    getDecisionCallCount() {
      return decisionCallCount;
    }
  };
}

export function normalizeApprovalInbox(payload, { clientMode, route } = {}) {
  if (
    !isObject(payload) ||
    payload.schema_version !== WC_APPROVAL_INBOX_SCHEMA_VERSION ||
    !Array.isArray(payload.gates) ||
    payload.returned_count !== payload.gates.length
  ) {
    throw new ApprovalClientError("Approval inbox response is invalid.", {
      status: "APPROVAL_INBOX_INVALID"
    });
  }
  assertApprovalPayloadSafe(payload);
  const gates = payload.gates.map(normalizeHumanGate);
  return {
    schema_version: payload.schema_version,
    tenant_id: requiredText(payload.tenant_id, "tenant_id"),
    subject_ref: normalizeSubjectRef(payload.subject_ref),
    gates,
    returned_count: gates.length,
    limit: boundedLimit(payload.limit),
    scan_truncated: Boolean(payload.scan_truncated),
    client_mode: clientMode || "unknown",
    route: route || approvalInboxRoute(payload.limit)
  };
}

export function normalizeApprovalGateDetail(payload, { clientMode, route } = {}) {
  if (
    !isObject(payload) ||
    payload.schema_version !== WC_APPROVAL_GATE_DETAIL_SCHEMA_VERSION ||
    !Array.isArray(payload.decision_options) ||
    payload.decision_options.join(",") !== "APPROVE,REJECT"
  ) {
    throw new ApprovalClientError("Approval gate detail is invalid.", {
      status: "APPROVAL_GATE_DETAIL_INVALID"
    });
  }
  assertApprovalPayloadSafe(payload);
  const gate = normalizeHumanGate(payload.gate);
  return {
    schema_version: payload.schema_version,
    gate,
    created_at: requiredText(payload.created_at, "created_at"),
    version: positiveInteger(payload.version, "version"),
    decision_options: ["APPROVE", "REJECT"],
    client_mode: clientMode || "unknown",
    route: route || approvalGateRoute(gate.gate_id)
  };
}

export function normalizeApprovalDecision(payload, { clientMode, route } = {}) {
  if (
    !isObject(payload) ||
    payload.schema_version !== "wc_approval_decision.v1" ||
    !DECISIONS.has(payload.decision) ||
    payload.authorized_by_oa !== true
  ) {
    throw new ApprovalClientError("Approval decision response is invalid.", {
      status: "APPROVAL_DECISION_RESPONSE_INVALID"
    });
  }
  assertApprovalPayloadSafe(payload);
  return {
    schema_version: payload.schema_version,
    tenant_id: requiredText(payload.tenant_id, "tenant_id"),
    decision_id: requiredGateId(payload.decision_id),
    approval_work_item_id: requiredGateId(payload.approval_work_item_id),
    decision: payload.decision,
    decided_by: requiredText(payload.decided_by, "decided_by"),
    decision_comment: optionalText(payload.decision_comment),
    decision_version: positiveInteger(payload.decision_version, "decision_version"),
    authorized_by_oa: true,
    decided_at: requiredText(payload.decided_at, "decided_at"),
    client_mode: clientMode || "unknown",
    route: route || approvalDecisionRoute(payload.approval_work_item_id)
  };
}

export function isApprovalGateExpired(gate, now = new Date()) {
  if (!gate?.expires_at) return false;
  const expiresAt = new Date(gate.expires_at);
  return !Number.isNaN(expiresAt.valueOf()) && expiresAt <= now;
}

export function assertApprovalPayloadSafe(payload) {
  const found = [];
  visitObject(payload, "", found);
  if (found.length > 0) {
    throw new ApprovalClientError("Approval payload contains protected fields.", {
      status: "APPROVAL_PAYLOAD_UNSAFE"
    });
  }
}

export function buildDefaultMockApprovalInbox() {
  const gates = [
    mockGate({
      gateId: "42000000-0000-4000-8000-000000000001",
      domain: "NSL_WRITE",
      title: "보호된 WRITE 승인",
      summary: "검증된 NSL 계획의 전표 초안 생성을 승인합니다.",
      provider: "NSL",
      target: "approval-request-p8-s42",
      operationId: "business-operation-p8-s42",
      attachmentManifest: mockAttachmentReviewManifest(
        "42000000-0000-4000-8000-000000000001"
      )
    }),
    mockGate({
      gateId: "42000000-0000-4000-8000-000000000002",
      domain: "AGENT_FORMAL",
      title: "Agent 공식 작업 승인",
      summary: "IA가 제안한 공식 작업 실행 범위를 검토합니다.",
      provider: "AGENT",
      target: "agent-formal-p8-s42"
    }),
    mockGate({
      gateId: "42000000-0000-4000-8000-000000000003",
      domain: "BUSINESS_FORMAL",
      title: "업무 결재 검토",
      summary: "EOS 업무 규칙에 따른 재무 결재 단계를 검토합니다.",
      provider: "EOS",
      target: "eos-stage-p8-s42",
      operationId: "business-operation-p8-s42",
      attachmentManifest: mockAttachmentReviewManifest(
        "42000000-0000-4000-8000-000000000003"
      ),
      formalApproval: {
        currentStage: 1,
        stageCount: 2,
        requestedRole: "TEAM_LEAD",
        orgUnitId: "org-finance",
        projectId: "project-p8-s42"
      }
    }),
    mockGate({
      gateId: "42000000-0000-4000-8000-000000000004",
      domain: "NSL_WRITE",
      title: "만료된 WRITE 승인",
      summary: "기한이 지난 요청은 승인하거나 반려할 수 없습니다.",
      provider: "NSL",
      target: "approval-request-expired-p8-s42",
      expiresAt: "2020-01-01T00:00:00Z"
    })
  ];
  return {
    schema_version: WC_APPROVAL_INBOX_SCHEMA_VERSION,
    tenant_id: "tenant-local",
    subject_ref: { type: "oa.user", id: "owner-local" },
    gates,
    returned_count: gates.length,
    limit: 50,
    scan_truncated: false
  };
}

function mockGate({
  gateId,
  domain,
  title,
  summary,
  provider,
  target,
  operationId = null,
  formalApproval = null,
  attachmentManifest = null,
  expiresAt = "2099-10-23T09:00:00Z"
}) {
  const gate = {
    schema_version: HUMAN_GATE_VIEW_SCHEMA_VERSION,
    gate_id: gateId,
    approval_domain: domain,
    state: "PENDING",
    title,
    summary,
    action_ref: approvalGateRoute(gateId),
    approval_provider_type: provider,
    approval_target_ref: target,
    business_operation_id: operationId,
    expires_at: expiresAt
  };
  if (formalApproval) {
    gate.formal_approval = {
      schema_version: "business_formal_gate_view.p8.v1",
      current_stage: formalApproval.currentStage,
      stage_count: formalApproval.stageCount,
      requested_role: formalApproval.requestedRole,
      eos_target_ref: target,
      org_unit_id: formalApproval.orgUnitId,
      project_id: formalApproval.projectId,
      terminal_state: null
    };
  }
  if (attachmentManifest) {
    gate.attachment_manifest = attachmentManifest;
  }
  return gate;
}

function mockAttachmentReviewManifest(gateId) {
  const batchId = "75a70000-0000-4000-8000-000000000001";
  const items = [
    {
      attachment_id: "75a70000-0000-4000-8000-000000000002",
      display_name: "교통비-영수증.png",
      media_type: "image/png",
      size_bytes: 184320
    },
    {
      attachment_id: "75a70000-0000-4000-8000-000000000003",
      display_name: "출장비-내역.pdf",
      media_type: "application/pdf",
      size_bytes: 348160
    }
  ].map(item => ({
    ...item,
    content_route: `/api/v1/approval-gates/${gateId}/attachments/${item.attachment_id}/content?download=false`,
    download_route: `/api/v1/approval-gates/${gateId}/attachments/${item.attachment_id}/content?download=true`
  }));
  return {
    schema_version: "ae_voucher_attachment_review_manifest.v1",
    attachment_batch_id: batchId,
    attachment_manifest_hash: `sha256:${"b".repeat(64)}`,
    state: "LOCKED",
    attachment_count: items.length,
    total_size_bytes: items.reduce((total, item) => total + item.size_bytes, 0),
    items
  };
}

function attachmentIdentityFromSummary(summary) {
  if (typeof summary !== "string" || !summary.startsWith("{")) return null;
  try {
    const value = JSON.parse(summary);
    return isObject(value?.attachment_review_manifest)
      ? value.attachment_review_manifest
      : null;
  } catch {
    return null;
  }
}

function normalizeHumanGate(gate) {
  if (
    !isObject(gate) ||
    gate.schema_version !== HUMAN_GATE_VIEW_SCHEMA_VERSION ||
    !APPROVAL_DOMAINS.includes(gate.approval_domain) ||
    !["PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"].includes(
      gate.state
    )
  ) {
    throw new ApprovalClientError("Human approval gate is invalid.", {
      status: "HUMAN_GATE_INVALID"
    });
  }
  const normalized = {
    schema_version: gate.schema_version,
    gate_id: requiredGateId(gate.gate_id),
    approval_domain: gate.approval_domain,
    state: gate.state,
    title: requiredText(gate.title, "title"),
    summary: requiredText(gate.summary, "summary"),
    action_ref: requiredText(gate.action_ref, "action_ref"),
    approval_provider_type: optionalText(gate.approval_provider_type),
    approval_target_ref: optionalText(gate.approval_target_ref),
    business_operation_id: optionalText(gate.business_operation_id),
    expires_at: optionalText(gate.expires_at)
  };
  const attachmentManifest =
    gate.attachment_manifest || attachmentIdentityFromSummary(normalized.summary);
  if (attachmentManifest != null) {
    normalized.attachment_manifest = normalizeAttachmentReviewManifest(
      attachmentManifest
    );
  }
  if (normalized.approval_domain === "BUSINESS_FORMAL") {
    if (
      normalized.approval_provider_type !== "EOS" ||
      normalized.approval_target_ref == null ||
      normalized.business_operation_id == null
    ) {
      throw new ApprovalClientError("Business formal approval gate is invalid.", {
        status: "BUSINESS_FORMAL_GATE_INVALID"
      });
    }
    normalized.formal_approval = normalizeFormalApproval(
      gate.formal_approval,
      normalized
    );
  } else if (gate.formal_approval != null) {
    throw new ApprovalClientError("Formal approval projection crossed domains.", {
      status: "BUSINESS_FORMAL_DOMAIN_INVALID"
    });
  }
  return normalized;
}

export function normalizeAttachmentReviewManifest(value) {
  if (
    !isObject(value) ||
    value.schema_version !== "ae_voucher_attachment_review_manifest.v1" ||
    value.state !== "LOCKED" ||
    !Array.isArray(value.items) ||
    value.attachment_count !== value.items.length ||
    !HASH_REF.test(value.attachment_manifest_hash)
  ) {
    throw new ApprovalClientError("Approval attachment manifest is invalid.", {
      status: "APPROVAL_ATTACHMENT_MANIFEST_INVALID"
    });
  }
  const items = value.items.map(item => {
    if (
      !isObject(item) ||
      typeof item.attachment_id !== "string" ||
      typeof item.display_name !== "string" ||
      typeof item.media_type !== "string" ||
      !Number.isInteger(item.size_bytes) ||
      item.size_bytes < 1 ||
      typeof item.content_route !== "string" ||
      typeof item.download_route !== "string" ||
      !item.content_route.startsWith("/api/v1/") ||
      !item.download_route.startsWith("/api/v1/")
    ) {
      throw new ApprovalClientError("Approval attachment item is invalid.", {
        status: "APPROVAL_ATTACHMENT_MANIFEST_INVALID"
      });
    }
    return {
      attachment_id: item.attachment_id,
      display_name: item.display_name,
      media_type: item.media_type,
      size_bytes: item.size_bytes,
      content_route: item.content_route,
      download_route: item.download_route
    };
  });
  const total = items.reduce((sum, item) => sum + item.size_bytes, 0);
  if (!Number.isInteger(value.total_size_bytes) || value.total_size_bytes !== total) {
    throw new ApprovalClientError("Approval attachment totals are invalid.", {
      status: "APPROVAL_ATTACHMENT_MANIFEST_INVALID"
    });
  }
  return {
    schema_version: value.schema_version,
    attachment_batch_id: requiredText(
      value.attachment_batch_id,
      "attachment_batch_id"
    ),
    attachment_manifest_hash: value.attachment_manifest_hash,
    state: "LOCKED",
    attachment_count: items.length,
    total_size_bytes: total,
    items
  };
}

function normalizeFormalApproval(value, gate) {
  if (
    !isObject(value) ||
    value.schema_version !== "business_formal_gate_view.p8.v1"
  ) {
    throw new ApprovalClientError("Business formal projection is invalid.", {
      status: "BUSINESS_FORMAL_PROJECTION_INVALID"
    });
  }
  const currentStage = optionalStage(value.current_stage, "current_stage");
  const stageCount = optionalStage(value.stage_count, "stage_count");
  if (
    (currentStage == null) !== (stageCount == null) ||
    (currentStage != null && currentStage > stageCount)
  ) {
    throw new ApprovalClientError("Business formal stage progress is invalid.", {
      status: "BUSINESS_FORMAL_PROGRESS_INVALID"
    });
  }
  const eosTargetRef = requiredText(value.eos_target_ref, "formal eos_target_ref");
  if (eosTargetRef !== gate.approval_target_ref) {
    throw new ApprovalClientError("Business formal target projection is invalid.", {
      status: "BUSINESS_FORMAL_TARGET_INVALID"
    });
  }
  const terminalState = optionalText(value.terminal_state);
  const expectedTerminal = gate.state === "PENDING" ? null : gate.state;
  if (
    ![null, "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"].includes(
      terminalState
    ) ||
    terminalState !== expectedTerminal
  ) {
    throw new ApprovalClientError("Business formal terminal state is invalid.", {
      status: "BUSINESS_FORMAL_TERMINAL_INVALID"
    });
  }
  return {
    schema_version: value.schema_version,
    current_stage: currentStage,
    stage_count: stageCount,
    requested_role: optionalText(value.requested_role),
    eos_target_ref: eosTargetRef,
    org_unit_id: optionalText(value.org_unit_id),
    project_id: optionalText(value.project_id),
    terminal_state: terminalState
  };
}

function optionalStage(value, field) {
  if (value == null) return null;
  if (!Number.isInteger(value) || value < 1 || value > 5) {
    throw new ApprovalClientError(`Approval formal ${field} is invalid.`, {
      status: "BUSINESS_FORMAL_PROGRESS_INVALID"
    });
  }
  return value;
}

function normalizeDecisionRequest(payload) {
  if (
    !isObject(payload) ||
    payload.schema_version !== WC_APPROVAL_DECISION_REQUEST_SCHEMA_VERSION
  ) {
    throw new ApprovalClientError("Approval decision request is invalid.", {
      status: "APPROVAL_DECISION_REQUEST_INVALID"
    });
  }
  return buildApprovalDecisionRequest({
    decision: payload.decision,
    decisionComment: payload.decision_comment,
    correlationId: payload.correlation_id,
    causationId: payload.causation_id
  });
}

async function fetchJson(fetchImpl, url, options = {}) {
  let response;
  try {
    response = await fetchImpl(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      ...options
    });
  } catch (error) {
    throw new ApprovalClientError("Approval request is unavailable.", {
      status: "APPROVAL_NETWORK_ERROR",
      retryable: true
    });
  }
  const body = await safeResponseJson(response);
  if (!response.ok) {
    throw new ApprovalClientError(body.detail || "Approval request failed.", {
      status: body.error_code || `APPROVAL_HTTP_${response.status}`,
      httpStatus: response.status,
      retryable: Boolean(body.retryable || response.status >= 500)
    });
  }
  return body;
}

async function safeResponseJson(response) {
  try {
    const body = await response.json();
    return isObject(body) ? body : {};
  } catch {
    return {};
  }
}

function normalizeSubjectRef(value) {
  if (!isObject(value) || value.type !== "oa.user") {
    throw new ApprovalClientError("Approval subject ref is invalid.", {
      status: "APPROVAL_SUBJECT_INVALID"
    });
  }
  return { type: "oa.user", id: requiredText(value.id, "subject_ref.id") };
}

function requiredFetch(fetchImpl) {
  const candidate = fetchImpl || globalThis.fetch;
  if (typeof candidate !== "function") {
    throw new ApprovalClientError("Fetch implementation is required.", {
      status: "APPROVAL_FETCH_REQUIRED"
    });
  }
  return candidate.bind(globalThis);
}

function normalizeBaseUrl(value) {
  if (value == null || value === "") return "";
  if (typeof value !== "string") {
    throw new ApprovalClientError("Approval base URL is invalid.", {
      status: "APPROVAL_BASE_URL_INVALID"
    });
  }
  return value.replace(/\/+$/, "");
}

function boundedLimit(value) {
  if (!Number.isInteger(value) || value < 1 || value > 100) {
    throw new ApprovalClientError("Approval inbox limit must be between 1 and 100.", {
      status: "APPROVAL_LIMIT_INVALID"
    });
  }
  return value;
}

function requiredGateId(value) {
  if (typeof value !== "string" || !GATE_ID.test(value)) {
    throw new ApprovalClientError("Approval gate identity is invalid.", {
      status: "APPROVAL_GATE_ID_INVALID"
    });
  }
  return value;
}

function requiredText(value, field) {
  const normalized = optionalText(value);
  if (!normalized) {
    throw new ApprovalClientError(`Approval ${field} is invalid.`, {
      status: "APPROVAL_TEXT_INVALID"
    });
  }
  return normalized;
}

function optionalText(value) {
  if (value == null) return null;
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized || null;
}

function positiveInteger(value, field) {
  if (!Number.isInteger(value) || value < 1) {
    throw new ApprovalClientError(`Approval ${field} is invalid.`, {
      status: "APPROVAL_INTEGER_INVALID"
    });
  }
  return value;
}

function mockDecisionId(gateId) {
  return `42100000-0000-4000-8000-${gateId.replaceAll("-", "").slice(-12)}`;
}

function visitObject(value, path, found) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => visitObject(item, `${path}[${index}]`, found));
    return;
  }
  if (!isObject(value)) return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = key.toLowerCase();
    const keyPath = path ? `${path}.${key}` : key;
    if (SENSITIVE_KEY_PARTS.some(part => normalized.includes(part))) {
      found.push(keyPath);
    }
    visitObject(child, keyPath, found);
  }
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
