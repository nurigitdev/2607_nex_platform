export const AE_WEB_GROUNDED_GENERATION_CLIENT_SCHEMA_VERSION =
  "ae_web_grounded_generation_client.v1";
export const AE_CHAT_INTERACTIONS_ROUTE = "/api/v1/chat/interactions";

const SCHEMAS = {
  interaction: ["interaction_schema_version", "ae_chat_interaction.v1"],
  progress: ["progress_schema_version", "ae_generation_progress.v1"],
  recovery: ["recovery_plan_schema_version", "ae_generation_recovery_plan.v1"],
  refresh: ["refresh_schema_version", "ae_async_chat_refresh.v1"],
  response: ["response_schema_version", "ae_generated_response.v1"],
  citationQuality: ["workflow_schema_version", "ae_citation_quality_workflow.v1"]
};

export class GroundedGenerationClientError extends Error {
  constructor(
    message,
    {
      status = "GROUNDED_GENERATION_CLIENT_ERROR",
      statusCode = null,
      retryable = false
    } = {}
  ) {
    super(message);
    this.name = "GroundedGenerationClientError";
    this.status = status;
    this.statusCode = statusCode;
    this.retryable = retryable;
  }
}

export function createMockGroundedGenerationClient({ responseFactories = {} } = {}) {
  return buildClient({
    clientMode: "mock",
    invoke: async ({ operation, interactionId, payload, route }) => {
      const factory = responseFactories[operation];
      if (typeof factory === "function") {
        return factory({ interactionId, payload, route });
      }
      return buildMockResponse(operation, interactionId, payload);
    }
  });
}

export function createFetchGroundedGenerationClient({ baseUrl = "", fetchImpl } = {}) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new GroundedGenerationClientError("Fetch is not available.", {
      status: "FETCH_UNAVAILABLE"
    });
  }

  return buildClient({
    clientMode: "fetch",
    invoke: ({ method, route, payload }) =>
      requestJson(request, `${baseUrl}${route}`, { method, payload })
  });
}

function buildClient({ clientMode, invoke }) {
  const execute = async ({
    operation,
    method,
    route,
    interactionId,
    payload,
    project
  }) => {
    const response = await invoke({
      operation,
      method,
      route,
      interactionId,
      payload
    });
    return project(response, { clientMode, route });
  };

  return {
    grounded_generation_client_schema_version:
      AE_WEB_GROUNDED_GENERATION_CLIENT_SCHEMA_VERSION,
    clientMode,
    admitInteraction(payload) {
      assertObject(payload, "Grounded generation admission payload is invalid.");
      return execute({
        operation: "admitInteraction",
        method: "POST",
        route: AE_CHAT_INTERACTIONS_ROUTE,
        payload,
        project: buildInteractionResult
      });
    },
    getInteraction(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "getInteraction",
        method: "GET",
        route: interactionRoute(normalizedId),
        interactionId: normalizedId,
        project: buildInteractionResult
      });
    },
    getProgress(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "getProgress",
        method: "GET",
        route: interactionRoute(normalizedId, "progress"),
        interactionId: normalizedId,
        project: buildProgressResult
      });
    },
    refreshInteraction(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "refreshInteraction",
        method: "POST",
        route: interactionRoute(normalizedId, "refresh"),
        interactionId: normalizedId,
        project: buildRefreshResult
      });
    },
    cancelInteraction(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "cancelInteraction",
        method: "POST",
        route: interactionRoute(normalizedId, "cancel"),
        interactionId: normalizedId,
        project: buildInteractionResult
      });
    },
    retryInteraction(interactionId, payload) {
      assertObject(payload, "Grounded generation retry payload is invalid.");
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "retryInteraction",
        method: "POST",
        route: interactionRoute(normalizedId, "retry"),
        interactionId: normalizedId,
        payload,
        project: buildInteractionResult
      });
    },
    getRecovery(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "getRecovery",
        method: "GET",
        route: interactionRoute(normalizedId, "recovery"),
        interactionId: normalizedId,
        project: buildRecoveryResult
      });
    },
    getResponse(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "getResponse",
        method: "GET",
        route: interactionRoute(normalizedId, "response"),
        interactionId: normalizedId,
        project: buildGeneratedResponseResult
      });
    },
    getCitationQuality(interactionId) {
      const normalizedId = normalizeInteractionId(interactionId);
      return execute({
        operation: "getCitationQuality",
        method: "GET",
        route: interactionRoute(normalizedId, "citation-quality"),
        interactionId: normalizedId,
        project: buildCitationQualityResult
      });
    }
  };
}

export function buildInteractionResult(
  record,
  { clientMode = "mock", route = AE_CHAT_INTERACTIONS_ROUTE } = {}
) {
  assertSchema(record, SCHEMAS.interaction, "CHAT_INTERACTION_INVALID");
  const asyncGeneration = objectOrNull(record.generation?.async_generation);
  return withClientMetadata(
    {
      interactionSchemaVersion: record.interaction_schema_version,
      interactionId: stringOrNull(record.interaction_id),
      workspaceId: stringOrNull(record.workspace_id),
      chatDocumentId: stringOrNull(record.chat_document_id),
      status: record.status || "UNKNOWN",
      cxGenerationId: stringOrNull(record.cx_generation_id),
      cxStatus: record.cx_status || "UNKNOWN",
      asyncGeneration,
      artifactRefs: Array.isArray(record.artifact_refs) ? record.artifact_refs : [],
      retryable: Boolean(asyncGeneration?.retryable),
      terminal: ["COMPLETED", "FAILED", "CANCELLED"].includes(record.status)
    },
    { clientMode, route, contentIncluded: false }
  );
}

export function buildProgressResult(record, { clientMode = "mock", route = "" } = {}) {
  assertSchema(record, SCHEMAS.progress, "GENERATION_PROGRESS_INVALID");
  return withClientMetadata(
    {
      progressSchemaVersion: record.progress_schema_version,
      interactionId: stringOrNull(record.interaction_id),
      jobId: stringOrNull(record.job_id),
      cxGenerationId: stringOrNull(record.cx_generation_id),
      lifecycleStatus: record.lifecycle_status || "UNKNOWN",
      eventType: record.event_type || "generation.unknown",
      currentStage: record.current_stage || "UNKNOWN",
      progressMode: record.progress_mode || "INDETERMINATE",
      progressPercent:
        typeof record.progress_percent === "number" ? record.progress_percent : null,
      messageKey: record.message_key || "generation.progress.unknown",
      attemptCount: Number.isInteger(record.attempt_count) ? record.attempt_count : 0,
      maxAttempts: Number.isInteger(record.max_attempts) ? record.max_attempts : 0,
      retryable: Boolean(record.retryable),
      cancellable: Boolean(record.cancellable),
      terminal: Boolean(record.terminal),
      nextAction: record.next_action || "WAIT",
      nextPollAfterSeconds:
        typeof record.next_poll_after_seconds === "number"
          ? record.next_poll_after_seconds
          : null,
      handoffStatus: stringOrNull(record.handoff_status),
      error: objectOrNull(record.error),
      recovery: objectOrNull(record.recovery)
    },
    { clientMode, route, contentIncluded: false }
  );
}

export function buildRecoveryResult(record, { clientMode = "mock", route = "" } = {}) {
  assertSchema(record, SCHEMAS.recovery, "GENERATION_RECOVERY_INVALID");
  return withClientMetadata(
    {
      recoveryPlanSchemaVersion: record.recovery_plan_schema_version,
      action: record.action || "NONE",
      eligible: Boolean(record.eligible),
      reasonCode: record.reason_code || "UNKNOWN",
      newInteractionRequired: Boolean(record.new_interaction_required),
      parentLineageRequired: Boolean(record.parent_lineage_required),
      inputHashRequired: Boolean(record.input_hash_required)
    },
    { clientMode, route, contentIncluded: false }
  );
}

export function buildRefreshResult(record, { clientMode = "mock", route = "" } = {}) {
  assertSchema(record, SCHEMAS.refresh, "GENERATION_REFRESH_INVALID");
  assertSchema(
    record.interaction,
    SCHEMAS.interaction,
    "GENERATION_REFRESH_INTERACTION_INVALID"
  );
  const result = objectOrNull(record.result);
  return withClientMetadata(
    {
      refreshSchemaVersion: record.refresh_schema_version,
      interaction: buildInteractionResult(record.interaction, { clientMode, route }),
      handoffStatus: result?.handoff_status || null,
      cxGenerationId: stringOrNull(result?.cx_generation_id),
      content: typeof result?.content === "string" ? result.content : null,
      contentType: stringOrNull(result?.content_type),
      contentSha256: stringOrNull(result?.content_sha256),
      sizeBytes: Number.isInteger(result?.size_bytes) ? result.size_bytes : null,
      contentPersistedByAe: Boolean(record.content_persisted_by_ae)
    },
    { clientMode, route, contentIncluded: typeof result?.content === "string" }
  );
}

export function buildGeneratedResponseResult(
  record,
  { clientMode = "mock", route = "" } = {}
) {
  assertSchema(record, SCHEMAS.response, "GENERATED_RESPONSE_INVALID");
  if (typeof record.content !== "string") {
    throw new GroundedGenerationClientError("Generated response content is invalid.", {
      status: "GENERATED_RESPONSE_CONTENT_INVALID"
    });
  }
  return withClientMetadata(
    {
      responseSchemaVersion: record.response_schema_version,
      interactionId: stringOrNull(record.interaction_id),
      chatDocumentId: stringOrNull(record.chat_document_id),
      responseId: stringOrNull(record.response_id),
      cxGenerationId: stringOrNull(record.cx_generation_id),
      contentType: record.content_type || "text/plain; charset=utf-8",
      content: record.content,
      contentSha256: stringOrNull(record.content_sha256),
      sizeBytes: Number.isInteger(record.size_bytes) ? record.size_bytes : null,
      lineage: objectOrNull(record.lineage),
      ownerScopeEnforced: record.owner_scope_enforced === true
    },
    { clientMode, route, contentIncluded: true }
  );
}

export function buildCitationQualityResult(
  record,
  { clientMode = "mock", route = "" } = {}
) {
  assertSchema(record, SCHEMAS.citationQuality, "CITATION_QUALITY_INVALID");
  return withClientMetadata(
    {
      workflowSchemaVersion: record.workflow_schema_version,
      interactionId: stringOrNull(record.interaction_id),
      cxGenerationId: stringOrNull(record.cx_generation_id),
      workflowStatus: record.workflow_status || "UNKNOWN",
      nextAction: record.next_action || "WAIT",
      quality: objectOrNull(record.quality),
      repair: objectOrNull(record.repair),
      operatorRemediation: objectOrNull(record.operator_remediation),
      ownerScopeEnforced: record.owner_scope_enforced === true
    },
    { clientMode, route, contentIncluded: false }
  );
}

function interactionRoute(interactionId, suffix = "") {
  const normalized = normalizeInteractionId(interactionId);
  const tail = suffix ? `/${suffix}` : "";
  return `${AE_CHAT_INTERACTIONS_ROUTE}/${encodeURIComponent(normalized)}${tail}`;
}

function normalizeInteractionId(value) {
  if (typeof value !== "string" || !value.trim()) {
    throw new GroundedGenerationClientError("interactionId is required.", {
      status: "INTERACTION_ID_INVALID"
    });
  }
  return value.trim();
}

async function requestJson(request, url, { method, payload }) {
  const options = {
    method,
    credentials: "same-origin",
    headers: { Accept: "application/json" }
  };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }

  let response;
  try {
    response = await request(url, options);
  } catch {
    throw new GroundedGenerationClientError("Grounded generation request failed.", {
      status: "NETWORK_ERROR",
      retryable: true
    });
  }
  const body = await safeJson(response);
  if (!response.ok) {
    throw new GroundedGenerationClientError(
      typeof body.detail === "string"
        ? body.detail
        : `Grounded generation request failed with HTTP ${response.status}.`,
      {
        status: body.error_code || `HTTP_${response.status}`,
        statusCode: response.status,
        retryable: Boolean(body.retryable) || response.status >= 500
      }
    );
  }
  return body;
}

async function safeJson(response) {
  try {
    const body = await response.json();
    return isObject(body) ? body : {};
  } catch {
    return {};
  }
}

function assertSchema(record, [field, expected], status) {
  if (!isObject(record) || record[field] !== expected) {
    throw new GroundedGenerationClientError("Grounded generation record is invalid.", {
      status
    });
  }
}

function assertObject(value, message) {
  if (!isObject(value)) {
    throw new GroundedGenerationClientError(message, {
      status: "REQUEST_PAYLOAD_INVALID"
    });
  }
}

function withClientMetadata(result, { clientMode, route, contentIncluded }) {
  return {
    groundedGenerationClientSchemaVersion:
      AE_WEB_GROUNDED_GENERATION_CLIENT_SCHEMA_VERSION,
    clientMode,
    route,
    ...result,
    metadata: {
      contentIncluded,
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false,
      storageRefIncluded: false
    }
  };
}

function buildMockResponse(operation, interactionId, payload) {
  const id =
    (operation === "retryInteraction" ? payload?.interaction_id : interactionId) ||
    payload?.interaction_id ||
    "interaction-web-local-001";
  if (["admitInteraction", "getInteraction", "cancelInteraction", "retryInteraction"].includes(operation)) {
    return mockInteraction(id, operation === "cancelInteraction" ? "CANCELLED" : "PENDING");
  }
  if (operation === "getProgress") return mockProgress(id);
  if (operation === "getRecovery") return mockRecovery();
  if (operation === "refreshInteraction") return mockRefresh(id);
  if (operation === "getResponse") return mockGeneratedResponse(id);
  if (operation === "getCitationQuality") return mockCitationQuality(id);
  throw new GroundedGenerationClientError("Unsupported mock operation.", {
    status: "MOCK_OPERATION_UNSUPPORTED"
  });
}

function mockInteraction(interactionId, status) {
  return {
    interaction_schema_version: "ae_chat_interaction.v1",
    interaction_id: interactionId,
    workspace_id: "workspace-web-local",
    chat_document_id: "chat-web-local",
    status,
    cx_generation_id: "cx-generation-web-local",
    cx_status: status === "CANCELLED" ? "CANCELLED" : "QUEUED",
    generation: {
      async_generation: {
        lifecycle_status: status,
        retryable: status !== "CANCELLED",
        cancellable: status === "PENDING"
      }
    },
    artifact_refs: []
  };
}

function mockProgress(interactionId) {
  return {
    progress_schema_version: "ae_generation_progress.v1",
    interaction_id: interactionId,
    job_id: "job-web-local",
    cx_generation_id: "cx-generation-web-local",
    lifecycle_status: "PENDING",
    event_type: "generation.request.accepted",
    current_stage: "MO_ADMISSION_WAITING",
    progress_mode: "INDETERMINATE",
    progress_percent: null,
    message_key: "generation.progress.queued",
    attempt_count: 0,
    max_attempts: 3,
    retryable: true,
    cancellable: true,
    terminal: false,
    next_action: "POLL_GENERATION_HANDOFF",
    next_poll_after_seconds: 2,
    handoff_status: null,
    error: null,
    recovery: mockRecovery()
  };
}

function mockRecovery() {
  return {
    recovery_plan_schema_version: "ae_generation_recovery_plan.v1",
    action: "WAIT",
    eligible: false,
    reason_code: "GENERATION_IN_PROGRESS",
    new_interaction_required: false,
    parent_lineage_required: false,
    input_hash_required: false
  };
}

function mockRefresh(interactionId) {
  const content = "Grounded mock response [1].";
  return {
    refresh_schema_version: "ae_async_chat_refresh.v1",
    interaction: {
      ...mockInteraction(interactionId, "COMPLETED"),
      cx_status: "SUCCEEDED"
    },
    result: {
      handoff_status: "READY",
      cx_generation_id: "cx-generation-web-local",
      content,
      content_type: "text/plain; charset=utf-8",
      content_sha256: "a".repeat(64),
      size_bytes: content.length,
      owner_scope_enforced: true
    },
    content_persisted_by_ae: true
  };
}

function mockGeneratedResponse(interactionId) {
  const content = "Grounded mock response [1].";
  return {
    response_schema_version: "ae_generated_response.v1",
    interaction_id: interactionId,
    chat_document_id: "chat-web-local",
    response_id: "response-web-local",
    cx_generation_id: "cx-generation-web-local",
    content_type: "text/plain; charset=utf-8",
    content,
    content_sha256: "a".repeat(64),
    size_bytes: content.length,
    lineage: { owner_scope_enforced: true, raw_content_included: false },
    owner_scope_enforced: true
  };
}

function mockCitationQuality(interactionId) {
  return {
    workflow_schema_version: "ae_citation_quality_workflow.v1",
    interaction_id: interactionId,
    cx_generation_id: "cx-generation-web-local",
    workflow_status: "VALIDATED",
    next_action: "PRESENT_RESPONSE",
    quality: {
      boundary_status: "PASS",
      citation_status: "VALIDATED",
      issue_count: 0,
      recommended_action: "proceed"
    },
    repair: { status: "NOT_ATTEMPTED", attempted: false },
    operator_remediation: { required: false },
    owner_scope_enforced: true,
    content_included: false
  };
}

function objectOrNull(value) {
  return isObject(value) ? value : null;
}

function stringOrNull(value) {
  return typeof value === "string" && value ? value : null;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
