export const AE_WEB_INTERACTION_AGENT_RESULT_CLIENT_SCHEMA_VERSION =
  "ae_web_interaction_agent_result_client.v1";

export class InteractionAgentResultClientError extends Error {
  constructor(
    message,
    { status = "INTERACTION_AGENT_RESULT_CLIENT_ERROR", statusCode = null } = {}
  ) {
    super(message);
    this.name = "InteractionAgentResultClientError";
    this.status = status;
    this.statusCode = statusCode;
  }
}

export function interactionAgentResultRoute(interactionId) {
  return `/api/v1/chat/interactions/${encodeURIComponent(
    requiredText(interactionId, "interactionId")
  )}/agent-result`;
}

export function createFetchInteractionAgentResultClient({
  baseUrl = "",
  fetchImpl
} = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new InteractionAgentResultClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }
  return buildClient({
    clientMode: "fetch",
    read: async interactionId => {
      const route = interactionAgentResultRoute(interactionId);
      const response = await request(`${baseUrl}${route}`, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" }
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new InteractionAgentResultClientError(
          payload.detail || "Interaction result request failed.",
          {
            status: payload.error_code || "INTERACTION_AGENT_RESULT_REQUEST_FAILED",
            statusCode: response.status
          }
        );
      }
      return payload;
    }
  });
}

export function createMockInteractionAgentResultClient({ responseFactory } = {}) {
  return buildClient({
    clientMode: "mock",
    read: async interactionId =>
      typeof responseFactory === "function"
        ? responseFactory(interactionId)
        : mockProjection(interactionId)
  });
}

function buildClient({ clientMode, read }) {
  return {
    interaction_agent_result_client_schema_version:
      AE_WEB_INTERACTION_AGENT_RESULT_CLIENT_SCHEMA_VERSION,
    clientMode,
    async getInteractionAgentResult(interactionId) {
      const route = interactionAgentResultRoute(interactionId);
      return projectInteractionAgentResult(await read(interactionId), {
        clientMode,
        route
      });
    }
  };
}

export function projectInteractionAgentResult(
  value,
  { clientMode = "mock", route = "" } = {}
) {
  if (
    !value ||
    value.schema_version !== "ae_interaction_agent_result.v1" ||
    typeof value.interaction_id !== "string" ||
    typeof value.agent_execution_id !== "string"
  ) {
    throw new InteractionAgentResultClientError(
      "Interaction AgentResult projection is invalid.",
      { status: "INTERACTION_AGENT_RESULT_INVALID" }
    );
  }
  const result = value.result && typeof value.result === "object"
    ? {
        resultRef: optionalText(value.result.result_ref),
        resultHash: optionalText(value.result.result_hash),
        status: optionalText(value.result.status) || "UNKNOWN",
        businessRefs: stringList(value.result.business_refs),
        externalRefs: stringList(value.result.external_refs),
        artifactRefs: stringList(value.result.artifact_refs),
        warnings: stringList(value.result.warnings),
        businessSummary: projectBusinessResultSummary(
          value.result.business_summary
        ),
        deliveryState: optionalText(value.result.delivery?.state) || "UNKNOWN",
        workspaceActivityRef: optionalText(
          value.result.delivery?.workspace_activity_ref
        )
      }
    : null;
  return {
    interactionId: value.interaction_id,
    workspaceId: optionalText(value.workspace_id),
    agentExecutionId: value.agent_execution_id,
    executionState: optionalText(value.execution_state) || "UNKNOWN",
    executionPhase: optionalText(value.execution_phase) || "UNKNOWN",
    terminal: value.terminal === true,
    result,
    updatedAt: optionalText(value.updated_at),
    completedAt: optionalText(value.completed_at),
    clientMode,
    route,
    rawResultIncluded: false
  };
}

export function projectBusinessResultSummary(value) {
  if (!value || typeof value !== "object") return null;
  if (value.result_type !== "FINANCE.VOUCHER_DRAFT") return null;
  if (
    value.summary_schema_version !== "ae_business_result_summary.v1" ||
    !value.summary ||
    typeof value.summary !== "object"
  ) {
    throw invalidBusinessSummary();
  }
  const summary = value.summary;
  const outcome = enumText(
    summary.outcome,
    ["COMMITTED", "NOT_COMMITTED", "UNKNOWN_COMMIT_STATE"]
  );
  const approvalState = enumText(
    summary.approval_state,
    ["APPROVED", "DENIED", "NOT_REQUIRED", "UNKNOWN"]
  );
  const amount = decimalText(summary.amount);
  const currency = requiredBoundedText(summary.currency, 16);
  const projectCode = requiredBoundedText(summary.project_code, 128);
  const operationId = requiredBoundedText(summary.business_operation_id, 128);
  const accountCodes = boundedStringList(summary.account_codes, 8, 64);
  if (
    !outcome ||
    !approvalState ||
    !amount ||
    !currency ||
    !projectCode ||
    !operationId ||
    accountCodes.length === 0
  ) {
    throw invalidBusinessSummary();
  }
  if (summary.business_object_link !== null) {
    throw new InteractionAgentResultClientError(
      "Business result link is not admitted.",
      { status: "BUSINESS_RESULT_LINK_INVALID" }
    );
  }
  return Object.freeze({
    resultType: "FINANCE.VOUCHER_DRAFT",
    schemaVersion: "ae_business_result_summary.v1",
    outcome,
    verificationStatus: optionalText(summary.verification_status),
    approvalState,
    businessOperationId: operationId,
    voucherNumber: optionalText(summary.voucher_number),
    amount,
    currency: currency.toUpperCase(),
    accountCodes: Object.freeze(accountCodes),
    projectCode,
    businessObjectLink: null
  });
}

function mockProjection(interactionId) {
  return {
    schema_version: "ae_interaction_agent_result.v1",
    interaction_id: requiredText(interactionId, "interactionId"),
    workspace_id: "workspace-local",
    agent_execution_id: "agent-execution-local",
    execution_state: "SUCCEEDED",
    execution_phase: "FINALIZE",
    terminal: true,
    result: {
      result_ref: "AE:AGENT_RESULT:result-local",
      result_hash: `sha256:${"a".repeat(64)}`,
      status: "SUCCEEDED",
      business_refs: [],
      external_refs: [],
      artifact_refs: [],
      warnings: [],
      business_summary: null,
      delivery: {
        state: "ACKNOWLEDGED",
        workspace_activity_ref: "AE:WORKSPACE_ACTIVITY:activity-local"
      }
    },
    updated_at: "2026-10-26T00:00:00Z",
    completed_at: "2026-10-26T00:00:00Z"
  };
}

async function readJson(response) {
  try {
    const value = await response.json();
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function stringList(value) {
  return Array.isArray(value)
    ? value.filter(item => typeof item === "string" && item.trim())
    : [];
}

function boundedStringList(value, maximumItems, maximumLength) {
  if (!Array.isArray(value) || value.length < 1 || value.length > maximumItems) {
    return [];
  }
  const items = value.map(item => requiredBoundedText(item, maximumLength));
  if (items.some(item => item === null) || new Set(items).size !== items.length) {
    return [];
  }
  return items;
}

function requiredBoundedText(value, maximum) {
  const normalized = optionalText(value);
  return normalized && normalized.length <= maximum ? normalized : null;
}

function enumText(value, allowed) {
  const normalized = requiredBoundedText(value, 64)?.toUpperCase();
  return normalized && allowed.includes(normalized) ? normalized : null;
}

function decimalText(value) {
  const normalized = requiredBoundedText(value, 64);
  return normalized && /^(?:0|[1-9][0-9]*)(?:\.[0-9]{2})$/.test(normalized)
    ? normalized
    : null;
}

function invalidBusinessSummary() {
  return new InteractionAgentResultClientError(
    "Business result summary is invalid.",
    { status: "BUSINESS_RESULT_SUMMARY_INVALID" }
  );
}

function optionalText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function requiredText(value, name) {
  const normalized = optionalText(value);
  if (!normalized) {
    throw new InteractionAgentResultClientError(`${name} is required.`, {
      status: "INTERACTION_AGENT_RESULT_IDENTITY_INVALID"
    });
  }
  return normalized;
}
