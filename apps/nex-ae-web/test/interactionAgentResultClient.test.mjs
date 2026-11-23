import assert from "node:assert/strict";
import test from "node:test";

import {
  InteractionAgentResultClientError,
  createFetchInteractionAgentResultClient,
  createMockInteractionAgentResultClient,
  interactionAgentResultRoute,
  projectBusinessResultSummary,
  projectInteractionAgentResult
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

test("projects a reference-only completed IA result", () => {
  const result = projectInteractionAgentResult(projection(), {
    clientMode: "fetch",
    route: interactionAgentResultRoute(INTERACTION_ID)
  });

  assert.equal(result.executionState, "SUCCEEDED");
  assert.equal(result.result.deliveryState, "ACKNOWLEDGED");
  assert.equal(result.result.businessSummary.voucherNumber, "voucher-1");
  assert.equal(result.rawResultIncluded, false);
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

test("projects an ordered project-allocation result without exposing raw financial values", () => {
  const summary = projectBusinessResultSummary(projectAllocationSummary());

  assert.equal(summary.resultType, "FINANCE.PROJECT_ALLOCATION");
  assert.equal(summary.outcome, "ALLOCATED_AND_VERIFIED");
  assert.deepEqual(
    summary.projectProjections.map(item => item.projectCode),
    ["VO00D260001", "VO00D260002"]
  );
  assert.equal(summary.projectProjections[0].reconciliationStatus, "VERIFIED");
  assert.equal(JSON.stringify(summary).includes("posted_allocated_cost"), false);
  assert.equal(Object.isFrozen(summary), true);
  assert.equal(Object.isFrozen(summary.projectProjections), true);
});

test("project-allocation projection rejects unordered, tampered, and extended payloads", () => {
  const unordered = projectAllocationSummary();
  unordered.summary.project_projections.reverse();
  assert.throws(
    () => projectBusinessResultSummary(unordered),
    error => error.status === "BUSINESS_RESULT_SUMMARY_INVALID"
  );

  const tampered = projectAllocationSummary();
  tampered.summary.pnl_refresh_hash = "sha256:not-a-hash";
  assert.throws(
    () => projectBusinessResultSummary(tampered),
    error => error.status === "BUSINESS_RESULT_SUMMARY_INVALID"
  );

  const extended = projectAllocationSummary();
  extended.summary.project_projections[0].posted_allocated_cost = "100.00";
  assert.throws(
    () => projectBusinessResultSummary(extended),
    error => error.status === "BUSINESS_RESULT_SUMMARY_INVALID"
  );
});

function projectAllocationSummary() {
  return {
    result_type: "FINANCE.PROJECT_ALLOCATION",
    summary_schema_version: "ae_business_result_summary.v1",
    summary: {
      outcome: "ALLOCATED_AND_VERIFIED",
      journal_ref: "eos.posted_journal:journal-1",
      source_pool_ref: "eos.cost-source-pool:pool-1",
      source_pool_hash: `sha256:${"a".repeat(64)}`,
      allocation_batch_ref: "eos.cost-allocation-batch:batch-1",
      allocation_reconciliation_hash: `sha256:${"b".repeat(64)}`,
      pnl_refresh_hash: `sha256:${"c".repeat(64)}`,
      project_projections: [
        projectProjection("VO00D260001", "projection-1", "d"),
        projectProjection("VO00D260002", "projection-2", "e")
      ]
    }
  };
}

function projectProjection(projectCode, projectionId, hashCharacter) {
  return {
    project_code: projectCode,
    projection_id: projectionId,
    projection_version: 1,
    projection_hash: `sha256:${hashCharacter.repeat(64)}`,
    reconciliation_status: "VERIFIED",
    freshness_status: "CURRENT",
    data_classification: "CONFIDENTIAL_FINANCIAL"
  };
}
