import assert from "node:assert/strict";
import test from "node:test";

import {
  AE_CHAT_INTERACTIONS_ROUTE,
  GroundedGenerationClientError,
  buildGeneratedResponseResult,
  buildInteractionResult,
  createFetchGroundedGenerationClient,
  createMockGroundedGenerationClient
} from "../src/groundedGenerationClient.js";

function response(payload, { ok = true, status = 200, jsonError = false } = {}) {
  return {
    ok,
    status,
    async json() {
      if (jsonError) throw new Error("invalid json");
      return payload;
    }
  };
}

test("mock client exposes the complete owner-safe lifecycle", async () => {
  const client = createMockGroundedGenerationClient();
  const admitted = await client.admitInteraction({ interaction_id: "interaction-1" });
  const loaded = await client.getInteraction("interaction-1");
  const progress = await client.getProgress("interaction-1");
  const refreshed = await client.refreshInteraction("interaction-1");
  const recovery = await client.getRecovery("interaction-1");
  const generated = await client.getResponse("interaction-1");
  const quality = await client.getCitationQuality("interaction-1");
  const cancelled = await client.cancelInteraction("interaction-1");
  const retried = await client.retryInteraction("interaction-1", {
    interaction_id: "interaction-2"
  });

  assert.equal(client.clientMode, "mock");
  assert.equal(admitted.interactionId, "interaction-1");
  assert.equal(loaded.metadata.contentIncluded, false);
  assert.equal(progress.nextPollAfterSeconds, 2);
  assert.equal(refreshed.content, "Grounded mock response [1].");
  assert.equal(refreshed.metadata.contentIncluded, true);
  assert.equal(recovery.action, "WAIT");
  assert.equal(generated.ownerScopeEnforced, true);
  assert.equal(quality.workflowStatus, "VALIDATED");
  assert.equal(cancelled.status, "CANCELLED");
  assert.equal(retried.interactionId, "interaction-2");
  assert.deepEqual(admitted.metadata, {
    contentIncluded: false,
    browserServiceTokenIncluded: false,
    providerUrlIncluded: false,
    databaseUrlIncluded: false,
    storageRefIncluded: false
  });
});

test("mock response factories receive safe operation context", async () => {
  let observed;
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      getProgress(context) {
        observed = context;
        return {
          progress_schema_version: "ae_generation_progress.v1",
          interaction_id: context.interactionId,
          lifecycle_status: "FAILED",
          terminal: true,
          retryable: true,
          cancellable: false
        };
      }
    }
  });

  const result = await client.getProgress("interaction factory");

  assert.equal(result.lifecycleStatus, "FAILED");
  assert.equal(observed.interactionId, "interaction factory");
  assert.equal(
    observed.route,
    "/api/v1/chat/interactions/interaction%20factory/progress"
  );
});

test("fetch admission uses same-origin JSON without browser credentials", async () => {
  const calls = [];
  const client = createFetchGroundedGenerationClient({
    baseUrl: "https://ae.example",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return response({
        interaction_schema_version: "ae_chat_interaction.v1",
        interaction_id: "interaction-fetch",
        status: "PENDING",
        generation: { async_generation: { retryable: true } },
        artifact_refs: []
      }, { status: 202 });
    }
  });

  const result = await client.admitInteraction({
    interaction_id: "interaction-fetch",
    user_message: "private prompt"
  });

  assert.equal(result.clientMode, "fetch");
  assert.equal(calls[0].url, `https://ae.example${AE_CHAT_INTERACTIONS_ROUTE}`);
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.deepEqual(calls[0].options.headers, {
    Accept: "application/json",
    "Content-Type": "application/json"
  });
  assert.equal(JSON.parse(calls[0].options.body).user_message, "private prompt");
  assert.equal("Authorization" in calls[0].options.headers, false);
});

test("fetch lifecycle methods use canonical encoded routes and body policy", async () => {
  const calls = [];
  const interaction = {
    interaction_schema_version: "ae_chat_interaction.v1",
    interaction_id: "interaction/one",
    status: "PENDING"
  };
  const client = createFetchGroundedGenerationClient({
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      if (url.endsWith("/progress")) {
        return response({
          progress_schema_version: "ae_generation_progress.v1",
          interaction_id: "interaction/one",
          terminal: false
        });
      }
      if (url.endsWith("/recovery")) {
        return response({
          recovery_plan_schema_version: "ae_generation_recovery_plan.v1",
          action: "WAIT"
        });
      }
      return response(interaction);
    }
  });

  await client.getInteraction(" interaction/one ");
  await client.getProgress("interaction/one");
  await client.getRecovery("interaction/one");
  await client.cancelInteraction("interaction/one");
  await client.retryInteraction("interaction/one", { interaction_id: "child" });

  assert.deepEqual(
    calls.map(call => [call.url, call.options.method, "body" in call.options]),
    [
      ["/api/v1/chat/interactions/interaction%2Fone", "GET", false],
      ["/api/v1/chat/interactions/interaction%2Fone/progress", "GET", false],
      ["/api/v1/chat/interactions/interaction%2Fone/recovery", "GET", false],
      ["/api/v1/chat/interactions/interaction%2Fone/cancel", "POST", false],
      ["/api/v1/chat/interactions/interaction%2Fone/retry", "POST", true]
    ]
  );
});

test("fetch client classifies network and HTTP failures", async () => {
  const networkClient = createFetchGroundedGenerationClient({
    fetchImpl: async () => {
      throw new Error("private network detail");
    }
  });
  await assert.rejects(
    networkClient.getProgress("interaction-1"),
    error =>
      error instanceof GroundedGenerationClientError &&
      error.status === "NETWORK_ERROR" &&
      error.retryable === true &&
      !error.message.includes("private network detail")
  );

  const conflictClient = createFetchGroundedGenerationClient({
    fetchImpl: async () =>
      response(
        { detail: "Interaction is terminal.", error_code: "ae.not_cancellable" },
        { ok: false, status: 409 }
      )
  });
  await assert.rejects(
    conflictClient.cancelInteraction("interaction-1"),
    error =>
      error.status === "ae.not_cancellable" &&
      error.statusCode === 409 &&
      error.retryable === false
  );

  const unavailableClient = createFetchGroundedGenerationClient({
    fetchImpl: async () => response(null, { ok: false, status: 503, jsonError: true })
  });
  await assert.rejects(
    unavailableClient.getProgress("interaction-1"),
    error => error.status === "HTTP_503" && error.retryable === true
  );
});

test("client rejects missing fetch, identifiers, payloads, and schema drift", async () => {
  assert.throws(
    () => createFetchGroundedGenerationClient({ fetchImpl: 42 }),
    error => error.status === "FETCH_UNAVAILABLE"
  );
  const client = createMockGroundedGenerationClient();
  assert.throws(() => client.getProgress(" "), /interactionId is required/);
  assert.throws(() => client.admitInteraction([]), /admission payload is invalid/);
  assert.throws(
    () => client.retryInteraction("interaction-1", null),
    /retry payload is invalid/
  );
  assert.throws(
    () => buildInteractionResult({ interaction_schema_version: "wrong" }),
    error => error.status === "CHAT_INTERACTION_INVALID"
  );
  assert.throws(
    () =>
      buildGeneratedResponseResult({
        response_schema_version: "ae_generated_response.v1",
        content: null
      }),
    error => error.status === "GENERATED_RESPONSE_CONTENT_INVALID"
  );
});

test("unknown mock operation fails closed through a custom proxy call", async () => {
  const client = createMockGroundedGenerationClient({
    responseFactories: {
      admitInteraction: () => ({ interaction_schema_version: "wrong" })
    }
  });
  await assert.rejects(
    client.admitInteraction({ interaction_id: "interaction-1" }),
    error => error.status === "CHAT_INTERACTION_INVALID"
  );
});
