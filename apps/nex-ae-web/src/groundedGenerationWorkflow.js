import {
  applyCitationQuality,
  applyGenerationAdmission,
  applyGenerationProgress,
  applyGenerationRefresh,
  applyVerifiedGeneratedResponse,
  buildGenerationLifecycleReadModel,
  buildGenerationLifecycleSummary,
  createGenerationLifecycleState,
  markGenerationAdmissionRunning,
  markGenerationLifecycleFailure
} from "./generationLifecycleState.js";

export const AE_WEB_GROUNDED_GENERATION_WORKFLOW_SCHEMA_VERSION =
  "ae_web_grounded_generation_workflow.v1";

export class GroundedGenerationWorkflowError extends Error {
  constructor(message, { status = "GROUNDED_GENERATION_WORKFLOW_INVALID" } = {}) {
    super(message);
    this.name = "GroundedGenerationWorkflowError";
    this.status = status;
  }
}

export function buildGroundedGenerationRequest({
  interactionId,
  workspaceId,
  chatDocumentId,
  userMessage,
  documentScope,
  grounded = true
}) {
  const request = {
    interaction_id: requiredText(interactionId, "interactionId"),
    workspace_id: requiredText(workspaceId, "workspaceId"),
    chat_document_id: requiredText(chatDocumentId, "chatDocumentId"),
    user_message: requiredText(userMessage, "userMessage"),
    generation: {
      execution_strategy: "ASYNCHRONOUS",
      execution_mode: grounded ? "GROUNDED_ANSWER" : "GENERAL_ANSWER"
    },
    retrieval: {
      enabled: Boolean(grounded),
      execution_mode: grounded ? "DOCUMENT_SEARCH" : "GENERAL_CHAT",
      document_scope: grounded ? normalizedDocumentScope(documentScope) : null,
      retrieval_profile: { search_strategy: "hybrid" },
      top_k: 5,
      include_neighbors: false,
      include_source_preview: false,
      purpose: grounded ? "grounded_answer" : "search"
    }
  };
  return request;
}

export async function runGroundedGenerationWorkflow({
  client,
  request,
  initialState,
  onState = () => {},
  wait = waitForSeconds,
  maxPolls = 30,
  signal = null
}) {
  assertClient(client);
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw new GroundedGenerationWorkflowError("Generation request is invalid.", {
      status: "GENERATION_WORKFLOW_REQUEST_INVALID"
    });
  }
  if (!Number.isInteger(maxPolls) || maxPolls < 1 || maxPolls > 120) {
    throw new GroundedGenerationWorkflowError("maxPolls is invalid.", {
      status: "GENERATION_WORKFLOW_POLL_LIMIT_INVALID"
    });
  }

  let state = initialState || createGenerationLifecycleState({
    clientMode: client.clientMode
  });
  const events = [];
  let admission = null;
  let pollCount = 0;
  const publish = eventType => {
    const readModel = buildGenerationLifecycleReadModel(state);
    events.push({
      eventType,
      stage: readModel.currentStage,
      status: readModel.lifecycleStatus,
      progressPercent: readModel.progressPercent
    });
    onState(state, readModel);
  };

  try {
    assertNotAborted(signal);
    state = markGenerationAdmissionRunning(state);
    publish("generation.web.admitting");
    admission = await client.admitInteraction(request);
    state = applyGenerationAdmission(state, admission);
    publish("generation.request.accepted");

    while (!state.terminal && pollCount < maxPolls) {
      assertNotAborted(signal);
      const delay = state.nextPollAfterSeconds ?? 2;
      if (client.clientMode !== "mock") await wait(delay);
      assertNotAborted(signal);
      const progress = await client.getProgress(state.interactionId);
      pollCount += 1;
      state = applyGenerationProgress(state, progress);
      publish(progress.eventType || "generation.progress.updated");
    }

    if (state.phase === "completed") {
      const refresh = await client.refreshInteraction(state.interactionId);
      state = applyGenerationRefresh(state, refresh);
      publish("generation.web.refreshed");
      const response = await client.getResponse(state.interactionId);
      state = applyVerifiedGeneratedResponse(state, response);
      publish("generation.web.response.ready");
      const quality = await client.getCitationQuality(state.interactionId);
      state = applyCitationQuality(state, quality);
      publish("generation.web.citation-quality.ready");
    }
  } catch (error) {
    state = markGenerationLifecycleFailure(state, error);
    publish("generation.web.failed");
  }

  const readModel = buildGenerationLifecycleReadModel(state);
  return {
    workflowSchemaVersion: AE_WEB_GROUNDED_GENERATION_WORKFLOW_SCHEMA_VERSION,
    status:
      state.phase === "completed"
        ? "COMPLETED"
        : state.phase === "active"
          ? "ACTIVE"
          : "FAILED",
    state,
    readModel,
    admission,
    groundingRequested: request.retrieval?.enabled === true,
    pollCount,
    pollLimitReached: state.phase === "active" && pollCount === maxPolls,
    events,
    summary: buildGroundedGenerationWorkflowSummary({
      state,
      pollCount,
      maxPolls,
      groundingRequested: request.retrieval?.enabled === true
    })
  };
}

export function buildGroundedGenerationWorkflowSummary({
  state,
  pollCount,
  maxPolls,
  groundingRequested = false
}) {
  const lifecycle = buildGenerationLifecycleSummary(state);
  return {
    workflow_schema_version: AE_WEB_GROUNDED_GENERATION_WORKFLOW_SCHEMA_VERSION,
    lifecycle,
    poll_count: pollCount,
    max_polls: maxPolls,
    poll_limit_reached: lifecycle.terminal === false && pollCount === maxPolls,
    grounding_requested: Boolean(groundingRequested),
    metadata: {
      rawPromptIncluded: false,
      generatedContentIncluded: false,
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false
    }
  };
}

function normalizedDocumentScope(documentScope) {
  const scope = documentScope?.document_scope;
  if (!scope || !Array.isArray(scope.document_ids) || scope.document_ids.length < 1) {
    throw new GroundedGenerationWorkflowError(
      "Grounded generation requires a document scope.",
      { status: "GENERATION_DOCUMENT_SCOPE_REQUIRED" }
    );
  }
  return { document_ids: [...new Set(scope.document_ids.map(normalizedDocumentId))] };
}

function normalizedDocumentId(value) {
  return requiredText(value, "documentId");
}

function requiredText(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new GroundedGenerationWorkflowError(`${fieldName} is required.`, {
      status: "GENERATION_WORKFLOW_FIELD_REQUIRED"
    });
  }
  return value.trim();
}

function assertClient(client) {
  if (
    !client ||
    typeof client.admitInteraction !== "function" ||
    typeof client.getProgress !== "function" ||
    typeof client.refreshInteraction !== "function" ||
    typeof client.getResponse !== "function" ||
    typeof client.getCitationQuality !== "function"
  ) {
    throw new GroundedGenerationWorkflowError("Generation client is invalid.", {
      status: "GENERATION_WORKFLOW_CLIENT_INVALID"
    });
  }
}

function assertNotAborted(signal) {
  if (signal?.aborted) {
    throw new GroundedGenerationWorkflowError("Generation workflow was interrupted.", {
      status: "GENERATION_WORKFLOW_ABORTED"
    });
  }
}

function waitForSeconds(seconds) {
  return new Promise(resolve => globalThis.setTimeout(resolve, seconds * 1000));
}
