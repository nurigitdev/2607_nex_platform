import assert from "node:assert/strict";
import test from "node:test";

import { createMockGroundedGenerationClient } from "../src/groundedGenerationClient.js";
import {
  GroundedGenerationWorkflowError,
  buildGroundedGenerationRequest,
  runGroundedGenerationWorkflow
} from "../src/groundedGenerationWorkflow.js";

function request(overrides = {}) {
  return buildGroundedGenerationRequest({
    interactionId: "interaction-workflow-1",
    workspaceId: "workspace-workflow-1",
    chatDocumentId: "chat-workflow-1",
    userMessage: "Summarize the selected document.",
    documentScope: {
      document_scope: { document_ids: ["doc-1", "doc-1", "doc-2"] }
    },
    grounded: true,
    ...overrides
  });
}

test("builds an async owner-neutral grounded request", () => {
  const payload = request();

  assert.equal(payload.generation.execution_strategy, "ASYNCHRONOUS");
  assert.equal(payload.generation.execution_mode, "GROUNDED_ANSWER");
  assert.deepEqual(payload.retrieval.document_scope.document_ids, ["doc-1", "doc-2"]);
  assert.equal(payload.retrieval.include_source_preview, false);
  assert.equal("tenant_id" in payload, false);
  assert.equal("owner_user_id" in payload, false);
  assert.equal("service_token" in payload, false);

  const general = request({ grounded: false, documentScope: null });
  assert.equal(general.generation.execution_mode, "GENERAL_ANSWER");
  assert.equal(general.retrieval.enabled, false);
  assert.equal(general.retrieval.document_scope, null);
});

test("runs admission, bounded polling, verified response, and citation quality", async () => {
  const states = [];
  const result = await runGroundedGenerationWorkflow({
    client: createMockGroundedGenerationClient(),
    request: request(),
    onState: state => states.push(state.phase)
  });

  assert.equal(result.status, "COMPLETED");
  assert.equal(result.pollCount, 2);
  assert.equal(result.pollLimitReached, false);
  assert.equal(result.state.response.content, "Grounded mock response [1].");
  assert.equal(result.state.citationQuality.workflowStatus, "VALIDATED");
  assert.equal(result.readModel.presentation.artifactHandoffAllowed, true);
  assert.deepEqual(states, [
    "admitting",
    "active",
    "active",
    "completed",
    "completed",
    "completed",
    "completed"
  ]);
  assert.equal(JSON.stringify(result.summary).includes("Grounded mock"), false);
  assert.equal(result.summary.metadata.generatedContentIncluded, false);
});

test("returns active state when the bounded poll limit is reached", async () => {
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      getProgress: ({ interactionId }) => ({
        progress_schema_version: "ae_generation_progress.v1",
        interaction_id: interactionId,
        lifecycle_status: "RUNNING",
        current_stage: "GENERATING",
        progress_mode: "INDETERMINATE",
        retryable: true,
        cancellable: true,
        terminal: false,
        next_poll_after_seconds: 1
      })
    }
  });
  const result = await runGroundedGenerationWorkflow({
    client,
    request: request(),
    maxPolls: 2
  });

  assert.equal(result.status, "ACTIVE");
  assert.equal(result.pollCount, 2);
  assert.equal(result.pollLimitReached, true);
  assert.equal(result.state.response, null);
  assert.equal(result.readModel.presentation.artifactHandoffAllowed, false);
});

test("converts client failures into redacted workflow failure state", async () => {
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      admitInteraction: () => {
        const error = new Error("private prompt and provider output");
        error.status = "HTTP_503";
        error.retryable = true;
        throw error;
      }
    }
  });
  const result = await runGroundedGenerationWorkflow({ client, request: request() });

  assert.equal(result.status, "FAILED");
  assert.equal(result.state.errorStatus, "HTTP_503");
  assert.equal(result.state.retryable, true);
  assert.equal(JSON.stringify(result).includes("private prompt and provider output"), false);
});

test("handles an aborted workflow without issuing client requests", async () => {
  let admitted = false;
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      admitInteraction: () => {
        admitted = true;
      }
    }
  });
  const result = await runGroundedGenerationWorkflow({
    client,
    request: request(),
    signal: { aborted: true }
  });

  assert.equal(admitted, false);
  assert.equal(result.status, "FAILED");
  assert.equal(result.state.errorStatus, "GENERATION_WORKFLOW_ABORTED");
});

test("rejects invalid request, client, scope, and poll limits", async () => {
  assert.throws(
    () => request({ interactionId: " " }),
    error => error.status === "GENERATION_WORKFLOW_FIELD_REQUIRED"
  );
  assert.throws(
    () => request({ documentScope: { document_scope: { document_ids: [] } } }),
    error => error.status === "GENERATION_DOCUMENT_SCOPE_REQUIRED"
  );
  await assert.rejects(
    runGroundedGenerationWorkflow({ client: {}, request: request() }),
    error => error instanceof GroundedGenerationWorkflowError
  );
  await assert.rejects(
    runGroundedGenerationWorkflow({
      client: createMockGroundedGenerationClient(),
      request: request(),
      maxPolls: 0
    }),
    error => error.status === "GENERATION_WORKFLOW_POLL_LIMIT_INVALID"
  );
});
