import assert from "node:assert/strict";
import test from "node:test";

import {
  InteractionAgentResultClientError,
  createFetchInteractionAgentResultClient,
  createMockInteractionAgentResultClient,
  interactionAgentResultRoute,
  projectInteractionAgentResult,
  renderInteractionAgentResult
} from "../src/interactionAgentResultClient.js";

const INTERACTION_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

function projection() {
  return {
    schema_version: "ae_interaction_agent_result.v1",
    interaction_id: INTERACTION_ID,
    workspace_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    agent_execution_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    execution_state: "SUCCEEDED",
    execution_phase: "FINALIZE",
    terminal: true,
    result: {
      result_ref: "AE:AGENT_RESULT:result-1",
      result_hash: `sha256:${"a".repeat(64)}`,
      status: "SUCCEEDED",
      business_refs: ["EOS:BUSINESS_OPERATION:business-1"],
      external_refs: ["EOS:VOUCHER:voucher-1"],
      artifact_refs: [],
      warnings: [],
      delivery: {
        state: "ACKNOWLEDGED",
        workspace_activity_ref: "AE:WORKSPACE_ACTIVITY:activity-1"
      }
    },
    updated_at: "2026-10-26T09:00:00Z",
    completed_at: "2026-10-26T09:00:00Z"
  };
}

test("projects and renders a reference-only completed IA result", () => {
  const result = projectInteractionAgentResult(projection(), {
    clientMode: "fetch",
    route: interactionAgentResultRoute(INTERACTION_ID)
  });

  assert.equal(result.executionState, "SUCCEEDED");
  assert.equal(result.result.deliveryState, "ACKNOWLEDGED");
  assert.equal(result.rawResultIncluded, false);
  const html = renderInteractionAgentResult(result);
  assert.match(html, /업무 처리 결과/);
  assert.match(html, /EOS:BUSINESS_OPERATION:business-1/);
  assert.doesNotMatch(html, /prompt/i);
});

test("fetch client uses same-origin credentials and the owner result route", async () => {
  const calls = [];
  const client = createFetchInteractionAgentResultClient({
    baseUrl: "http://ae.local",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, status: 200, json: async () => projection() };
    }
  });

  const result = await client.getInteractionAgentResult(INTERACTION_ID);

  assert.equal(result.terminal, true);
  assert.equal(calls[0].url, `http://ae.local${interactionAgentResultRoute(INTERACTION_ID)}`);
  assert.equal(calls[0].options.credentials, "include");
});

test("client rejects malformed records and projects bounded HTTP errors", async () => {
  assert.throws(
    () => projectInteractionAgentResult({}),
    InteractionAgentResultClientError
  );
  const client = createFetchInteractionAgentResultClient({
    fetchImpl: async () => ({
      ok: false,
      status: 404,
      json: async () => ({
        error_code: "ae.interaction_agent_result_not_found",
        detail: "not found"
      })
    })
  });
  await assert.rejects(
    client.getInteractionAgentResult(INTERACTION_ID),
    error => error.statusCode === 404
  );
});

test("mock client remains deterministic", async () => {
  const client = createMockInteractionAgentResultClient({
    responseFactory: () => projection()
  });

  assert.equal(
    (await client.getInteractionAgentResult(INTERACTION_ID)).result.status,
    "SUCCEEDED"
  );
});
