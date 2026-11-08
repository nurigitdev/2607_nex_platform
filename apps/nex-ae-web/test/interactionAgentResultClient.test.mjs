import assert from "node:assert/strict";
import test from "node:test";

import {
  InteractionAgentResultClientError,
  createFetchInteractionAgentResultClient,
  createMockInteractionAgentResultClient,
  interactionAgentResultRoute,
  projectBusinessResultSummary,
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
      business_summary: {
        result_type: "FINANCE.VOUCHER_DRAFT",
        summary_schema_version: "ae_business_result_summary.v1",
        summary: {
          outcome: "COMMITTED",
          verification_status: "VERIFIED",
          approval_state: "APPROVED",
          business_operation_id: "business-1",
          voucher_number: "voucher-1",
          amount: "12500.00",
          currency: "KRW",
          account_codes: ["TRAVEL", "CASH"],
          project_code: "NVT",
          business_object_link: null
        }
      },
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
  assert.equal(result.result.businessSummary.voucherNumber, "voucher-1");
  assert.equal(result.rawResultIncluded, false);
  const html = renderInteractionAgentResult(result);
  assert.match(html, /업무 처리 결과/);
  assert.match(html, /12500.00 KRW/);
  assert.match(html, /NVT/);
  assert.doesNotMatch(html, /EOS:BUSINESS_OPERATION/);
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

test("unknown business types stay generic and malformed known types fail closed", () => {
  assert.equal(
    projectBusinessResultSummary({
      result_type: "UNKNOWN.RESULT",
      summary_schema_version: "unknown.v1",
      summary: { raw: "hidden" }
    }),
    null
  );
  assert.throws(
    () => projectBusinessResultSummary({
      result_type: "FINANCE.VOUCHER_DRAFT",
      summary_schema_version: "ae_business_result_summary.v1",
      summary: { amount: "1.00" }
    }),
    error => error.status === "BUSINESS_RESULT_SUMMARY_INVALID"
  );
});
