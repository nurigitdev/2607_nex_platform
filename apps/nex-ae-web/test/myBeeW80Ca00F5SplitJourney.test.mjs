import assert from "node:assert/strict";
import test from "node:test";

import {
  splitJourneyAdmissionAccepted,
  splitJourneyChecks,
  splitJourneyContract
} from "../scripts/runMyBeeW80Ca00F5SplitJourney.mjs";

test("journal contract enforces business then accounting approval", () => {
  assert.deepEqual(splitJourneyContract("journal").approvalSequence, [
    { domain: "BUSINESS_FORMAL", role: "BUSINESS_APPROVER" },
    { domain: "BUSINESS_FORMAL", role: "ACCOUNTING_APPROVER" },
    { domain: "NSL_WRITE", role: "ACCOUNTING_APPROVER" }
  ]);
  assert.deepEqual(
    splitJourneyChecks({
      mode: "journal",
      approvalDomains: ["BUSINESS_FORMAL", "BUSINESS_FORMAL", "NSL_WRITE"],
      approvalActorRoles: ["BUSINESS_APPROVER", "ACCOUNTING_APPROVER", "ACCOUNTING_APPROVER"]
    }),
    {
      exact_sequential_approval_observed: true,
      journal_business_before_accounting: true,
      allocation_independent_from_business_approval: true
    }
  );
});

test("allocation contract rejects a business approval stage", () => {
  assert.deepEqual(splitJourneyContract("allocation").approvalSequence, [
    { domain: "NSL_WRITE", role: "ACCOUNTING_APPROVER" }
  ]);
  const checks = splitJourneyChecks({
    mode: "allocation",
    approvalDomains: ["BUSINESS_FORMAL", "NSL_WRITE"],
    approvalActorRoles: ["BUSINESS_APPROVER", "ACCOUNTING_APPROVER"]
  });
  assert.equal(checks.exact_sequential_approval_observed, false);
  assert.equal(checks.allocation_independent_from_business_approval, false);
});

test("unknown split journey mode fails closed", () => {
  assert.throws(() => splitJourneyContract("combined"), /SplitJourneyModeInvalid/);
});

test("journal admission requires a compiled three-stage semantic plan", () => {
  assert.equal(splitJourneyAdmissionAccepted({
    mode: "journal",
    httpStatus: 202,
    semanticPlanning: {
      status: "COMPILED",
      stages: [{}, {}, {}]
    }
  }), true);
  assert.equal(splitJourneyAdmissionAccepted({
    mode: "journal",
    httpStatus: 202,
    semanticPlanning: {
      status: "PRODUCT_COORDINATION_STARTED",
      stages: [{}, {}]
    }
  }), false);
});

test("allocation admission requires deterministic product coordination", () => {
  const semanticPlanning = {
    status: "PRODUCT_COORDINATION_STARTED",
    directive: "WAIT_FOR_PRODUCT_COORDINATION",
    product_planning_admission: { status: "PREPARATION_STARTED" },
    stages: [
      { semantic_stage: "INTENT" },
      { semantic_stage: "CONTEXT" }
    ]
  };
  assert.equal(splitJourneyAdmissionAccepted({
    mode: "allocation",
    httpStatus: 202,
    semanticPlanning
  }), true);
  assert.equal(splitJourneyAdmissionAccepted({
    mode: "allocation",
    httpStatus: 200,
    semanticPlanning
  }), false);
  assert.equal(splitJourneyAdmissionAccepted({
    mode: "allocation",
    httpStatus: 202,
    semanticPlanning: { ...semanticPlanning, product_planning_admission: null }
  }), false);
});
