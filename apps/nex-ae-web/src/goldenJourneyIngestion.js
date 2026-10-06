import {
  advanceGoldenJourney,
  buildGoldenJourneyEvidence,
  failGoldenJourney
} from "./goldenJourneyState.js";
import { buildUploadSurfaceDraft } from "./uploadSurface.js";

export const GOLDEN_JOURNEY_INGESTION_SCHEMA_VERSION =
  "ae_web_golden_journey_ingestion.v1";

export async function runGoldenJourneyIngestion({
  journeyState,
  sessionClient,
  loginRequest,
  uploadClient,
  uploadInput,
  uploadProgressClient,
  file = null,
  maxPolls = 3,
  clock = () => new Date().toISOString()
}) {
  let state = journeyState;
  let phase = "LOGIN";
  try {
    assertDependencies({ sessionClient, uploadClient, uploadProgressClient, clock });
    if (!Number.isInteger(maxPolls) || maxPolls < 1 || maxPolls > 20) {
      throw workflowError("POLL_LIMIT_INVALID", false);
    }
    if (!uploadInput || Object.prototype.hasOwnProperty.call(uploadInput, "ownerScope")) {
      throw workflowError("BROWSER_OWNER_SCOPE_FORBIDDEN", false);
    }

    const session = await sessionClient.login(loginRequest);
    if (
      session?.status !== "authenticated" ||
      !session.tenantRef?.id ||
      !session.subjectRef?.id
    ) {
      throw workflowError("AUTHENTICATION_REQUIRED", false);
    }
    state = advanceGoldenJourney(state, {
      stage: "SESSION_AUTHENTICATED",
      occurredAt: clock(),
      refs: {
        subject_ref: session.subjectRef.id,
        tenant_ref: session.tenantRef.id,
        workspace_id: uploadInput.workspaceId
      }
    });

    phase = "UPLOAD";
    const uploadDraft = buildUploadSurfaceDraft({
      ...uploadInput,
      ownerScope: {
        tenantId: session.tenantRef.id,
        ownerUserId: session.subjectRef.id,
        uploadedByUserId: session.subjectRef.id
      }
    });
    const upload = await uploadClient.submitUploadDraft(uploadDraft, { file });
    assertOwnerScope(upload, session);
    state = advanceGoldenJourney(state, {
      stage: "UPLOAD_ACCEPTED",
      occurredAt: clock(),
      refs: {
        upload_handoff_id: upload.uploadHandoffId,
        document_id: upload.documentId
      }
    });

    phase = "INGESTION";
    let progress = null;
    let pollCount = 0;
    while (pollCount < maxPolls) {
      pollCount += 1;
      progress = await uploadProgressClient.getProgress(upload.uploadHandoffId);
      if (progress.status === "INDEX_READY") break;
      if (progress.status === "FAILED" || progress.status === "CANCELLED") {
        throw workflowError("INGESTION_TERMINAL_FAILURE", progress.failure.retryable);
      }
    }
    if (
      progress?.status !== "INDEX_READY" ||
      progress.vectorIndex.retrievalUsable !== true
    ) {
      throw workflowError("INGESTION_NOT_READY", true);
    }
    state = advanceGoldenJourney(state, {
      stage: "INGESTION_INDEXED",
      occurredAt: clock(),
      refs: {
        processing_run_id: progress.ingestion.runId,
        document_id: progress.documentId
      }
    });

    return Object.freeze({
      journey_ingestion_schema_version: GOLDEN_JOURNEY_INGESTION_SCHEMA_VERSION,
      status: "INDEX_READY",
      journeyState: state,
      evidence: buildGoldenJourneyEvidence(state),
      session: safeSessionSummary(session),
      upload: safeUploadSummary(upload),
      progress: safeProgressSummary(progress, pollCount),
      failure: null
    });
  } catch (error) {
    const failureCode = phaseFailureCode(phase);
    const failedState = failGoldenJourney(state, {
      failureCode,
      occurredAt: clock(),
      retryable: Boolean(error?.retryable)
    });
    return Object.freeze({
      journey_ingestion_schema_version: GOLDEN_JOURNEY_INGESTION_SCHEMA_VERSION,
      status: "FAILED",
      journeyState: failedState,
      evidence: buildGoldenJourneyEvidence(failedState),
      session: null,
      upload: null,
      progress: null,
      failure: Object.freeze({
        failureCode,
        failedPhase: phase,
        retryable: Boolean(error?.retryable)
      })
    });
  }
}

function assertDependencies({ sessionClient, uploadClient, uploadProgressClient, clock }) {
  if (
    typeof sessionClient?.login !== "function" ||
    typeof uploadClient?.submitUploadDraft !== "function" ||
    typeof uploadProgressClient?.getProgress !== "function" ||
    typeof clock !== "function"
  ) {
    throw workflowError("WORKFLOW_DEPENDENCY_INVALID", false);
  }
}

function assertOwnerScope(upload, session) {
  if (
    upload?.ownerScope?.tenantId !== session.tenantRef.id ||
    upload?.ownerScope?.ownerUserId !== session.subjectRef.id ||
    !upload.uploadHandoffId ||
    !upload.documentId
  ) {
    throw workflowError("UPLOAD_OWNER_SCOPE_MISMATCH", false);
  }
}

function workflowError(status, retryable) {
  return Object.assign(new Error("Golden journey ingestion step failed."), {
    status,
    retryable
  });
}

function phaseFailureCode(phase) {
  return {
    LOGIN: "LOGIN_FAILED",
    UPLOAD: "UPLOAD_FAILED",
    INGESTION: "INGESTION_FAILED"
  }[phase] || "JOURNEY_FAILED";
}

function safeSessionSummary(session) {
  return Object.freeze({
    status: session.status,
    tenantRef: session.tenantRef.id,
    subjectRef: session.subjectRef.id,
    scopeCount: session.scopes?.length || 0
  });
}

function safeUploadSummary(upload) {
  return Object.freeze({
    status: upload.status,
    dedupeStatus: upload.dedupeStatus,
    uploadHandoffId: upload.uploadHandoffId,
    documentId: upload.documentId,
    clientMode: upload.clientMode
  });
}

function safeProgressSummary(progress, pollCount) {
  return Object.freeze({
    status: progress.status,
    progressPercent: progress.progressPercent,
    pollCount,
    processingRunId: progress.ingestion.runId,
    retrievalUsable: progress.vectorIndex.retrievalUsable,
    expectedVectorCount: progress.vectorIndex.expectedVectorCount,
    actualVectorCount: progress.vectorIndex.actualVectorCount,
    clientMode: progress.clientMode
  });
}
