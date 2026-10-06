import {
  advanceGoldenJourney,
  buildGoldenJourneyEvidence,
  failGoldenJourney
} from "./goldenJourneyState.js";
import { buildGroundedGenerationPresentation } from "./groundedGenerationPresentation.js";
import { runGroundedGenerationWorkflow } from "./groundedGenerationWorkflow.js";

export const GOLDEN_JOURNEY_GROUNDING_SCHEMA_VERSION =
  "ae_web_golden_journey_grounding.v1";

export async function runGoldenJourneyGrounding({
  journeyState,
  generationClient,
  generationRequest,
  repairedResponseReviewClient = null,
  maxPolls = 5,
  wait = async () => {},
  clock = () => new Date().toISOString()
}) {
  let state = journeyState;
  let phase = "RETRIEVAL";
  try {
    const workflow = await runGroundedGenerationWorkflow({
      client: generationClient,
      request: generationRequest,
      maxPolls,
      wait
    });
    if (workflow.status !== "COMPLETED") {
      throw boundedError("GENERATION_WORKFLOW_INCOMPLETE", workflow.state?.retryable);
    }
    const presentation = await buildGroundedGenerationPresentation({
      workflow,
      repairedResponseReviewClient
    });
    const retrieval = presentation.retrievalResult;
    if (retrieval?.cxStatus !== "READY" || !retrieval.cxRetrievalPackageId) {
      throw boundedError("RETRIEVAL_NOT_READY", retrieval?.retryable);
    }
    state = advanceGoldenJourney(state, {
      stage: "RETRIEVAL_READY",
      occurredAt: clock(),
      refs: {
        retrieval_id: retrieval.cxRetrievalPackageId,
        interaction_id: workflow.state.interactionId
      },
      details: {
        warning_count: warningCount(presentation.retrievalQualityWarning)
      }
    });

    phase = "GENERATION";
    const generationId = workflow.admission?.cxGenerationId;
    if (!workflow.state.response?.responseId || !generationId) {
      throw boundedError("GENERATION_LINEAGE_INCOMPLETE", false);
    }
    state = advanceGoldenJourney(state, {
      stage: "GENERATION_COMPLETED",
      occurredAt: clock(),
      refs: {
        interaction_id: workflow.state.interactionId,
        generation_id: generationId,
        response_id: workflow.state.response.responseId
      }
    });

    phase = "GROUNDING";
    const repaired = presentation.displayMode === "REPAIRED_RESPONSE_REVIEW";
    if (
      !["VERIFIED_RESPONSE", "REPAIRED_RESPONSE_REVIEW"].includes(
        presentation.displayMode
      ) ||
      presentation.groundedResponseQuality.recommended_action === "show_error"
    ) {
      throw boundedError("GROUNDING_QUALITY_REJECTED", false);
    }
    const citationCount = countCitationMarkers(workflow.state.response.content);
    state = advanceGoldenJourney(state, {
      stage: "GROUNDING_ACCEPTED",
      occurredAt: clock(),
      refs: {
        response_id: workflow.state.response.responseId,
        generation_id: generationId
      },
      details: {
        citation_count: citationCount,
        repair_attempt_count: repaired || workflow.state.citationQuality?.repair?.attempted ? 1 : 0,
        quality_status: repaired ? "REPAIRED" : "VALIDATED"
      }
    });

    return Object.freeze({
      journey_grounding_schema_version: GOLDEN_JOURNEY_GROUNDING_SCHEMA_VERSION,
      status: "GROUNDING_ACCEPTED",
      journeyState: state,
      evidence: buildGoldenJourneyEvidence(state),
      retrieval: Object.freeze({
        status: retrieval.cxStatus,
        retrievalId: retrieval.cxRetrievalPackageId,
        evidenceCount: retrieval.evidenceCount,
        warningCount: warningCount(presentation.retrievalQualityWarning),
        recommendedAction:
          presentation.retrievalQualityWarning.recommended_action
      }),
      generation: Object.freeze({
        status: workflow.status,
        interactionId: workflow.state.interactionId,
        generationId,
        responseId: workflow.state.response.responseId,
        pollCount: workflow.pollCount
      }),
      grounding: Object.freeze({
        displayMode: presentation.displayMode,
        citationWorkflowStatus: presentation.citationWorkflowStatus,
        citationCount,
        repairAttemptCount:
          repaired || workflow.state.citationQuality?.repair?.attempted ? 1 : 0,
        qualityStatus: repaired ? "REPAIRED" : "VALIDATED",
        artifactHandoffAllowed: presentation.artifactHandoffAllowed
      }),
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
      journey_grounding_schema_version: GOLDEN_JOURNEY_GROUNDING_SCHEMA_VERSION,
      status: "FAILED",
      journeyState: failedState,
      evidence: buildGoldenJourneyEvidence(failedState),
      retrieval: null,
      generation: null,
      grounding: null,
      failure: Object.freeze({
        failureCode,
        failedPhase: phase,
        retryable: Boolean(error?.retryable)
      })
    });
  }
}

function warningCount(surface) {
  if (!surface) return 0;
  return (
    (Number.isInteger(surface.warning_count) ? surface.warning_count : 0) +
    (Number.isInteger(surface.quality_flag_count) ? surface.quality_flag_count : 0)
  );
}

function countCitationMarkers(content) {
  if (typeof content !== "string") return 0;
  return new Set(content.match(/\[[1-9][0-9]*\]/g) || []).size;
}

function boundedError(status, retryable = false) {
  return Object.assign(new Error("Golden journey grounding failed."), {
    status,
    retryable: Boolean(retryable)
  });
}

function phaseFailureCode(phase) {
  return {
    RETRIEVAL: "RETRIEVAL_FAILED",
    GENERATION: "GENERATION_FAILED",
    GROUNDING: "GROUNDING_FAILED"
  }[phase] || "GROUNDING_FAILED";
}
