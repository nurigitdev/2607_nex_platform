import assert from "node:assert/strict";
import test from "node:test";

import { createMockGroundedGenerationClient } from "../src/groundedGenerationClient.js";
import {
  applyGenerationAdmission,
  createGenerationLifecycleState,
  markGenerationAdmissionRunning,
  markGenerationLifecycleFailure
} from "../src/generationLifecycleState.js";
import {
  GroundedGenerationRecoveryError,
  cancelGroundedGeneration,
  inspectGroundedGenerationRecovery,
  retryGroundedGeneration
} from "../src/groundedGenerationRecovery.js";
import { buildGroundedGenerationRequest } from "../src/groundedGenerationWorkflow.js";

async function activeState(client, interactionId = "interaction-parent") {
  const admitting = markGenerationAdmissionRunning(
    createGenerationLifecycleState({ clientMode: client.clientMode })
  );
  return applyGenerationAdmission(
    admitting,
    await client.admitInteraction({ interaction_id: interactionId })
  );
}

function failedState(client, interactionId = "interaction-parent") {
  return activeState(client, interactionId).then(state =>
    markGenerationLifecycleFailure(state, {
      status: "PROVIDER_UNAVAILABLE",
      retryable: true
    })
  );
}

function retryRecovery() {
  return {
    recovery_plan_schema_version: "ae_generation_recovery_plan.v1",
    action: "RETRY",
    eligible: true,
    reason_code: "PROVIDER_UNAVAILABLE",
    new_interaction_required: true,
    parent_lineage_required: true,
    input_hash_required: true
  };
}

function retryRequest(interactionId = "interaction-child") {
  return buildGroundedGenerationRequest({
    interactionId,
    workspaceId: "workspace-1",
    chatDocumentId: "chat-1",
    userMessage: "Retry the grounded answer.",
    documentScope: { document_scope: { document_ids: ["doc-1"] } },
    grounded: true
  });
}

test("cancels an active interaction and publishes terminal state", async () => {
  const client = createMockGroundedGenerationClient();
  const states = [];
  const result = await cancelGroundedGeneration({
    client,
    state: await activeState(client),
    onState: state => states.push([state.activeAction, state.phase])
  });

  assert.equal(result.action, "CANCEL");
  assert.equal(result.state.phase, "cancelled");
  assert.equal(result.readModel.controls.cancelEnabled, false);
  assert.deepEqual(states, [
    ["cancel", "active"],
    [null, "cancelled"]
  ]);
  assert.equal(result.summary.generated_content_included, false);
});

test("inspects recovery and enables retry only for an eligible plan", async () => {
  const client = createMockGroundedGenerationClient({
    responseFactories: { getRecovery: retryRecovery }
  });
  const result = await inspectGroundedGenerationRecovery({
    client,
    state: await failedState(client)
  });

  assert.equal(result.action, "RECOVERY");
  assert.equal(result.state.recovery.action, "RETRY");
  assert.equal(result.readModel.controls.retryEnabled, true);
  assert.equal(result.summary.recovery_eligible, true);
});

test("retries through the parent route and follows the child lifecycle", async () => {
  const retryCalls = [];
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      getRecovery: retryRecovery,
      retryInteraction: ({ interactionId, payload }) => {
        retryCalls.push([interactionId, payload.interaction_id]);
        return {
          interaction_schema_version: "ae_chat_interaction.v1",
          interaction_id: payload.interaction_id,
          workspace_id: payload.workspace_id,
          chat_document_id: payload.chat_document_id,
          status: "PENDING",
          cx_generation_id: "cx-child",
          cx_status: "QUEUED",
          generation: {
            async_generation: {
              lifecycle_status: "PENDING",
              retryable: true,
              cancellable: true
            }
          },
          artifact_refs: []
        };
      }
    }
  });
  const result = await retryGroundedGeneration({
    client,
    state: await failedState(client),
    request: retryRequest()
  });

  assert.equal(result.action, "RETRY");
  assert.equal(result.parentInteractionId, "interaction-parent");
  assert.equal(result.state.interactionId, "interaction-child");
  assert.equal(result.status, "COMPLETED");
  assert.deepEqual(retryCalls, [["interaction-parent", "interaction-child"]]);
  assert.equal(result.summary.raw_prompt_included, false);
});

test("rejects unsupported cancel, recovery, retry, and clients", async () => {
  const client = createMockGroundedGenerationClient();
  const idle = createGenerationLifecycleState();
  const failed = await failedState(client);

  await assert.rejects(
    cancelGroundedGeneration({ client, state: idle }),
    error => error.status === "GENERATION_CANCEL_NOT_ALLOWED"
  );
  await assert.rejects(
    inspectGroundedGenerationRecovery({ client, state: idle }),
    error => error.status === "GENERATION_RECOVERY_NOT_ALLOWED"
  );
  await assert.rejects(
    retryGroundedGeneration({ client, state: failed, request: retryRequest() }),
    error => error.status === "GENERATION_RETRY_NOT_ELIGIBLE"
  );
  await assert.rejects(
    retryGroundedGeneration({
      client: createMockGroundedGenerationClient({
        responseFactories: { getRecovery: retryRecovery }
      }),
      state: failed,
      request: retryRequest("interaction-parent")
    }),
    error => error.status === "GENERATION_RETRY_INTERACTION_REQUIRED"
  );
  await assert.rejects(
    cancelGroundedGeneration({ client: {}, state: idle }),
    error => error instanceof GroundedGenerationRecoveryError
  );
});

test("restores lifecycle action state when cancellation fails", async () => {
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      cancelInteraction: () => {
        const error = new Error("private provider detail");
        error.status = "HTTP_503";
        throw error;
      }
    }
  });
  const states = [];
  await assert.rejects(
    cancelGroundedGeneration({
      client,
      state: await activeState(client),
      onState: state => states.push(state)
    }),
    error => error.status === "HTTP_503"
  );

  assert.equal(states.at(-1).phase, "active");
  assert.equal(states.at(-1).activeAction, null);
  assert.equal(states.at(-1).errorStatus, "HTTP_503");
  assert.equal(JSON.stringify(states.at(-1)).includes("private provider"), false);
});
