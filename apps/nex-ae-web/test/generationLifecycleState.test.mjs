import assert from "node:assert/strict";
import test from "node:test";

import { createMockGroundedGenerationClient } from "../src/groundedGenerationClient.js";
import {
  GenerationLifecycleStateError,
  applyCitationQuality,
  applyGenerationAdmission,
  applyGenerationProgress,
  applyGenerationRefresh,
  applyVerifiedGeneratedResponse,
  buildGenerationLifecycleReadModel,
  buildGenerationLifecycleSummary,
  createGenerationLifecycleState,
  markGenerationActionRunning,
  markGenerationAdmissionRunning,
  markGenerationLifecycleFailure
} from "../src/generationLifecycleState.js";

async function activeState(interactionId = "interaction-state-1") {
  const client = createMockGroundedGenerationClient();
  const initial = createGenerationLifecycleState({ clientMode: "mock" });
  const admitting = markGenerationAdmissionRunning(initial);
  return applyGenerationAdmission(
    admitting,
    await client.admitInteraction({ interaction_id: interactionId })
  );
}

test("creates a privacy-safe idle state and read model", () => {
  const state = createGenerationLifecycleState({ clientMode: "fetch" });
  const view = buildGenerationLifecycleReadModel(state);
  const summary = buildGenerationLifecycleSummary(state);

  assert.equal(state.phase, "idle");
  assert.equal(view.polling.enabled, false);
  assert.equal(view.controls.cancelEnabled, false);
  assert.equal(view.presentation.artifactHandoffAllowed, false);
  assert.equal(summary.client_mode, "fetch");
  assert.equal(JSON.stringify(summary).includes("content"), true);
  assert.equal(JSON.stringify(summary).includes("Grounded mock"), false);
});

test("moves admission into an active polling state", async () => {
  const state = await activeState();
  const view = buildGenerationLifecycleReadModel(state);

  assert.equal(state.phase, "active");
  assert.equal(state.lifecycleStatus, "PENDING");
  assert.equal(state.interactionId, "interaction-state-1");
  assert.equal(view.polling.enabled, true);
  assert.equal(view.polling.nextAfterSeconds, 2);
  assert.equal(view.controls.cancelEnabled, true);
});

test("applies running and terminal progress deterministically", async () => {
  const state = await activeState();
  const base = {
    groundedGenerationClientSchemaVersion: "ae_web_grounded_generation_client.v1",
    interactionId: state.interactionId,
    lifecycleStatus: "RUNNING",
    currentStage: "GENERATING",
    progressMode: "DETERMINATE",
    progressPercent: 60,
    messageKey: "generation.progress.generating",
    attemptCount: 1,
    maxAttempts: 3,
    cancellable: true,
    retryable: true,
    terminal: false,
    nextPollAfterSeconds: 3,
    recovery: { action: "WAIT", eligible: false }
  };
  const running = applyGenerationProgress(state, base);
  const completed = applyGenerationProgress(running, {
    ...base,
    lifecycleStatus: "COMPLETED",
    currentStage: "COMPLETED",
    progressPercent: 100,
    terminal: true,
    cancellable: false,
    retryable: false,
    nextPollAfterSeconds: null
  });

  assert.equal(running.progressPercent, 60);
  assert.equal(running.nextPollAfterSeconds, 3);
  assert.equal(completed.phase, "completed");
  assert.equal(completed.nextPollAfterSeconds, null);
  assert.equal(buildGenerationLifecycleReadModel(completed).polling.enabled, false);
});

test("accepts verified response and citation quality before artifact handoff", async () => {
  const client = createMockGroundedGenerationClient();
  let state = await activeState();
  state = applyVerifiedGeneratedResponse(
    state,
    await client.getResponse(state.interactionId)
  );
  assert.equal(
    buildGenerationLifecycleReadModel(state).presentation.artifactHandoffAllowed,
    false
  );

  state = applyCitationQuality(
    state,
    await client.getCitationQuality(state.interactionId)
  );
  const view = buildGenerationLifecycleReadModel(state);
  const summary = buildGenerationLifecycleSummary(state);

  assert.equal(state.response.content, "Grounded mock response [1].");
  assert.equal(view.presentation.responseReady, true);
  assert.equal(view.presentation.citationQualityReady, true);
  assert.equal(view.presentation.artifactHandoffAllowed, true);
  assert.equal("response" in summary, false);
  assert.equal(JSON.stringify(summary).includes("Grounded mock response"), false);
});

test("applies completed refresh content only after AE persistence", async () => {
  const client = createMockGroundedGenerationClient();
  const state = await activeState();
  const refreshed = applyGenerationRefresh(
    state,
    await client.refreshInteraction(state.interactionId)
  );

  assert.equal(refreshed.phase, "completed");
  assert.equal(refreshed.response.source, "refresh");
  assert.equal(refreshed.metadata.contentIncluded, true);
});

test("keeps action and failure state free of raw exception details", async () => {
  const state = await activeState();
  const running = markGenerationActionRunning(state, "cancel");
  const failed = markGenerationLifecycleFailure(running, {
    status: "HTTP_503",
    message: "private provider output",
    retryable: true
  });

  assert.equal(running.activeAction, "cancel");
  assert.equal(failed.phase, "failed");
  assert.equal(failed.errorStatus, "HTTP_503");
  assert.equal(failed.retryable, true);
  assert.equal(JSON.stringify(failed).includes("private provider output"), false);
  assert.equal(buildGenerationLifecycleReadModel(failed).controls.retryEnabled, true);
});

test("rejects invalid transitions, lineage, progress, and owner scope", async () => {
  const initial = createGenerationLifecycleState();
  const state = await activeState();
  assert.throws(
    () => markGenerationAdmissionRunning(state),
    error => error.status === "GENERATION_ADMISSION_CONFLICT"
  );
  assert.throws(
    () => applyGenerationProgress(state, {}),
    error => error.status === "GENERATION_PROGRESS_INVALID"
  );
  assert.throws(
    () =>
      applyGenerationProgress(state, {
        groundedGenerationClientSchemaVersion:
          "ae_web_grounded_generation_client.v1",
        interactionId: "other",
        progressPercent: 101
      }),
    error => error.status === "GENERATION_INTERACTION_LINEAGE_MISMATCH"
  );
  assert.throws(
    () =>
      applyVerifiedGeneratedResponse(state, {
        groundedGenerationClientSchemaVersion:
          "ae_web_grounded_generation_client.v1",
        interactionId: state.interactionId,
        content: "private",
        ownerScopeEnforced: false
      }),
    error => error.status === "GENERATED_RESPONSE_OWNER_SCOPE_REQUIRED"
  );
  assert.throws(
    () => markGenerationActionRunning(state, "delete"),
    error => error.status === "GENERATION_ACTION_UNSUPPORTED"
  );
  assert.throws(
    () => buildGenerationLifecycleSummary({}),
    error => error instanceof GenerationLifecycleStateError
  );
  assert.throws(
    () => createGenerationLifecycleState({ clientMode: "remote" }),
    error => error.status === "GENERATION_CLIENT_MODE_INVALID"
  );
  assert.equal(initial.interactionId, null);
});

test("rejects out-of-range progress after lineage is valid", async () => {
  const state = await activeState();
  assert.throws(
    () =>
      applyGenerationProgress(state, {
        groundedGenerationClientSchemaVersion:
          "ae_web_grounded_generation_client.v1",
        interactionId: state.interactionId,
        lifecycleStatus: "RUNNING",
        progressPercent: -1,
        terminal: false
      }),
    error => error.status === "GENERATION_PROGRESS_PERCENT_INVALID"
  );
  assert.throws(
    () =>
      applyGenerationProgress(state, {
        groundedGenerationClientSchemaVersion:
          "ae_web_grounded_generation_client.v1",
        interactionId: state.interactionId,
        lifecycleStatus: "RUNNING",
        progressPercent: 1,
        nextPollAfterSeconds: 61,
        terminal: false
      }),
    error => error.status === "GENERATION_POLL_DELAY_INVALID"
  );
});
