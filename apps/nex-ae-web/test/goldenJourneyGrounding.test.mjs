import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createMockGroundedGenerationClient } from "../src/groundedGenerationClient.js";
import { runGoldenJourneyGrounding } from "../src/goldenJourneyGrounding.js";
import {
  advanceGoldenJourney,
  createGoldenJourneyState
} from "../src/goldenJourneyState.js";
import { buildGroundedGenerationRequest } from "../src/groundedGenerationWorkflow.js";

describe("AE Web retrieval-generation-grounding golden journey", () => {
  it("correlates retrieval, generation, citations, and validated quality", async () => {
    const result = await runGoldenJourneyGrounding({
      journeyState: ingestedState("journey-grounding-001"),
      generationClient: createMockGroundedGenerationClient(),
      generationRequest: request("interaction-grounding-001"),
      clock: sequenceClock(4)
    });

    assert.equal(result.status, "GROUNDING_ACCEPTED");
    assert.equal(result.journeyState.completed_stages.length, 6);
    assert.equal(result.retrieval.status, "READY");
    assert.equal(result.retrieval.warningCount, 0);
    assert.equal(result.generation.status, "COMPLETED");
    assert.equal(result.grounding.citationCount, 1);
    assert.equal(result.grounding.qualityStatus, "VALIDATED");
    assert.equal(result.grounding.artifactHandoffAllowed, true);
    assert.doesNotMatch(
      JSON.stringify(result),
      /Grounded mock response|Build a grounded answer/
    );
  });

  it("accepts one repaired response review without retaining repaired content", async () => {
    const interactionId = "interaction-grounding-repaired";
    const client = createMockGroundedGenerationClient({
      responseFactories: {
        getCitationQuality: ({ interactionId: actual }) => ({
          workflow_schema_version: "ae_citation_quality_workflow.v1",
          interaction_id: actual,
          cx_generation_id: "cx-generation-web-local",
          workflow_status: "REPAIRED",
          next_action: "PRESENT_REPAIRED_RESPONSE",
          quality: {
            boundary_status: "PASS",
            citation_status: "VALIDATED",
            issue_count: 0,
            recommended_action: "proceed"
          },
          repair: { status: "SUCCEEDED", attempted: true },
          operator_remediation: { required: false },
          owner_scope_enforced: true,
          content_included: false
        })
      }
    });
    const result = await runGoldenJourneyGrounding({
      journeyState: ingestedState("journey-grounding-002"),
      generationClient: client,
      generationRequest: request(interactionId),
      repairedResponseReviewClient: {
        async listRepairedResponseReviews(actual) {
          return {
            items: [
              {
                interactionId: actual,
                repairedResponseHandoffId: "repair-handoff-001",
                clientMode: "mock"
              }
            ]
          };
        }
      },
      clock: sequenceClock(4)
    });

    assert.equal(result.status, "GROUNDING_ACCEPTED");
    assert.equal(result.grounding.displayMode, "REPAIRED_RESPONSE_REVIEW");
    assert.equal(result.grounding.repairAttemptCount, 1);
    assert.equal(result.grounding.qualityStatus, "REPAIRED");
    assert.equal(result.grounding.artifactHandoffAllowed, false);
  });

  it("fails at retrieval when the admission package is unavailable", async () => {
    const client = createMockGroundedGenerationClient({
      responseFactories: {
        admitInteraction: ({ payload }) => ({
          interaction_schema_version: "ae_chat_interaction.v1",
          interaction_id: payload.interaction_id,
          chat_document_id: payload.chat_document_id,
          status: "PENDING",
          generation: {
            execution_strategy: "ASYNCHRONOUS",
            execution_mode: "GROUNDED_ANSWER",
            lifecycle_status: "PENDING",
            retryable: true,
            cancellable: true
          },
          retrieval: {
            cx_retrieval_package_id: null,
            cx_status: "NO_ANSWER",
            evidence_count: 0,
            warnings: [],
            quality_warnings: {
              contract_schema_version: "ae_chat_retrieval_quality_warning.v1",
              recommended_action: "show_no_answer"
            }
          },
          artifact_refs: []
        })
      }
    });
    const result = await runGoldenJourneyGrounding({
      journeyState: ingestedState("journey-grounding-003"),
      generationClient: client,
      generationRequest: request("interaction-grounding-no-answer"),
      clock: sequenceClock(4)
    });

    assert.equal(result.status, "FAILED");
    assert.equal(result.failure.failureCode, "RETRIEVAL_FAILED");
    assert.equal(result.evidence.failure.failed_stage, "RETRIEVAL_READY");
  });

  it("fails closed on generation and grounding quality failures", async () => {
    const generationFailure = await runGoldenJourneyGrounding({
      journeyState: ingestedState("journey-grounding-004"),
      generationClient: {
        clientMode: "mock",
        async admitInteraction() { throw new Error("private prompt"); },
        async getProgress() {},
        async refreshInteraction() {},
        async getResponse() {},
        async getCitationQuality() {}
      },
      generationRequest: request("interaction-grounding-failed"),
      clock: sequenceClock(4)
    });
    assert.equal(generationFailure.failure.failureCode, "RETRIEVAL_FAILED");
    assert.equal(JSON.stringify(generationFailure).includes("private prompt"), false);

    const qualityClient = createMockGroundedGenerationClient({
      responseFactories: {
        getCitationQuality: ({ interactionId }) => ({
          workflow_schema_version: "ae_citation_quality_workflow.v1",
          interaction_id: interactionId,
          cx_generation_id: "cx-generation-web-local",
          workflow_status: "ATTENTION_REQUIRED",
          next_action: "RETRY_OR_REVIEW_GENERATION",
          quality: {
            boundary_status: "FAIL",
            citation_status: "INVALID",
            issue_count: 1,
            recommended_action: "show_error"
          },
          repair: { status: "FAILED", attempted: true },
          operator_remediation: { required: true },
          owner_scope_enforced: true,
          content_included: false
        })
      }
    });
    const groundingFailure = await runGoldenJourneyGrounding({
      journeyState: ingestedState("journey-grounding-005"),
      generationClient: qualityClient,
      generationRequest: request("interaction-grounding-quality"),
      clock: sequenceClock(4)
    });
    assert.equal(groundingFailure.failure.failureCode, "GROUNDING_FAILED");
    assert.equal(groundingFailure.evidence.failure.failed_stage, "GROUNDING_ACCEPTED");
  });
});

function ingestedState(journeyId) {
  let state = createGoldenJourneyState({
    journeyId,
    startedAt: "2026-10-06T00:00:00.000Z"
  });
  const prior = [
    ["SESSION_AUTHENTICATED", { subject_ref: "owner-local" }],
    ["UPLOAD_ACCEPTED", { upload_handoff_id: "handoff-local" }],
    ["INGESTION_INDEXED", { processing_run_id: "run-local" }]
  ];
  prior.forEach(([stage, refs], index) => {
    state = advanceGoldenJourney(state, {
      stage,
      occurredAt: `2026-10-06T00:00:0${index + 1}.000Z`,
      refs
    });
  });
  return state;
}

function request(interactionId) {
  return buildGroundedGenerationRequest({
    interactionId,
    workspaceId: "workspace-local",
    chatDocumentId: "chat-local",
    userMessage: "Build a grounded answer.",
    documentScope: { document_scope: { document_ids: ["doc-local"] } },
    grounded: true
  });
}

function sequenceClock(start) {
  let second = start;
  return () => `2026-10-06T00:00:0${second++}.000Z`;
}
