import assert from "node:assert/strict";
import test from "node:test";

import {
  apiFailureCode,
  myBeeM1RuntimeConfig,
  myBeeM1ProductJourneyUiContract,
  parseProductPrompts,
  runMyBeeM1ProductGoldenJourney,
  runMyBeeM1ProductPostRestartRecovery
} from "../scripts/runMyBeeW70CpM1ProductGoldenJourney.mjs";

test("M1 product journey preserves bounded API failure codes", () => {
  assert.equal(
    apiFailureCode({ payload: { error_code: "SEMANTIC_ADMISSION_BLOCKED" } }, "fallback"),
    "SEMANTIC_ADMISSION_BLOCKED"
  );
  assert.equal(apiFailureCode({ payload: { error_code: "unsafe value" } }, "fallback"), "fallback");
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
    logoutButton: "로그아웃"
  });
});

test("M1 product runtime config keeps authenticated fetch approval mode", () => {
  const config = myBeeM1RuntimeConfig();
  assert.equal(config.client_mode, "fetch");
  assert.equal(config.ae_base_url, "/ae-api");
  assert.equal(config.features.approval_inbox_enabled, true);
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
      NEX_MYBEE_M1_GOLDEN_APPROVER_EMPLOYEE_ID: "8201",
      NEX_MYBEE_M1_GOLDEN_APPROVER_PASSWORD: "approver-private-password",
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
      NEX_MYBEE_M1_GOLDEN_APPROVER_EMPLOYEE_ID: "8201",
      NEX_MYBEE_M1_GOLDEN_APPROVER_PASSWORD: "approver-private-password",
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
