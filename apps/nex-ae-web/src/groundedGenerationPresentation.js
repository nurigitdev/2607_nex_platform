import {
  buildGroundedResponseQualitySurface,
  buildGroundedResponseQualitySummary
} from "./groundedResponseQuality.js";
import { createRepairedResponseDecisionState } from "./repairedResponseDecisionState.js";
import { buildRetrievalQualityWarningSurface } from "./retrievalQualityWarnings.js";

export const AE_WEB_GROUNDED_GENERATION_PRESENTATION_SCHEMA_VERSION =
  "ae_web_grounded_generation_presentation.v1";

const WORKFLOW_SCHEMA_VERSION = "ae_web_grounded_generation_workflow.v1";
const RETRIEVAL_CLIENT_SCHEMA_VERSION = "ae_web_retrieval_client.v1";

export class GroundedGenerationPresentationError extends Error {
  constructor(message, { status = "GENERATION_PRESENTATION_INVALID" } = {}) {
    super(message);
    this.name = "GroundedGenerationPresentationError";
    this.status = status;
  }
}

export async function buildGroundedGenerationPresentation({
  workflow,
  repairedResponseReviewClient = null
}) {
  assertWorkflow(workflow);
  const state = workflow.state;
  const citationQuality = state.citationQuality;
  const nextAction = citationQuality?.nextAction || "WAIT";
  const qualitySurface = buildGroundedResponseQualitySurface({
    generation: {
      grounded_response_quality: citationQuality?.quality || null
    }
  });
  const retrievalResult = buildAdmissionRetrievalResult(workflow.admission);
  if (workflow.groundingRequested === true && !retrievalResult) {
    throw new GroundedGenerationPresentationError(
      "Grounded generation retrieval projection is missing.",
      { status: "GENERATION_RETRIEVAL_PROJECTION_REQUIRED" }
    );
  }
  let displayMode = "BLOCKED";
  let assistantText = generationStatusMessage(workflow.status);
  let repairedResponseReview = null;
  let artifactHandoffAllowed = false;

  if (
    workflow.status === "COMPLETED" &&
    nextAction === "PRESENT_RESPONSE" &&
    typeof state.response?.content === "string"
  ) {
    displayMode = "VERIFIED_RESPONSE";
    assistantText = state.response.content;
    artifactHandoffAllowed =
      workflow.readModel?.presentation?.artifactHandoffAllowed === true;
  } else if (
    workflow.status === "COMPLETED" &&
    nextAction === "PRESENT_REPAIRED_RESPONSE"
  ) {
    repairedResponseReview = await loadRepairedResponseReview(
      repairedResponseReviewClient,
      state.interactionId
    );
    displayMode = "REPAIRED_RESPONSE_REVIEW";
    assistantText = "수리된 응답이 준비되어 검토가 필요합니다.";
  } else if (nextAction === "RETRY_OR_REVIEW_GENERATION") {
    displayMode = "QUALITY_ATTENTION_REQUIRED";
    assistantText = "인용 품질을 확인한 뒤 재시도하거나 검토해야 합니다.";
  }

  const presentation = {
    presentationSchemaVersion:
      AE_WEB_GROUNDED_GENERATION_PRESENTATION_SCHEMA_VERSION,
    displayMode,
    assistantText,
    interactionId: state.interactionId,
    lifecycleStatus: state.lifecycleStatus,
    citationWorkflowStatus: citationQuality?.workflowStatus || "UNKNOWN",
    nextAction,
    artifactHandoffAllowed,
    retrievalResult,
    retrievalQualityWarning: retrievalResult
      ? buildRetrievalQualityWarningSurface(retrievalResult)
      : null,
    groundedResponseQuality: qualitySurface,
    repairedResponseReview,
    metadata: {
      ownerVerifiedResponse: Boolean(state.response),
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false,
      storageRefIncluded: false
    }
  };
  return {
    ...presentation,
    summary: buildGroundedGenerationPresentationSummary(presentation)
  };
}

export function buildGroundedGenerationPresentationFailure(workflow, error) {
  assertWorkflow(workflow);
  const qualitySurface = buildGroundedResponseQualitySurface({
    generation: {
      grounded_response_quality: workflow.state.citationQuality?.quality || null
    }
  });
  const presentation = {
    presentationSchemaVersion:
      AE_WEB_GROUNDED_GENERATION_PRESENTATION_SCHEMA_VERSION,
    displayMode: "PRESENTATION_UNAVAILABLE",
    assistantText: "검증된 생성 응답을 표시할 수 없습니다.",
    interactionId: workflow.state.interactionId,
    lifecycleStatus: workflow.state.lifecycleStatus,
    citationWorkflowStatus:
      workflow.state.citationQuality?.workflowStatus || "UNKNOWN",
    nextAction: workflow.state.citationQuality?.nextAction || "WAIT",
    artifactHandoffAllowed: false,
    retrievalResult: buildAdmissionRetrievalResult(workflow.admission),
    retrievalQualityWarning: null,
    groundedResponseQuality: qualitySurface,
    repairedResponseReview: null,
    errorStatus: safeErrorStatus(error),
    metadata: {
      ownerVerifiedResponse: Boolean(workflow.state.response),
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false,
      databaseUrlIncluded: false,
      storageRefIncluded: false
    }
  };
  return {
    ...presentation,
    summary: buildGroundedGenerationPresentationSummary(presentation)
  };
}

export function buildAdmissionRetrievalResult(admission) {
  if (!admission) return null;
  if (admission.groundedGenerationClientSchemaVersion !== "ae_web_grounded_generation_client.v1") {
    throw new GroundedGenerationPresentationError("Generation admission is invalid.", {
      status: "GENERATION_ADMISSION_PRESENTATION_INVALID"
    });
  }
  const retrieval = admission.retrieval;
  if (!retrieval || typeof retrieval !== "object" || Array.isArray(retrieval)) {
    return null;
  }
  const cxStatus = retrieval.cx_status || "UNKNOWN";
  return {
    retrieval_client_schema_version: RETRIEVAL_CLIENT_SCHEMA_VERSION,
    interaction_schema_version: admission.interactionSchemaVersion,
    clientMode: admission.clientMode,
    route: admission.route,
    retrievalInteractionId: admission.interactionId,
    chatDocumentId: admission.chatDocumentId,
    status: ["READY", "NO_ANSWER", "NOT_REQUESTED"].includes(cxStatus)
      ? "COMPLETED"
      : "PENDING",
    cxRetrievalPackageId: retrieval.cx_retrieval_package_id || null,
    cxPackageHash: retrieval.cx_package_hash || null,
    cxStatus,
    purpose: "grounded_answer",
    userMessageHash: null,
    evidenceCount: integerOr(retrieval.evidence_count, 0),
    bestScore:
      typeof retrieval.best_score === "number" ? retrieval.best_score : null,
    confidenceBucket: retrieval.confidence_bucket || "UNKNOWN",
    noAnswerReason: retrieval.no_answer_reason || null,
    warnings: stringList(retrieval.warnings),
    qualityWarnings: objectOrNull(retrieval.quality_warnings),
    retryable: false,
    metadata: {
      userMessageIncluded: false,
      sourcePreviewIncluded: false,
      browserServiceTokenIncluded: false,
      providerUrlIncluded: false
    }
  };
}

export function buildGroundedGenerationPresentationSummary(presentation) {
  if (
    !presentation ||
    presentation.presentationSchemaVersion !==
      AE_WEB_GROUNDED_GENERATION_PRESENTATION_SCHEMA_VERSION
  ) {
    throw new GroundedGenerationPresentationError(
      "Generation presentation is invalid."
    );
  }
  return {
    presentation_schema_version:
      AE_WEB_GROUNDED_GENERATION_PRESENTATION_SCHEMA_VERSION,
    display_mode: presentation.displayMode,
    lifecycle_status: presentation.lifecycleStatus,
    citation_workflow_status: presentation.citationWorkflowStatus,
    next_action: presentation.nextAction,
    artifact_handoff_allowed: presentation.artifactHandoffAllowed,
    retrieval_available: Boolean(presentation.retrievalResult),
    repaired_response_review_available: Boolean(
      presentation.repairedResponseReview
    ),
    quality: buildGroundedResponseQualitySummary(
      presentation.groundedResponseQuality
    ),
    metadata: presentation.metadata
  };
}

async function loadRepairedResponseReview(client, interactionId) {
  if (!client || typeof client.listRepairedResponseReviews !== "function") {
    throw new GroundedGenerationPresentationError(
      "Repaired response review client is required.",
      { status: "REPAIRED_RESPONSE_REVIEW_CLIENT_REQUIRED" }
    );
  }
  const collection = await client.listRepairedResponseReviews(interactionId);
  const surface = collection?.items?.[0];
  if (!surface || surface.interactionId !== interactionId) {
    throw new GroundedGenerationPresentationError(
      "Repaired response review is unavailable.",
      { status: "REPAIRED_RESPONSE_REVIEW_UNAVAILABLE" }
    );
  }
  return {
    ...surface,
    decisionState: createRepairedResponseDecisionState({
      clientMode: surface.clientMode
    })
  };
}

function generationStatusMessage(status) {
  if (status === "ACTIVE") return "생성 작업이 계속 진행 중입니다.";
  return "검증된 생성 응답을 표시할 수 없습니다.";
}

function assertWorkflow(workflow) {
  if (
    !workflow ||
    workflow.workflowSchemaVersion !== WORKFLOW_SCHEMA_VERSION ||
    !workflow.state ||
    !workflow.readModel
  ) {
    throw new GroundedGenerationPresentationError(
      "Generation workflow is invalid."
    );
  }
}

function integerOr(value, fallback) {
  return Number.isInteger(value) && value >= 0 ? value : fallback;
}

function stringList(value) {
  return Array.isArray(value)
    ? value.filter(item => typeof item === "string" && item.trim())
    : [];
}

function objectOrNull(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : null;
}

function safeErrorStatus(error) {
  return typeof error?.status === "string" && error.status.trim()
    ? error.status.trim().slice(0, 120)
    : "GENERATION_PRESENTATION_UNAVAILABLE";
}
