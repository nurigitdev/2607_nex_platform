import assert from "node:assert/strict";
import test from "node:test";

import { createMockGroundedGenerationClient } from "../src/groundedGenerationClient.js";
import {
  GroundedGenerationPresentationError,
  buildAdmissionRetrievalResult,
  buildGroundedGenerationPresentation,
  buildGroundedGenerationPresentationFailure,
  buildGroundedGenerationPresentationSummary
} from "../src/groundedGenerationPresentation.js";
import {
  buildGroundedGenerationRequest,
  runGroundedGenerationWorkflow
} from "../src/groundedGenerationWorkflow.js";

function request() {
  return buildGroundedGenerationRequest({
    interactionId: "interaction-presentation-1",
    workspaceId: "workspace-presentation-1",
    chatDocumentId: "chat-presentation-1",
    userMessage: "Build a grounded answer.",
    documentScope: { document_scope: { document_ids: ["doc-1", "doc-2"] } },
    grounded: true
  });
}

async function completedWorkflow() {
  return runGroundedGenerationWorkflow({
    client: createMockGroundedGenerationClient(),
    request: request()
  });
}

function withCitationAction(workflow, nextAction, workflowStatus) {
  return {
    ...workflow,
    state: {
      ...workflow.state,
      citationQuality: {
        ...workflow.state.citationQuality,
        nextAction,
        workflowStatus
      }
    }
  };
}

test("presents only an owner-verified response with validated citation quality", async () => {
  const presentation = await buildGroundedGenerationPresentation({
    workflow: await completedWorkflow()
  });

  assert.equal(presentation.displayMode, "VERIFIED_RESPONSE");
  assert.equal(presentation.assistantText, "Grounded mock response [1].");
  assert.equal(presentation.artifactHandoffAllowed, true);
  assert.equal(presentation.retrievalResult.cxStatus, "READY");
  assert.equal(presentation.retrievalResult.evidenceCount, 2);
  assert.equal(presentation.retrievalQualityWarning.severity, "success");
  assert.equal(presentation.summary.retrieval_available, true);
  assert.equal(JSON.stringify(presentation.summary).includes("Grounded mock"), false);
});

test("presents a compiled semantic plan as an active Agent execution", async () => {
  const workflow = {
    ...(await completedWorkflow()),
    status: "ACTIVE",
    agentExecutionAdmitted: true,
    groundingRequested: false
  };
  const presentation = await buildGroundedGenerationPresentation({ workflow });

  assert.equal(presentation.displayMode, "AGENT_EXECUTION");
  assert.equal(presentation.assistantText, "Agent가 요청을 처리하고 있습니다.");
  assert.equal(presentation.agentExecutionAdmitted, true);
  assert.equal(presentation.artifactHandoffAllowed, false);
  assert.equal(presentation.summary.agent_execution_admitted, true);
});

test("projects an owner-verified batch result into the message presentation", async () => {
  const workflow = await completedWorkflow();
  const projection = {
    schema_version: "p8.project_membership_batch_result_projection.v1",
    operation_id: "PROJECT.MEMBERSHIP.ADD_MANY",
    project_id: "project-batch",
    member_role: "MEMBER",
    overall_status: "PARTIALLY_APPLIED",
    business_result_ref: "eos:batch",
    summary: {
      requested_count: 2,
      admitted_count: 1,
      applied_count: 1,
      total_rejected_count: 1
    },
    items: [
      {
        stage: "OA_RESOLUTION",
        input_index: 1,
        subject_id: null,
        normalized_employee_id: "emp-2",
        outcome: "NAME_MISMATCH",
        applied: false
      },
      {
        stage: "EOS_COMMIT",
        input_index: null,
        subject_id: "subject-1",
        normalized_employee_id: null,
        outcome: "ADDED",
        applied: true
      }
    ]
  };
  workflow.state.response.projectMembershipBatchResult = projection;

  const presentation = await buildGroundedGenerationPresentation({ workflow });

  assert.equal(presentation.projectMembershipBatchResult.appliedCount, 1);
  assert.equal(presentation.projectMembershipBatchResult.rejectedCount, 1);
  assert.equal("projectMembershipBatchResult" in presentation.summary, false);
});

test("blocks an original response when citation quality requires attention", async () => {
  const workflow = withCitationAction(
    await completedWorkflow(),
    "RETRY_OR_REVIEW_GENERATION",
    "ATTENTION_REQUIRED"
  );
  const presentation = await buildGroundedGenerationPresentation({ workflow });

  assert.equal(presentation.displayMode, "QUALITY_ATTENTION_REQUIRED");
  assert.equal(presentation.assistantText.includes("인용 품질"), true);
  assert.equal(presentation.artifactHandoffAllowed, false);
  assert.equal(presentation.repairedResponseReview, null);
});

test("loads an owner-scoped repaired response review before presentation", async () => {
  const workflow = withCitationAction(
    await completedWorkflow(),
    "PRESENT_REPAIRED_RESPONSE",
    "REPAIRED"
  );
  const reviewSurface = {
    interactionId: workflow.state.interactionId,
    repairedResponseHandoffId: "repair-handoff-1",
    clientMode: "fetch"
  };
  const presentation = await buildGroundedGenerationPresentation({
    workflow,
    repairedResponseReviewClient: {
      async listRepairedResponseReviews(interactionId) {
        assert.equal(interactionId, workflow.state.interactionId);
        return { items: [reviewSurface] };
      }
    }
  });

  assert.equal(presentation.displayMode, "REPAIRED_RESPONSE_REVIEW");
  assert.equal(
    presentation.repairedResponseReview.repairedResponseHandoffId,
    "repair-handoff-1"
  );
  assert.equal(
    presentation.repairedResponseReview.decisionState.status,
    "READY_FOR_DECISION"
  );
  assert.equal(presentation.artifactHandoffAllowed, false);
});

test("projects metadata-only retrieval from generation admission", async () => {
  const workflow = await completedWorkflow();
  const result = buildAdmissionRetrievalResult(workflow.admission);

  assert.equal(result.retrievalInteractionId, workflow.state.interactionId);
  assert.equal(result.cxRetrievalPackageId, "cx-ret-web-local");
  assert.equal(result.userMessageHash, null);
  assert.equal(result.metadata.sourcePreviewIncluded, false);
  assert.equal(buildAdmissionRetrievalResult(null), null);
  assert.equal(
    buildAdmissionRetrievalResult({
      groundedGenerationClientSchemaVersion:
        "ae_web_grounded_generation_client.v1",
      retrieval: null
    }),
    null
  );
});

test("fails closed for invalid workflow, admission, repair client, and summary", async () => {
  assert.throws(
    () => buildAdmissionRetrievalResult({}),
    error => error.status === "GENERATION_ADMISSION_PRESENTATION_INVALID"
  );
  await assert.rejects(
    buildGroundedGenerationPresentation({ workflow: {} }),
    error => error instanceof GroundedGenerationPresentationError
  );
  const repaired = withCitationAction(
    await completedWorkflow(),
    "PRESENT_REPAIRED_RESPONSE",
    "REPAIRED"
  );
  await assert.rejects(
    buildGroundedGenerationPresentation({ workflow: repaired }),
    error => error.status === "REPAIRED_RESPONSE_REVIEW_CLIENT_REQUIRED"
  );
  await assert.rejects(
    buildGroundedGenerationPresentation({
      workflow: repaired,
      repairedResponseReviewClient: {
        async listRepairedResponseReviews() {
          return { items: [{ interactionId: "other" }] };
        }
      }
    }),
    error => error.status === "REPAIRED_RESPONSE_REVIEW_UNAVAILABLE"
  );
  assert.throws(
    () => buildGroundedGenerationPresentationSummary({}),
    error => error instanceof GroundedGenerationPresentationError
  );

  const workflow = await completedWorkflow();
  const fallback = buildGroundedGenerationPresentationFailure(workflow, {
    status: "REVIEW_HTTP_503",
    message: "private detail"
  });
  assert.equal(fallback.displayMode, "PRESENTATION_UNAVAILABLE");
  assert.equal(fallback.errorStatus, "REVIEW_HTTP_503");
  assert.equal(fallback.artifactHandoffAllowed, false);
  assert.equal(JSON.stringify(fallback.summary).includes("private detail"), false);
});
