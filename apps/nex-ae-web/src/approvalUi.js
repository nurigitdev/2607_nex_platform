import {
  ApprovalClientError,
  buildApprovalDecisionRequest,
  isApprovalGateExpired
} from "./approvalClient.js";

export const AE_WEB_APPROVAL_UI_SCHEMA_VERSION = "ae_web_approval_ui.p8.v1";

const DOMAIN_PRESENTATION = {
  NSL_WRITE: { label: "NSL WRITE", className: "nsl-write" },
  AGENT_FORMAL: { label: "Agent 공식 승인", className: "agent-formal" },
  BUSINESS_FORMAL: { label: "업무 공식 결재", className: "business-formal" }
};

export function createApprovalUiController({
  container,
  client,
  now = () => new Date(),
  correlationId = () => "conversation-p8-s42",
  causationId = () => "interaction-p8-s42"
} = {}) {
  if (!container || typeof container.addEventListener !== "function") {
    throw new Error("Approval UI container is required.");
  }
  let activeClient = requiredClient(client);
  let clientRevision = 0;
  let decisionInFlight = false;
  let state = emptyState(activeClient.clientMode);

  const render = () => {
    container.innerHTML = renderApprovalUi(state, { now: now() });
  };

  async function refresh() {
    const requestRevision = clientRevision;
    state = { ...state, phase: "LOADING", errorStatus: null, feedback: null };
    render();
    try {
      const inbox = await activeClient.listApprovalGates({ limit: 50 });
      if (requestRevision !== clientRevision) return snapshot();
      state = {
        ...emptyState(activeClient.clientMode),
        phase: "READY",
        inbox,
        selectedGateId:
          inbox.gates.find(gate => gate.gate_id === state.selectedGateId)?.gate_id ||
          null
      };
    } catch (error) {
      if (requestRevision !== clientRevision) return snapshot();
      state = failedState(state, error);
    }
    render();
    return snapshot();
  }

  async function selectGate(gateId) {
    const requestRevision = clientRevision;
    const gate = state.inbox?.gates.find(item => item.gate_id === gateId);
    if (!gate) return snapshot();
    if (isApprovalGateExpired(gate, now())) {
      state = {
        ...state,
        phase: "EXPIRED",
        selectedGateId: gate.gate_id,
        detail: { gate, decision_options: ["APPROVE", "REJECT"] },
        errorStatus: "APPROVAL_EXPIRED",
        feedback: "승인 기한이 만료되었습니다. 새 승인 요청이 필요합니다."
      };
      render();
      return snapshot();
    }
    state = {
      ...state,
      phase: "DETAIL_LOADING",
      selectedGateId: gate.gate_id,
      detail: null,
      errorStatus: null,
      feedback: null
    };
    render();
    try {
      const detail = await activeClient.getApprovalGate(gate.gate_id);
      if (requestRevision !== clientRevision) return snapshot();
      state = { ...state, phase: "DETAIL_READY", detail };
    } catch (error) {
      if (requestRevision !== clientRevision) return snapshot();
      state = failedState(state, error);
    }
    render();
    return snapshot();
  }

  async function submitDecision(decision) {
    const requestRevision = clientRevision;
    if (decisionInFlight || state.phase !== "DETAIL_READY" || !state.detail) {
      return snapshot();
    }
    if (isApprovalGateExpired(state.detail.gate, now())) {
      state = {
        ...state,
        phase: "EXPIRED",
        errorStatus: "APPROVAL_EXPIRED",
        feedback: "승인 기한이 만료되었습니다. 새 승인 요청이 필요합니다."
      };
      render();
      return snapshot();
    }
    decisionInFlight = true;
    const comment = container.querySelector("#approval-decision-comment")?.value || null;
    state = {
      ...state,
      phase: "SUBMITTING",
      errorStatus: null,
      feedback: decision === "APPROVE" ? "승인을 기록하고 있습니다." : "반려를 기록하고 있습니다."
    };
    render();
    try {
      const request = buildApprovalDecisionRequest({
        decision,
        decisionComment: comment,
        correlationId: correlationId(),
        causationId: causationId()
      });
      const result = await activeClient.submitApprovalDecision(
        state.detail.gate.gate_id,
        request
      );
      if (requestRevision !== clientRevision) return snapshot();
      const terminalState = result.decision === "APPROVE" ? "APPROVED" : "REJECTED";
      state = {
        ...state,
        phase: "DECIDED",
        decision: result,
        detail: {
          ...state.detail,
          gate: { ...state.detail.gate, state: terminalState }
        },
        inbox: {
          ...state.inbox,
          gates: state.inbox.gates.map(gate =>
            gate.gate_id === result.approval_work_item_id
              ? { ...gate, state: terminalState }
              : gate
          )
        },
        feedback:
          result.decision === "APPROVE"
            ? "승인이 안전하게 기록되었습니다."
            : "반려가 안전하게 기록되었습니다."
      };
    } catch (error) {
      if (requestRevision !== clientRevision) return snapshot();
      state = decisionFailureState(state, error);
    } finally {
      decisionInFlight = false;
    }
    render();
    return snapshot();
  }

  container.addEventListener("click", event => {
    const refreshTarget = event.target.closest("[data-approval-refresh]");
    if (refreshTarget) {
      void refresh();
      return;
    }
    const gateTarget = event.target.closest("[data-approval-gate-id]");
    if (gateTarget) {
      void selectGate(gateTarget.dataset.approvalGateId);
      return;
    }
    const decisionTarget = event.target.closest("[data-approval-decision]");
    if (decisionTarget && !decisionTarget.hasAttribute("disabled")) {
      void submitDecision(decisionTarget.dataset.approvalDecision);
    }
  });

  render();
  return {
    refresh,
    selectGate,
    submitDecision,
    setClient(nextClient) {
      clientRevision += 1;
      activeClient = requiredClient(nextClient);
      decisionInFlight = false;
      state = emptyState(activeClient.clientMode);
      render();
    },
    snapshot
  };

  function snapshot() {
    return structuredClone({
      ...state,
      decisionInFlight,
      ui_schema_version: AE_WEB_APPROVAL_UI_SCHEMA_VERSION
    });
  }
}

export function buildApprovalUiSummary(state, { now = new Date() } = {}) {
  const gates = state.inbox?.gates || [];
  const domainCounts = Object.fromEntries(
    Object.keys(DOMAIN_PRESENTATION).map(domain => [
      domain,
      gates.filter(gate => gate.approval_domain === domain).length
    ])
  );
  return {
    ui_schema_version: AE_WEB_APPROVAL_UI_SCHEMA_VERSION,
    phase: state.phase,
    client_mode: state.clientMode,
    gate_count: gates.length,
    actionable_count: gates.filter(
      gate => gate.state === "PENDING" && !isApprovalGateExpired(gate, now)
    ).length,
    expired_count: gates.filter(gate => isApprovalGateExpired(gate, now)).length,
    selected_gate_id: state.selectedGateId,
    domain_counts: domainCounts,
    decision_status: state.decision?.decision || null,
    error_status: state.errorStatus,
    metadata: {
      domainsMerged: false,
      rawProtectedPayloadRendered: false,
      browserServiceTokenIncluded: false,
      decisionAuthority: "WC_WITH_FRESH_OA_AUTHORIZATION"
    }
  };
}

export function renderApprovalUi(state, { now = new Date() } = {}) {
  const summary = buildApprovalUiSummary(state, { now });
  const gates = state.inbox?.gates || [];
  const detail = state.detail;
  return `
    <div class="approval-toolbar">
      <div>
        <strong>${escapeHtml(summary.actionable_count)}건 처리 가능</strong>
        <span>${escapeHtml(summary.gate_count)}건 조회됨</span>
      </div>
      <button type="button" data-approval-refresh>새로고침</button>
    </div>
    <div class="approval-feedback" role="status" aria-live="polite" data-phase="${escapeAttribute(state.phase)}">
      ${escapeHtml(state.feedback || phaseMessage(state.phase))}
    </div>
    <div class="approval-workbench">
      <div class="approval-inbox-list" role="list" aria-label="승인 대기 목록">
        ${gates.length > 0 ? gates.map(gate => renderGate(gate, state, now)).join("") : renderEmptyGateList(state.phase)}
      </div>
      <section class="approval-detail-surface" aria-label="승인 상세">
        ${detail ? renderDetail(detail, state, now) : renderEmptyDetail(state.phase)}
      </section>
    </div>
  `;
}

function renderGate(gate, state, now) {
  const domain = DOMAIN_PRESENTATION[gate.approval_domain];
  const expired = isApprovalGateExpired(gate, now);
  const selected = gate.gate_id === state.selectedGateId;
  const status = expired ? "EXPIRED" : gate.state;
  return `
    <button
      type="button"
      role="listitem"
      class="approval-inbox-item${selected ? " selected" : ""}${expired ? " expired" : ""}"
      data-approval-gate-id="${escapeAttribute(gate.gate_id)}"
      data-approval-domain="${escapeAttribute(gate.approval_domain)}"
      aria-pressed="${selected ? "true" : "false"}"
    >
      <span class="approval-domain ${escapeAttribute(domain.className)}">${escapeHtml(domain.label)}</span>
      <strong>${escapeHtml(gate.title)}</strong>
      <span class="approval-item-summary">${escapeHtml(gate.summary)}</span>
      <span class="approval-item-state">${escapeHtml(statusLabel(status))}</span>
    </button>
  `;
}

function renderDetail(detail, state, now) {
  const gate = detail.gate;
  const domain = DOMAIN_PRESENTATION[gate.approval_domain];
  const expired = isApprovalGateExpired(gate, now) || state.phase === "EXPIRED";
  const disabled =
    expired ||
    state.phase === "SUBMITTING" ||
    state.phase === "DECIDED" ||
    state.phase === "UNAUTHORIZED" ||
    gate.state !== "PENDING";
  return `
    <header class="approval-detail-header">
      <span class="approval-domain ${escapeAttribute(domain.className)}">${escapeHtml(domain.label)}</span>
      <span class="badge ${badgeClass(expired ? "EXPIRED" : gate.state)}">${escapeHtml(statusLabel(expired ? "EXPIRED" : gate.state))}</span>
    </header>
    <h3>${escapeHtml(gate.title)}</h3>
    <p>${escapeHtml(gate.summary)}</p>
    <dl class="approval-detail-meta">
      <div><dt>provider</dt><dd>${escapeHtml(gate.approval_provider_type || "n/a")}</dd></div>
      <div><dt>target</dt><dd>${escapeHtml(gate.approval_target_ref || "n/a")}</dd></div>
      <div><dt>operation</dt><dd>${escapeHtml(gate.business_operation_id || "n/a")}</dd></div>
      <div><dt>expires</dt><dd>${escapeHtml(gate.expires_at || "none")}</dd></div>
    </dl>
    <label class="approval-comment-label" for="approval-decision-comment">검토 의견</label>
    <textarea id="approval-decision-comment" maxlength="2000" rows="3" ${disabled ? "disabled" : ""}></textarea>
    <div class="approval-decision-actions" aria-label="승인 결정">
      <button type="button" data-approval-decision="APPROVE" ${disabled ? "disabled" : ""}>승인</button>
      <button type="button" class="danger" data-approval-decision="REJECT" ${disabled ? "disabled" : ""}>반려</button>
    </div>
    ${state.decision ? `<p class="approval-decision-record">decision ${escapeHtml(state.decision.decision_id)}</p>` : ""}
  `;
}

function renderEmptyGateList(phase) {
  const text = phase === "LOADING" ? "승인 목록을 불러오는 중입니다." : "처리할 승인 요청이 없습니다.";
  return `<p class="approval-empty">${escapeHtml(text)}</p>`;
}

function renderEmptyDetail(phase) {
  const text = phase === "LOADING" ? "목록을 확인하고 있습니다." : "승인 요청을 선택하면 안전한 상세 정보가 표시됩니다.";
  return `<p class="approval-empty">${escapeHtml(text)}</p>`;
}

function emptyState(clientMode) {
  return {
    phase: "IDLE",
    clientMode,
    inbox: null,
    selectedGateId: null,
    detail: null,
    decision: null,
    errorStatus: null,
    feedback: null
  };
}

function failedState(state, error) {
  const normalized = normalizeError(error);
  return {
    ...state,
    phase: normalized.httpStatus === 401 || normalized.httpStatus === 403 ? "UNAUTHORIZED" : "FAILED",
    errorStatus: normalized.status,
    feedback:
      normalized.httpStatus === 401 || normalized.httpStatus === 403
        ? "현재 계정으로 승인 정보를 조회할 수 없습니다."
        : "승인 정보를 불러오지 못했습니다. 다시 시도해 주세요."
  };
}

function decisionFailureState(state, error) {
  const normalized = normalizeError(error);
  if (normalized.httpStatus === 401 || normalized.httpStatus === 403) {
    return {
      ...state,
      phase: "UNAUTHORIZED",
      errorStatus: normalized.status,
      feedback: "현재 계정에는 이 요청을 결정할 권한이 없습니다."
    };
  }
  if (normalized.status.includes("EXPIRED")) {
    return {
      ...state,
      phase: "EXPIRED",
      errorStatus: normalized.status,
      feedback: "승인 기한이 만료되었습니다. 새 승인 요청이 필요합니다."
    };
  }
  return {
    ...state,
    phase: normalized.httpStatus === 409 ? "CONFLICT" : "FAILED",
    errorStatus: normalized.status,
    feedback:
      normalized.httpStatus === 409
        ? "이미 처리되었거나 현재 상태와 충돌합니다. 목록을 새로고침해 주세요."
        : "승인 결정을 기록하지 못했습니다. 다시 시도해 주세요."
  };
}

function normalizeError(error) {
  if (error instanceof ApprovalClientError) return error;
  return new ApprovalClientError("Approval UI request failed.", {
    status: "APPROVAL_UI_FAILED",
    retryable: false
  });
}

function requiredClient(client) {
  if (
    !client ||
    typeof client.listApprovalGates !== "function" ||
    typeof client.getApprovalGate !== "function" ||
    typeof client.submitApprovalDecision !== "function"
  ) {
    throw new Error("Approval UI client is invalid.");
  }
  return client;
}

function phaseMessage(phase) {
  const messages = {
    IDLE: "승인 목록을 준비했습니다.",
    LOADING: "승인 목록을 불러오는 중입니다.",
    READY: "승인 요청을 선택해 검토할 수 있습니다.",
    DETAIL_LOADING: "승인 상세를 확인하고 있습니다.",
    DETAIL_READY: "승인 또는 반려를 선택할 수 있습니다.",
    SUBMITTING: "승인 결정을 기록하고 있습니다.",
    DECIDED: "승인 결정이 기록되었습니다.",
    UNAUTHORIZED: "승인 권한이 확인되지 않았습니다.",
    EXPIRED: "승인 요청이 만료되었습니다.",
    CONFLICT: "승인 상태가 변경되었습니다.",
    FAILED: "승인 요청을 처리하지 못했습니다."
  };
  return messages[phase] || messages.FAILED;
}

function statusLabel(status) {
  const labels = {
    PENDING: "대기",
    APPROVED: "승인됨",
    REJECTED: "반려됨",
    EXPIRED: "만료",
    CANCELLED: "취소"
  };
  return labels[status] || status;
}

function badgeClass(status) {
  if (status === "APPROVED") return "success";
  if (status === "PENDING") return "pending";
  return "danger";
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
