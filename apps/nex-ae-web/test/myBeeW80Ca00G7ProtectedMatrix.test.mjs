import assert from "node:assert/strict";
import test from "node:test";

import {
  isTransientBrowserFetch,
  parseProtectedScenarios,
  protectedMatrixChecks,
  runProtectedMatrix
} from "../scripts/runMyBeeW80Ca00G7ProtectedMatrix.mjs";

test("only transient browser fetch failures are retryable", () => {
  assert.equal(isTransientBrowserFetch(new TypeError("Failed to fetch")), true);
  assert.equal(isTransientBrowserFetch(new Error("VoucherListUnavailable")), false);
});

const scenarios = [
  ["one-stage-success", 1, "ENVELOPE_ONLY"],
  ["two-stage-success", 2, "ENVELOPE_ONLY"],
  ["three-stage-success", 3, "JOURNAL_SUCCESS"],
  ["middle-stage-rejection", 3, "MIDDLE_REJECTION"],
  ["final-stage-rejection", 3, "FINAL_REJECTION"],
  ["accounting-correction", 3, "ACCOUNTING_CORRECTION"]
].map(([scenario_id, expected_business_stages, outcome]) => ({
  scenario_id,
  expected_business_stages,
  outcome,
  prompt: `충분히 긴 보호 acceptance prompt ${scenario_id}`
}));

test("scenario contract admits exactly the six protected journeys", () => {
  const parsed = parseProtectedScenarios(JSON.stringify(scenarios));
  assert.equal(parsed.length, 6);
  assert.deepEqual(parsed.map(item => item.expectedStages), [1, 2, 3, 3, 3, 3]);
  assert.throws(
    () => parseProtectedScenarios(JSON.stringify(scenarios.slice(0, 5))),
    /ScenarioCountInvalid/
  );
  assert.throws(
    () => parseProtectedScenarios(JSON.stringify([...scenarios.slice(0, 5), scenarios[0]])),
    /ScenarioInvalid6/
  );
});

test("matrix checks require tier routes, terminal rejections, correction, replay, and screens", () => {
  const results = scenarios.map((scenario, index) => ({
    scenario_id: scenario.scenario_id,
    outcome: scenario.outcome,
    business_stage_count: scenario.expected_business_stages,
    approved_envelope_present: !scenario.outcome.endsWith("REJECTION"),
    voucher_created: !scenario.outcome.endsWith("REJECTION"),
    rejected_stage: scenario.outcome === "MIDDLE_REJECTION" ? 2
      : scenario.outcome === "FINAL_REJECTION" ? 3 : null,
    terminal_status: scenario.outcome === "JOURNAL_SUCCESS" ||
      scenario.outcome === "ACCOUNTING_CORRECTION" ? "SUCCEEDED" : "WAITING",
    correction_cycle: scenario.outcome === "ACCOUNTING_CORRECTION" ? 1 : 0,
    decision_replay_statuses: [200, 200],
    screen_capture_count: index + 1,
    accounting_documents: ["JOURNAL_SUCCESS", "ACCOUNTING_CORRECTION"].includes(scenario.outcome)
      ? [
        {
          approval_domain: "BUSINESS_FORMAL",
          project_code: "T001D260001",
          line_count: 2,
          balanced: true,
          document_identity: "T001D260001:Candidate rev. 3"
        },
        {
          approval_domain: "NSL_WRITE",
          project_code: "T001D260001",
          line_count: 2,
          balanced: true,
          document_identity: "T001D260001:Candidate rev. 3"
        }
      ]
      : []
  }));
  const checks = protectedMatrixChecks(results);
  assert.equal(Object.values(checks).every(Boolean), true);
  assert.equal(
    protectedMatrixChecks(results.map((item, index) =>
      index === 5 ? { ...item, correction_cycle: 0 } : item
    )).correction_used_latest_revision,
    false
  );
  const drifted = results.map((item, index) => index === 2
    ? {
      ...item,
      accounting_documents: item.accounting_documents.map((document, documentIndex) =>
        documentIndex === 1 ? { ...document, document_identity: "drift" } : document
      )
    }
    : item);
  assert.equal(
    protectedMatrixChecks(drifted).voucher_shaped_accounting_projection_visible,
    false
  );
});

test("runner fails closed before browser launch when required configuration is absent", async () => {
  const result = await runProtectedMatrix({ environ: {} });
  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "ProtectedMatrixRequiredEnvMissing");
  assert.equal(result.observations.missing_count > 0, true);
});
