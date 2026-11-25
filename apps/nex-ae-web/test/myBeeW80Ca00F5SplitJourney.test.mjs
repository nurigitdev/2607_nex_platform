import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluateExecutionProgressAcceptance,
  splitJourneyAdmissionAccepted,
  splitJourneyChecks,
  splitJourneyContract
} from "../scripts/runMyBeeW80Ca00F5SplitJourney.mjs";

test("progress acceptance requires overlap, append-only lines, and terminal projection", () => {
  const result = evaluateExecutionProgressAcceptance({
    snapshots: [
      { lines: ["[10:01:02] IA가 요청을 접수했습니다."], append_only: true },
      {
        lines: [
          "[10:01:02] IA가 요청을 접수했습니다.",
          "[10:01:03] IA가 요청 의도를 파악하고 있습니다."
        ],
        append_only: true
      }
    ],
    transport: {
      first_progress_request_at: 10,
      chat_response_at: 20,
      progress_request_count: 4,
      progress_http_statuses: [404, 200, 200, 200],
      poll_count_before_stability_check: 4,
      poll_count_after_stability_check: 4
    },
    projection: {
      terminal: true,
      events: [
        { event_id: "event-1", sequence: 1, event_code: "CHAT_REQUEST_ACCEPTED" },
        { event_id: "event-2", sequence: 2, event_code: "RESULT_PUBLISHED" }
      ],
      metadata: {
        owner_scoped: true,
        raw_prompt_included: false,
        private_payload_included: false
      }
    },
    progressCaptureCount: 2
  });

  assert.equal(result.status, "PASS");
  assert.equal(Object.values(result.checks).every(Boolean), true);
  assert.deepEqual(result.event_codes, ["CHAT_REQUEST_ACCEPTED", "RESULT_PUBLISHED"]);
});

test("progress acceptance fails closed on reordering and active polling", () => {
  const result = evaluateExecutionProgressAcceptance({
    snapshots: [
      { lines: ["진행 중"], append_only: false }
    ],
    transport: {
      first_progress_request_at: 30,
      chat_response_at: 20,
      progress_request_count: 3,
      progress_http_statuses: [200],
      poll_count_before_stability_check: 2,
      poll_count_after_stability_check: 3
    },
    projection: {
      terminal: false,
      events: [
        { event_id: "duplicate", sequence: 2, event_code: "RESULT_PUBLISHED" },
        { event_id: "duplicate", sequence: 1, event_code: "CHAT_REQUEST_ACCEPTED" }
      ],
      metadata: {
        owner_scoped: false,
        raw_prompt_included: true,
        private_payload_included: true
      }
    },
    progressCaptureCount: 0
  });

  assert.equal(result.status, "FAIL");
  assert.equal(result.checks.progress_polling_stopped_after_terminal, false);
  assert.equal(result.checks.progress_projection_ordered_and_unique, false);
});

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

test("allocation contract has no human or NSL approval wait", () => {
  assert.deepEqual(splitJourneyContract("allocation").approvalSequence, []);
  assert.deepEqual(splitJourneyChecks({
    mode: "allocation",
    approvalDomains: [],
    approvalActorRoles: []
  }), {
    exact_sequential_approval_observed: true,
    journal_business_before_accounting: true,
    allocation_independent_from_business_approval: true
  });
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
