import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  apiFailureCode,
  apiSemanticFailureStage,
  journeyProgressReporter,
  myBeeM1RuntimeConfig,
  myBeeM1RuntimeTimeouts,
  myBeeM1ApprovalJourneyChecks,
  myBeeM1ProductJourneyUiContract,
  parseProductPrompts,
  pendingApprovalGates,
  prepareApprovalInbox,
  runMyBeeM1ProductGoldenJourney,
  runMyBeeM1ProductPostRestartRecovery
} from "../scripts/runMyBeeW70CpM1ProductGoldenJourney.mjs";

test("M1 product journey distinguishes authority kind from WC approval domain", () => {
  const valid = myBeeM1ApprovalJourneyChecks([
    {
      approval_domains: ["BUSINESS_FORMAL", "BUSINESS_FORMAL", "NSL_WRITE"],
      approval_actor_roles: [
        "BUSINESS_APPROVER",
        "ACCOUNTING_APPROVER",
        "ACCOUNTING_APPROVER"
      ]
    }
  ]);
  assert.deepEqual(valid, {
    all_required_approval_domains_observed: true,
    business_approval_role_separated: true,
    accounting_approval_role_separated: true
  });

  const wrongActor = myBeeM1ApprovalJourneyChecks([
    {
      approval_domains: ["BUSINESS_FORMAL", "BUSINESS_FORMAL", "NSL_WRITE"],
      approval_actor_roles: ["BUSINESS_APPROVER", "BUSINESS_APPROVER", "ACCOUNTING_APPROVER"]
    }
  ]);
  assert.equal(wrongActor.all_required_approval_domains_observed, false);
  assert.equal(wrongActor.business_approval_role_separated, true);
  assert.equal(wrongActor.accounting_approval_role_separated, false);

  const falseDomain = myBeeM1ApprovalJourneyChecks([
    {
      approval_domains: ["BUSINESS_FORMAL", "ACCOUNTING_REVIEW", "NSL_WRITE"],
      approval_actor_roles: [
        "BUSINESS_APPROVER",
        "ACCOUNTING_APPROVER",
        "ACCOUNTING_APPROVER"
      ]
    }
  ]);
  assert.equal(falseDomain.all_required_approval_domains_observed, false);
  assert.equal(falseDomain.accounting_approval_role_separated, false);
});

test("M1 product journey writes only bounded atomic progress evidence", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "mybee-m1-progress-"));
  const target = path.join(directory, "progress.json");
  try {
    const reporter = journeyProgressReporter(target);
    reporter.record("transaction_1_approval_and_result", "RUNNING", {
      transaction_index: 1,
      poll_count: 12,
      approval_count: 1,
      pending_gate_count: 0,
      private_value: "must-not-be-persisted"
    });
    const evidence = JSON.parse(readFileSync(target, "utf8"));
    assert.equal(evidence.stage, "transaction_1_approval_and_result");
    assert.equal(evidence.state, "RUNNING");
    assert.equal(evidence.sequence, 1);
    assert.equal(evidence.poll_count, 12);
    assert.equal("private_value" in evidence, false);
    reporter.record("transaction_1_approval_and_result", "FAIL");
    const failed = JSON.parse(readFileSync(target, "utf8"));
    assert.equal(failed.state, "FAIL");
    assert.equal(failed.sequence, 2);
    assert.equal(failed.poll_count, 12);
    assert.equal(failed.approval_count, 1);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("M1 product journey preserves bounded API failure codes", () => {
  assert.equal(
    apiFailureCode({ payload: { error_code: "SEMANTIC_ADMISSION_BLOCKED" } }, "fallback"),
    "SEMANTIC_ADMISSION_BLOCKED"
  );
  assert.equal(apiFailureCode({ payload: { error_code: "unsafe value" } }, "fallback"), "fallback");
});

test("M1 product journey preserves only bounded semantic failure stages", () => {
  assert.equal(
    apiSemanticFailureStage({ payload: { details: { semantic_stage: "CONTEXT" } } }),
    "CONTEXT"
  );
  assert.equal(
    apiSemanticFailureStage({ payload: { details: { semantic_stage: "private-value" } } }),
    null
  );
});

test("M1 product journey binds to the authenticated React accessibility contract", () => {
  assert.deepEqual(myBeeM1ProductJourneyUiContract(), {
    loginHeading: "사번 로그인",
    employeeInputName: "employee_id",
    passwordInputName: "password",
    primaryNavigation: "주요 탐색",
    workspaceHeading: "작업 공간",
    promptLabel: "업무 요청",
    evidenceLabel: "근거 사용",
    submitButton: "보내기",
    approvalLink: "승인함",
    approvalHeading: "승인함",
    approveButton: "승인",
    confirmApprovalButton: "승인 확정",
    decisionRecordedHeading: "결정이 기록되었습니다",
    nextReviewButton: "다음 요청 검토",
    refreshButton: "새로고침",
    logoutButton: "로그아웃"
  });
});

test("M1 product journey advances a completed approval before selecting the next gate", async () => {
  const calls = [];
  const page = approvalInboxPage({ calls, nextReviewVisible: true });

  assert.equal(await prepareApprovalInbox(page, 60_000), "NEXT_REVIEW");
  assert.deepEqual(calls, ["navigation", "heading", "next-review"]);
});

test("M1 product journey refreshes the inbox when no completed approval is selected", async () => {
  const calls = [];
  const page = approvalInboxPage({ calls, nextReviewVisible: false });

  assert.equal(await prepareApprovalInbox(page, 60_000), "REFRESH");
  assert.deepEqual(calls, ["navigation", "heading", "refresh"]);
});

test("M1 product runtime config keeps authenticated fetch approval mode", () => {
  const config = myBeeM1RuntimeConfig();
  assert.equal(config.client_mode, "fetch");
  assert.equal(config.ae_base_url, "/ae-api");
  assert.equal(config.features.approval_inbox_enabled, true);
});

test("M1 product journey separates action, semantic submit, and result budgets", () => {
  assert.deepEqual(myBeeM1RuntimeTimeouts({}), {
    actionTimeout: 60_000,
    semanticSubmitTimeout: 180_000,
    resultTimeout: 900_000
  });
  assert.deepEqual(myBeeM1RuntimeTimeouts({
    NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS: "70000",
    NEX_MYBEE_M1_GOLDEN_SEMANTIC_SUBMIT_TIMEOUT_MS: "190000",
    NEX_MYBEE_M1_GOLDEN_RESULT_TIMEOUT_MS: "910000"
  }), {
    actionTimeout: 70_000,
    semanticSubmitTimeout: 190_000,
    resultTimeout: 910_000
  });
});

test("M1 product prompts require two non-identical bounded prompts", () => {
  const prompts = parseProductPrompts(JSON.stringify([
    "첫 번째 제품 전표 처리 요청은 충분히 긴 업무 문장입니다.",
    "두 번째 제품 전표 처리 요청도 서로 다른 충분히 긴 업무 문장입니다."
  ]));
  assert.equal(prompts.length, 2);
  assert.throws(() => parseProductPrompts("not-json"), /ProductPromptsInvalid/);
  assert.throws(
    () => parseProductPrompts(JSON.stringify([prompts[0], prompts[0]])),
    /ProductPromptsInvalid/
  );
  assert.throws(
    () => parseProductPrompts(JSON.stringify(["too short", prompts[1]])),
    /ProductPromptsInvalid/
  );
});

test("M1 product journey fails closed before importing Playwright", async () => {
  let imported = false;
  const result = await runMyBeeM1ProductGoldenJourney({
    environ: {},
    importPlaywright: async () => {
      imported = true;
      return {};
    }
  });

  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "required_env_missing");
  assert.equal(imported, false);
});

test("M1 product recovery fails closed before importing Playwright", async () => {
  let imported = false;
  const result = await runMyBeeM1ProductPostRestartRecovery({
    environ: {},
    importPlaywright: async () => {
      imported = true;
      return {};
    }
  });

  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "recovery_env_missing");
  assert.equal(imported, false);
});

test("M1 product journey reports a bounded launch failure without secrets", async () => {
  const evidence = await runMyBeeM1ProductGoldenJourney({
    environ: {
      NEX_MYBEE_M1_GOLDEN_WEB_URL: "https://ae.nex-staging.test:8443",
      NEX_MYBEE_M1_GOLDEN_TENANT_ID: "M1A7",
      NEX_MYBEE_M1_GOLDEN_REQUESTER_EMPLOYEE_ID: "8101",
      NEX_MYBEE_M1_GOLDEN_REQUESTER_PASSWORD: "requester-private-password",
      NEX_MYBEE_M1_GOLDEN_BUSINESS_APPROVER_EMPLOYEE_ID: "8201",
      NEX_MYBEE_M1_GOLDEN_BUSINESS_APPROVER_PASSWORD: "business-private-password",
      NEX_MYBEE_M1_GOLDEN_ACCOUNTING_APPROVER_EMPLOYEE_ID: "8301",
      NEX_MYBEE_M1_GOLDEN_ACCOUNTING_APPROVER_PASSWORD: "accounting-private-password",
      NEX_MYBEE_M1_GOLDEN_PROMPTS_JSON: JSON.stringify([
        "첫 번째 제품 전표 처리 요청은 충분히 긴 업무 문장입니다.",
        "두 번째 제품 전표 처리 요청도 서로 다른 충분히 긴 업무 문장입니다."
      ])
    },
    importPlaywright: async () => ({
      chromium: {
        launch: async () => {
          throw new Error("LaunchUnavailable");
        }
      }
    })
  });

  assert.equal(evidence.status, "FAIL");
  assert.equal(evidence.failure_code, "LaunchUnavailable");
  assert.equal(JSON.stringify(evidence).includes("private-password"), false);
});

test("M1 product journey falls back to a bounded Playwright error name", async () => {
  const evidence = await runMyBeeM1ProductGoldenJourney({
    environ: {
      NEX_MYBEE_M1_GOLDEN_WEB_URL: "https://ae.nex-staging.test:8443",
      NEX_MYBEE_M1_GOLDEN_TENANT_ID: "M1A7",
      NEX_MYBEE_M1_GOLDEN_REQUESTER_EMPLOYEE_ID: "8101",
      NEX_MYBEE_M1_GOLDEN_REQUESTER_PASSWORD: "requester-private-password",
      NEX_MYBEE_M1_GOLDEN_BUSINESS_APPROVER_EMPLOYEE_ID: "8201",
      NEX_MYBEE_M1_GOLDEN_BUSINESS_APPROVER_PASSWORD: "business-private-password",
      NEX_MYBEE_M1_GOLDEN_ACCOUNTING_APPROVER_EMPLOYEE_ID: "8301",
      NEX_MYBEE_M1_GOLDEN_ACCOUNTING_APPROVER_PASSWORD: "accounting-private-password",
      NEX_MYBEE_M1_GOLDEN_PROMPTS_JSON: JSON.stringify([
        "첫 번째 제품 전표 처리 요청은 충분히 긴 업무 문장입니다.",
        "두 번째 제품 전표 처리 요청도 서로 다른 충분히 긴 업무 문장입니다."
      ])
    },
    importPlaywright: async () => ({
      chromium: {
        launch: async () => {
          const error = new Error("Timeout 1000ms exceeded while opening a page");
          error.name = "TimeoutError";
          throw error;
        }
      }
    })
  });

  assert.equal(evidence.status, "FAIL");
  assert.equal(evidence.failure_code, "TimeoutError");
  assert.equal(evidence.observations.stage, "launch");
});

test("M1 product journey keeps business and accounting approval principals separated", async () => {
  const businessPage = approvalGatePage([
    { gate_id: "business-1", state: "PENDING", approval_domain: "BUSINESS_FORMAL" },
    { gate_id: "done-1", state: "APPROVED", approval_domain: "NSL_WRITE" }
  ]);
  const accountingPage = approvalGatePage([
    { gate_id: "accounting-1", state: "PENDING", approval_domain: "ACCOUNTING_REVIEW" }
  ]);

  const pending = await pendingApprovalGates(
    [
      { role: "BUSINESS_APPROVER", page: businessPage },
      { role: "ACCOUNTING_APPROVER", page: accountingPage }
    ],
    new Set(["business-1"])
  );

  assert.deepEqual(
    pending.map(item => [item.role, item.gate.gate_id]),
    [["ACCOUNTING_APPROVER", "accounting-1"]]
  );
});

test("M1 product journey fails closed when one approver inbox is unavailable", async () => {
  await assert.rejects(
    pendingApprovalGates([
      { role: "BUSINESS_APPROVER", page: approvalGatePage([], 503) },
      { role: "ACCOUNTING_APPROVER", page: approvalGatePage([]) }
    ]),
    /ApprovalGateListStatus503/
  );
});

function approvalInboxPage({ calls, nextReviewVisible }) {
  return {
    getByRole(role, options) {
      if (role === "link" && options.name === "승인함") {
        return { click: async () => calls.push("navigation") };
      }
      if (role === "heading" && options.name === "승인함") {
        return { waitFor: async () => calls.push("heading") };
      }
      if (role === "button" && options.name === "다음 요청 검토") {
        return {
          count: async () => Number(nextReviewVisible),
          isVisible: async () => nextReviewVisible,
          click: async () => calls.push("next-review")
        };
      }
      if (role === "button" && options.name === "새로고침") {
        return { click: async () => calls.push("refresh") };
      }
      throw new Error(`Unexpected role lookup: ${role}:${options.name}`);
    }
  };
}

function approvalGatePage(gates, status = 200) {
  return {
    evaluate: async () => ({ status, payload: { gates } })
  };
}
