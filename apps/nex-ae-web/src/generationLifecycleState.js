export const AE_WEB_GENERATION_LIFECYCLE_STATE_SCHEMA_VERSION =
  "ae_web_generation_lifecycle_state.v1";

export const GENERATION_LIFECYCLE_PHASES = [
  "idle",
  "admitting",
  "active",
  "completed",
  "failed",
  "cancelled"
];

const CLIENT_SCHEMA_VERSION = "ae_web_grounded_generation_client.v1";
const TERMINAL_STATUSES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

export class GenerationLifecycleStateError extends Error {
  constructor(message, { status = "GENERATION_LIFECYCLE_STATE_INVALID" } = {}) {
    super(message);
    this.name = "GenerationLifecycleStateError";
    this.status = status;
  }
}

export function createGenerationLifecycleState({ clientMode = "mock" } = {}) {
  return {
    generation_lifecycle_state_schema_version:
      AE_WEB_GENERATION_LIFECYCLE_STATE_SCHEMA_VERSION,
    clientMode: normalizeClientMode(clientMode),
    phase: "idle",
    interactionId: null,
    lifecycleStatus: "IDLE",
    currentStage: "NOT_STARTED",
    progressMode: "INDETERMINATE",
    progressPercent: null,
    messageKey: "generation.progress.idle",
    attemptCount: 0,
    maxAttempts: 0,
    cancellable: false,
    retryable: false,
    terminal: false,
    nextPollAfterSeconds: null,
    handoffStatus: null,
    recovery: null,
    response: null,
    citationQuality: null,
    activeAction: null,
    errorStatus: null,
    metadata: safeMetadata(false)
  };
}

export function markGenerationAdmissionRunning(state) {
  const current = assertLifecycleState(state);
  if (!["idle", "failed", "cancelled"].includes(current.phase)) {
    throw new GenerationLifecycleStateError("Generation admission is already active.", {
      status: "GENERATION_ADMISSION_CONFLICT"
    });
  }
  return {
    ...current,
    phase: "admitting",
    lifecycleStatus: "ADMITTING",
    currentStage: "REQUEST_ADMISSION",
    messageKey: "generation.progress.admitting",
    retryable: false,
    terminal: false,
    response: null,
    citationQuality: null,
    activeAction: "admit",
    errorStatus: null,
    metadata: safeMetadata(false)
  };
}

export function applyGenerationAdmission(state, admission) {
  const current = assertLifecycleState(state);
  assertClientResult(admission, "GENERATION_ADMISSION_INVALID");
  if (!admission.interactionId) {
    throw new GenerationLifecycleStateError("Admission interaction is missing.", {
      status: "GENERATION_INTERACTION_ID_MISSING"
    });
  }
  const lifecycleStatus =
    admission.asyncGeneration?.lifecycle_status || admission.status || "PENDING";
  const terminal = Boolean(admission.terminal || TERMINAL_STATUSES.has(lifecycleStatus));
  return {
    ...current,
    phase: phaseForStatus(lifecycleStatus, terminal),
    interactionId: admission.interactionId,
    lifecycleStatus,
    currentStage: terminal ? lifecycleStatus : "ADMITTED",
    messageKey: terminal
      ? messageKeyForStatus(lifecycleStatus)
      : "generation.progress.queued",
    attemptCount: integerOr(admission.asyncGeneration?.attempt_count, 0),
    maxAttempts: integerOr(admission.asyncGeneration?.max_attempts, 0),
    cancellable: Boolean(admission.asyncGeneration?.cancellable ?? !terminal),
    retryable: Boolean(admission.retryable),
    terminal,
    nextPollAfterSeconds: terminal ? null : 2,
    handoffStatus: admission.asyncGeneration?.handoff_status || null,
    recovery: null,
    response: null,
    citationQuality: null,
    activeAction: null,
    errorStatus: admission.asyncGeneration?.error?.error_code || null,
    metadata: safeMetadata(false)
  };
}

export function applyGenerationProgress(state, progress) {
  const current = assertLifecycleState(state);
  assertClientResult(progress, "GENERATION_PROGRESS_INVALID");
  assertSameInteraction(current, progress.interactionId);
  const lifecycleStatus = progress.lifecycleStatus || "UNKNOWN";
  const terminal = Boolean(progress.terminal || TERMINAL_STATUSES.has(lifecycleStatus));
  return {
    ...current,
    phase: phaseForStatus(lifecycleStatus, terminal),
    lifecycleStatus,
    currentStage: progress.currentStage || "UNKNOWN",
    progressMode: progress.progressMode || "INDETERMINATE",
    progressPercent: normalizeProgress(progress.progressPercent),
    messageKey: progress.messageKey || messageKeyForStatus(lifecycleStatus),
    attemptCount: integerOr(progress.attemptCount, current.attemptCount),
    maxAttempts: integerOr(progress.maxAttempts, current.maxAttempts),
    cancellable: Boolean(progress.cancellable && !terminal),
    retryable: Boolean(progress.retryable),
    terminal,
    nextPollAfterSeconds: terminal
      ? null
      : normalizePollDelay(progress.nextPollAfterSeconds),
    handoffStatus: progress.handoffStatus || current.handoffStatus,
    recovery: normalizeRecovery(progress.recovery),
    activeAction: null,
    errorStatus: progress.error?.error_code || null,
    metadata: safeMetadata(Boolean(current.response))
  };
}

export function applyGenerationRefresh(state, refresh) {
  const current = assertLifecycleState(state);
  assertClientResult(refresh, "GENERATION_REFRESH_INVALID");
  const interaction = refresh.interaction;
  assertClientResult(interaction, "GENERATION_REFRESH_INTERACTION_INVALID");
  assertSameInteraction(current, interaction.interactionId);
  const next = applyGenerationAdmission(current, interaction);
  const response =
    refresh.contentPersistedByAe && typeof refresh.content === "string"
      ? {
          content: refresh.content,
          contentType: refresh.contentType,
          contentSha256: refresh.contentSha256,
          sizeBytes: refresh.sizeBytes,
          source: "refresh"
        }
      : current.response;
  return {
    ...next,
    response,
    handoffStatus: refresh.handoffStatus || next.handoffStatus,
    metadata: safeMetadata(Boolean(response))
  };
}

export function applyVerifiedGeneratedResponse(state, response) {
  const current = assertLifecycleState(state);
  assertClientResult(response, "GENERATED_RESPONSE_INVALID");
  assertSameInteraction(current, response.interactionId);
  if (response.ownerScopeEnforced !== true || typeof response.content !== "string") {
    throw new GenerationLifecycleStateError("Generated response is not owner verified.", {
      status: "GENERATED_RESPONSE_OWNER_SCOPE_REQUIRED"
    });
  }
  return {
    ...current,
    phase: "completed",
    lifecycleStatus: "COMPLETED",
    currentStage: "RESPONSE_READY",
    progressMode: "DETERMINATE",
    progressPercent: 100,
    messageKey: "generation.progress.completed",
    cancellable: false,
    retryable: false,
    terminal: true,
    nextPollAfterSeconds: null,
    handoffStatus: "READY",
    response: {
      content: response.content,
      contentType: response.contentType,
      contentSha256: response.contentSha256,
      sizeBytes: response.sizeBytes,
      responseId: response.responseId,
      lineage: response.lineage,
      source: "response"
    },
    activeAction: null,
    errorStatus: null,
    metadata: safeMetadata(true)
  };
}

export function applyCitationQuality(state, workflow) {
  const current = assertLifecycleState(state);
  assertClientResult(workflow, "CITATION_QUALITY_INVALID");
  assertSameInteraction(current, workflow.interactionId);
  if (workflow.ownerScopeEnforced !== true) {
    throw new GenerationLifecycleStateError("Citation workflow is not owner scoped.", {
      status: "CITATION_QUALITY_OWNER_SCOPE_REQUIRED"
    });
  }
  return {
    ...current,
    citationQuality: {
      workflowStatus: workflow.workflowStatus,
      nextAction: workflow.nextAction,
      quality: workflow.quality,
      repair: workflow.repair,
      operatorRemediation: workflow.operatorRemediation
    }
  };
}

export function markGenerationActionRunning(state, action) {
  const current = assertLifecycleState(state);
  if (!["cancel", "retry", "refresh", "load-response", "load-quality"].includes(action)) {
    throw new GenerationLifecycleStateError("Generation action is unsupported.", {
      status: "GENERATION_ACTION_UNSUPPORTED"
    });
  }
  return { ...current, activeAction: action, errorStatus: null };
}

export function markGenerationLifecycleFailure(state, error) {
  const current = assertLifecycleState(state);
  return {
    ...current,
    phase: "failed",
    lifecycleStatus: "FAILED",
    currentStage: "FAILED",
    messageKey: "generation.progress.failed",
    cancellable: false,
    retryable: Boolean(error?.retryable),
    terminal: true,
    nextPollAfterSeconds: null,
    activeAction: null,
    errorStatus: normalizeErrorStatus(error?.status),
    metadata: safeMetadata(Boolean(current.response))
  };
}

export function buildGenerationLifecycleReadModel(state) {
  const current = assertLifecycleState(state);
  return {
    lifecycleStateSchemaVersion:
      current.generation_lifecycle_state_schema_version,
    phase: current.phase,
    lifecycleStatus: current.lifecycleStatus,
    currentStage: current.currentStage,
    progressMode: current.progressMode,
    progressPercent: current.progressPercent,
    messageKey: current.messageKey,
    attemptLabel:
      current.maxAttempts > 0
        ? `${current.attemptCount}/${current.maxAttempts}`
        : String(current.attemptCount),
    polling: {
      enabled: current.phase === "active" && !current.terminal,
      nextAfterSeconds: current.nextPollAfterSeconds
    },
    controls: {
      cancelEnabled: current.cancellable && !current.activeAction,
      retryEnabled: current.retryable && current.terminal && !current.activeAction,
      refreshEnabled: Boolean(current.interactionId) && !current.activeAction,
      busy: Boolean(current.activeAction),
      activeAction: current.activeAction
    },
    presentation: {
      responseReady: Boolean(current.response),
      citationQualityReady: Boolean(current.citationQuality),
      artifactHandoffAllowed: Boolean(
        current.response && current.citationQuality?.nextAction === "PRESENT_RESPONSE"
      )
    },
    errorStatus: current.errorStatus
  };
}

export function buildGenerationLifecycleSummary(state) {
  const current = assertLifecycleState(state);
  return {
    generation_lifecycle_state_schema_version:
      current.generation_lifecycle_state_schema_version,
    client_mode: current.clientMode,
    phase: current.phase,
    lifecycle_status: current.lifecycleStatus,
    current_stage: current.currentStage,
    progress_percent: current.progressPercent,
    attempt_count: current.attemptCount,
    max_attempts: current.maxAttempts,
    cancellable: current.cancellable,
    retryable: current.retryable,
    terminal: current.terminal,
    response_ready: Boolean(current.response),
    citation_quality_ready: Boolean(current.citationQuality),
    error_status: current.errorStatus,
    metadata: current.metadata
  };
}

function assertLifecycleState(value) {
  if (
    !value ||
    value.generation_lifecycle_state_schema_version !==
      AE_WEB_GENERATION_LIFECYCLE_STATE_SCHEMA_VERSION ||
    !GENERATION_LIFECYCLE_PHASES.includes(value.phase)
  ) {
    throw new GenerationLifecycleStateError("Generation lifecycle state is invalid.", {
      status: "GENERATION_LIFECYCLE_STATE_SCHEMA_INVALID"
    });
  }
  return value;
}

function assertClientResult(value, status) {
  if (!value || value.groundedGenerationClientSchemaVersion !== CLIENT_SCHEMA_VERSION) {
    throw new GenerationLifecycleStateError("Generation client result is invalid.", {
      status
    });
  }
}

function assertSameInteraction(state, interactionId) {
  if (
    !state.interactionId ||
    typeof interactionId !== "string" ||
    state.interactionId !== interactionId
  ) {
    throw new GenerationLifecycleStateError("Generation interaction lineage differs.", {
      status: "GENERATION_INTERACTION_LINEAGE_MISMATCH"
    });
  }
}

function phaseForStatus(status, terminal) {
  if (status === "CANCELLED") return "cancelled";
  if (status === "FAILED") return "failed";
  if (status === "COMPLETED") return "completed";
  return terminal ? "failed" : "active";
}

function messageKeyForStatus(status) {
  const normalized = String(status || "unknown").toLowerCase();
  return `generation.progress.${normalized}`;
}

function normalizeClientMode(value) {
  if (!["mock", "fetch"].includes(value)) {
    throw new GenerationLifecycleStateError("Generation client mode is invalid.", {
      status: "GENERATION_CLIENT_MODE_INVALID"
    });
  }
  return value;
}

function normalizeProgress(value) {
  if (value == null) return null;
  if (typeof value !== "number" || value < 0 || value > 100) {
    throw new GenerationLifecycleStateError("Generation progress is invalid.", {
      status: "GENERATION_PROGRESS_PERCENT_INVALID"
    });
  }
  return value;
}

function normalizePollDelay(value) {
  if (value == null) return 2;
  if (typeof value !== "number" || value < 0 || value > 60) {
    throw new GenerationLifecycleStateError("Generation poll delay is invalid.", {
      status: "GENERATION_POLL_DELAY_INVALID"
    });
  }
  return value;
}

function normalizeRecovery(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return {
    action: value.action || "NONE",
    eligible: Boolean(value.eligible),
    reasonCode: value.reason_code || value.reasonCode || "UNKNOWN",
    newInteractionRequired: Boolean(
      value.new_interaction_required ?? value.newInteractionRequired
    )
  };
}

function normalizeErrorStatus(value) {
  return typeof value === "string" && value.trim()
    ? value.trim().slice(0, 120)
    : "GENERATION_UNAVAILABLE";
}

function integerOr(value, fallback) {
  return Number.isInteger(value) && value >= 0 ? value : fallback;
}

function safeMetadata(contentIncluded) {
  return {
    contentIncluded,
    rawPromptIncluded: false,
    rawSourceIncluded: false,
    browserServiceTokenIncluded: false,
    providerUrlIncluded: false,
    databaseUrlIncluded: false,
    storageRefIncluded: false
  };
}
