export const AE_WEB_INTERACTION_EXECUTION_PROGRESS_CLIENT_SCHEMA_VERSION =
  "ae_web_interaction_execution_progress_client.v1";

const PROGRESS_MESSAGES = Object.freeze({
  CHAT_REQUEST_ACCEPTED: "IA가 요청을 접수했습니다.",
  IA_INTENT_STARTED: "IA가 요청 의도를 파악하고 있습니다.",
  IA_INTENT_COMPLETED: "IA가 요청 의도 파악을 완료했습니다.",
  IA_CONTEXT_STARTED: "IA가 업무 컨텍스트를 구성하고 있습니다.",
  IA_CONTEXT_COMPLETED: "IA가 업무 컨텍스트 구성을 완료했습니다.",
  IA_PLAN_STARTED: "IA가 실행 계획을 수립하고 있습니다.",
  IA_PLAN_COMPLETED: "IA가 실행 계획 수립을 완료했습니다.",
  WC_DELEGATION_CREATED: "WC로 업무를 위임했습니다.",
  WC_WORK_CLAIMED: "WC 업무가 처리 가능한 Agent에게 전달되었습니다.",
  PA_ASSIGNED: "업무가 Project Agent에게 할당되었습니다.",
  CA_ASSIGNED: "업무가 Coordination Agent에게 할당되었습니다.",
  EA_ASSIGNED: "업무가 Enterprise Agent에게 할당되었습니다.",
  PA_INTENT_STARTED: "Project Agent가 업무 의도를 확인하고 있습니다.",
  PA_INTENT_COMPLETED: "Project Agent가 업무 의도 확인을 완료했습니다.",
  PA_CONTEXT_STARTED: "Project Agent가 실행 컨텍스트를 구성하고 있습니다.",
  PA_CONTEXT_COMPLETED: "Project Agent가 실행 컨텍스트 구성을 완료했습니다.",
  PA_PLAN_STARTED: "Project Agent가 실행 계획을 수립하고 있습니다.",
  PA_PLAN_COMPLETED: "Project Agent가 실행 계획 수립을 완료했습니다.",
  CA_INTENT_STARTED: "Coordination Agent가 업무 의도를 확인하고 있습니다.",
  CA_INTENT_COMPLETED: "Coordination Agent가 업무 의도 확인을 완료했습니다.",
  CA_CONTEXT_STARTED: "Coordination Agent가 실행 컨텍스트를 구성하고 있습니다.",
  CA_CONTEXT_COMPLETED: "Coordination Agent가 실행 컨텍스트 구성을 완료했습니다.",
  CA_PLAN_STARTED: "Coordination Agent가 실행 계획을 수립하고 있습니다.",
  CA_PLAN_COMPLETED: "Coordination Agent가 실행 계획 수립을 완료했습니다.",
  EA_INTENT_STARTED: "Enterprise Agent가 업무 의도를 확인하고 있습니다.",
  EA_INTENT_COMPLETED: "Enterprise Agent가 업무 의도 확인을 완료했습니다.",
  EA_CONTEXT_STARTED: "Enterprise Agent가 실행 컨텍스트를 구성하고 있습니다.",
  EA_CONTEXT_COMPLETED: "Enterprise Agent가 실행 컨텍스트 구성을 완료했습니다.",
  EA_PLAN_STARTED: "Enterprise Agent가 실행 계획을 수립하고 있습니다.",
  EA_PLAN_COMPLETED: "Enterprise Agent가 실행 계획 수립을 완료했습니다.",
  RUNTIME_EXECUTION_STARTED: "Agent 실행 계획을 처리하고 있습니다.",
  RUNTIME_EXECUTION_ADMITTED: "Agent Runtime이 실행 요청을 승인했습니다.",
  RESULT_PUBLISHED: "처리 결과가 Workspace에 게시되었습니다.",
  INTERACTION_COMPLETED: "요청 처리가 완료되었습니다.",
  INTERACTION_NO_ANSWER: "요청에 사용할 수 있는 답을 찾지 못했습니다.",
  INTERACTION_FAILED: "요청 처리가 실패했습니다."
});

export class InteractionExecutionProgressClientError extends Error {
  constructor(message, { status = "INTERACTION_EXECUTION_PROGRESS_CLIENT_ERROR", statusCode = null } = {}) {
    super(message);
    this.name = "InteractionExecutionProgressClientError";
    this.status = status;
    this.statusCode = statusCode;
  }
}

export function interactionExecutionProgressRoute(interactionId, afterSequence = 0) {
  const interaction = encodeURIComponent(requiredText(interactionId, "interactionId"));
  const cursor = nonNegativeInteger(afterSequence, "afterSequence");
  return `/api/v1/chat/interactions/${interaction}/execution-progress?after_sequence=${cursor}`;
}

export function createFetchInteractionExecutionProgressClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new InteractionExecutionProgressClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }
  return buildClient({
    clientMode: "fetch",
    read: async (interactionId, afterSequence) => {
      const route = interactionExecutionProgressRoute(interactionId, afterSequence);
      const response = await request(`${baseUrl}${route}`, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" }
      });
      const payload = await readJson(response);
      if (!response.ok) {
        throw new InteractionExecutionProgressClientError(
          payload.detail || "Interaction progress request failed.",
          {
            status: payload.error_code || "INTERACTION_EXECUTION_PROGRESS_REQUEST_FAILED",
            statusCode: response.status
          }
        );
      }
      return payload;
    }
  });
}

export function createMockInteractionExecutionProgressClient({ responseFactory } = {}) {
  return buildClient({
    clientMode: "mock",
    read: async (interactionId, afterSequence) =>
      typeof responseFactory === "function"
        ? responseFactory(interactionId, afterSequence)
        : {
            schema_version: "ae_interaction_execution_progress.v1",
            interaction_id: interactionId,
            workspace_id: "workspace-local",
            status: "COMPLETED",
            terminal: true,
            next_sequence: 1,
            events: [{
              event_id: interactionId,
              sequence: 1,
              event_code: "INTERACTION_COMPLETED",
              state: "COMPLETED",
              agent_type: "IA",
              source_ref: null,
              occurred_at: "2026-01-01T00:00:00Z",
              terminal: true
            }],
            metadata: {
              owner_scoped: true,
              ordered_projection: true,
              raw_prompt_included: false,
              private_payload_included: false,
              debug_time_available: true
            }
          }
  });
}

function buildClient({ clientMode, read }) {
  return Object.freeze({
    interaction_execution_progress_client_schema_version:
      AE_WEB_INTERACTION_EXECUTION_PROGRESS_CLIENT_SCHEMA_VERSION,
    clientMode,
    async getInteractionExecutionProgress(interactionId, afterSequence = 0) {
      const route = interactionExecutionProgressRoute(interactionId, afterSequence);
      return projectInteractionExecutionProgress(
        await read(interactionId, afterSequence),
        { clientMode, route }
      );
    }
  });
}

export function projectInteractionExecutionProgress(value, { clientMode = "mock", route = "" } = {}) {
  if (
    !isObject(value) ||
    value.schema_version !== "ae_interaction_execution_progress.v1" ||
    typeof value.interaction_id !== "string" ||
    typeof value.workspace_id !== "string" ||
    !Array.isArray(value.events)
  ) {
    throw invalidProjection();
  }
  const events = value.events.map(projectEvent);
  for (let index = 1; index < events.length; index += 1) {
    if (events[index].sequence <= events[index - 1].sequence) throw invalidProjection();
  }
  return Object.freeze({
    interactionId: requiredText(value.interaction_id, "interaction_id"),
    workspaceId: requiredText(value.workspace_id, "workspace_id"),
    status: requiredText(value.status, "status"),
    terminal: value.terminal === true,
    nextSequence: nonNegativeInteger(value.next_sequence, "next_sequence"),
    events: Object.freeze(events),
    clientMode,
    route,
    rawPromptIncluded: false,
    privatePayloadIncluded: false
  });
}

function projectEvent(value) {
  if (!isObject(value)) throw invalidProjection();
  const eventCode = requiredText(value.event_code, "event_code");
  return Object.freeze({
    eventId: requiredText(value.event_id, "event_id"),
    sequence: positiveInteger(value.sequence),
    eventCode,
    state: requiredText(value.state, "state"),
    agentType: optionalText(value.agent_type),
    sourceRef: optionalText(value.source_ref),
    occurredAt: isoTimestamp(value.occurred_at),
    terminal: value.terminal === true,
    message: PROGRESS_MESSAGES[eventCode] || "업무 처리 상태가 변경되었습니다."
  });
}

function invalidProjection() {
  return new InteractionExecutionProgressClientError(
    "Interaction execution progress projection is invalid.",
    { status: "INTERACTION_EXECUTION_PROGRESS_INVALID" }
  );
}

function isoTimestamp(value) {
  const text = requiredText(value, "occurred_at");
  if (Number.isNaN(Date.parse(text))) throw invalidProjection();
  return text;
}

function positiveInteger(value) {
  if (!Number.isInteger(value) || value < 1) throw invalidProjection();
  return value;
}

function nonNegativeInteger(value, field) {
  if (!Number.isInteger(value) || value < 0) {
    throw new InteractionExecutionProgressClientError(`${field} is invalid.`, {
      status: "INTERACTION_EXECUTION_PROGRESS_CURSOR_INVALID"
    });
  }
  return value;
}

function requiredText(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new InteractionExecutionProgressClientError(`${field} is required.`, {
      status: "INTERACTION_EXECUTION_PROGRESS_FIELD_REQUIRED"
    });
  }
  return value.trim();
}

function optionalText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function readJson(response) {
  try {
    const payload = await response.json();
    return isObject(payload) ? payload : {};
  } catch {
    return {};
  }
}
