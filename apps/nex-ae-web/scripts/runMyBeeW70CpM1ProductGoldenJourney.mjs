#!/usr/bin/env node
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV } from "./runCredentialLoginPlaywrightReadiness.mjs";

export const MYBEE_M1_PRODUCT_GOLDEN_SCHEMA_VERSION =
  "mybee_w70_cp_m1_product_golden_journey_playwright.v1";

const ENV = {
  webUrl: "NEX_MYBEE_M1_GOLDEN_WEB_URL",
  tenantId: "NEX_MYBEE_M1_GOLDEN_TENANT_ID",
  requesterEmployeeId: "NEX_MYBEE_M1_GOLDEN_REQUESTER_EMPLOYEE_ID",
  requesterPassword: "NEX_MYBEE_M1_GOLDEN_REQUESTER_PASSWORD",
  businessApproverEmployeeId: "NEX_MYBEE_M1_GOLDEN_BUSINESS_APPROVER_EMPLOYEE_ID",
  businessApproverPassword: "NEX_MYBEE_M1_GOLDEN_BUSINESS_APPROVER_PASSWORD",
  accountingApproverEmployeeId: "NEX_MYBEE_M1_GOLDEN_ACCOUNTING_APPROVER_EMPLOYEE_ID",
  accountingApproverPassword: "NEX_MYBEE_M1_GOLDEN_ACCOUNTING_APPROVER_PASSWORD",
  promptsJson: "NEX_MYBEE_M1_GOLDEN_PROMPTS_JSON",
  recoveryInteractionId: "NEX_MYBEE_M1_GOLDEN_RECOVERY_INTERACTION_ID",
  screenshotDir: "NEX_MYBEE_M1_GOLDEN_SCREENSHOT_DIR",
  progressPath: "NEX_MYBEE_M1_GOLDEN_PROGRESS_PATH",
  timeoutMs: "NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS",
  semanticSubmitTimeoutMs: "NEX_MYBEE_M1_GOLDEN_SEMANTIC_SUBMIT_TIMEOUT_MS",
  resultTimeoutMs: "NEX_MYBEE_M1_GOLDEN_RESULT_TIMEOUT_MS"
};
const REQUIRED = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.requesterEmployeeId,
  ENV.requesterPassword,
  ENV.businessApproverEmployeeId,
  ENV.businessApproverPassword,
  ENV.accountingApproverEmployeeId,
  ENV.accountingApproverPassword,
  ENV.promptsJson
];
const RECOVERY_REQUIRED = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.requesterEmployeeId,
  ENV.requesterPassword,
  ENV.recoveryInteractionId
];
const SENSITIVE = [
  ENV.requesterPassword,
  ENV.businessApproverPassword,
  ENV.accountingApproverPassword,
  ENV.promptsJson
];
const DEFAULT_TIMEOUT_MS = 60_000;
const DEFAULT_SEMANTIC_SUBMIT_TIMEOUT_MS = 180_000;
const DEFAULT_RESULT_TIMEOUT_MS = 900_000;

const UI = Object.freeze({
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

export function myBeeM1ProductJourneyUiContract() {
  return UI;
}

export function myBeeM1RuntimeConfig() {
  return {
    runtime_config_schema_version: "ae_web_runtime_config.v1",
    client_mode: "fetch",
    ae_base_url: "/ae-api",
    features: {
      approval_inbox_enabled: true,
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    }
  };
}

export function myBeeM1RuntimeTimeouts(environ = {}) {
  return {
    actionTimeout: positiveTimeout(environ[ENV.timeoutMs], DEFAULT_TIMEOUT_MS),
    semanticSubmitTimeout: positiveTimeout(
      environ[ENV.semanticSubmitTimeoutMs],
      DEFAULT_SEMANTIC_SUBMIT_TIMEOUT_MS
    ),
    resultTimeout: positiveTimeout(
      environ[ENV.resultTimeoutMs],
      DEFAULT_RESULT_TIMEOUT_MS
    )
  };
}

export function parseProductPrompts(raw) {
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error("ProductPromptsInvalid");
  }
  if (
    !Array.isArray(value) ||
    value.length < 2 ||
    value.some(item => typeof item !== "string" || item.trim().length < 20) ||
    new Set(value).size !== value.length
  ) {
    throw new Error("ProductPromptsInvalid");
  }
  return value;
}

export function journeyProgressReporter(progressPath) {
  let sequence = 0;
  let latestDetails = {};
  return {
    record(stage, state = "RUNNING", details = {}) {
      if (!progressPath) return;
      sequence += 1;
      latestDetails = { ...latestDetails, ...details };
      const safeStage = /^[a-z][a-z0-9_]{0,95}$/.test(stage) ? stage : "invalid";
      const safeState = ["RUNNING", "PASS", "FAIL"].includes(state) ? state : "FAIL";
      const payload = {
        schema_version: "mybee_m1_product_journey_progress.v1",
        state: safeState,
        stage: safeStage,
        sequence,
        recorded_at: new Date().toISOString()
      };
      for (const key of [
        "transaction_index",
        "poll_count",
        "approval_count",
        "pending_gate_count"
      ]) {
        const value = latestDetails[key];
        if (Number.isSafeInteger(value) && value >= 0 && value <= 1_000_000) {
          payload[key] = value;
        }
      }
      try {
        mkdirSync(path.dirname(progressPath), { recursive: true });
        const temporary = `${progressPath}.tmp-${process.pid}`;
        writeFileSync(temporary, `${JSON.stringify(payload)}\n`, { encoding: "utf8", mode: 0o600 });
        renameSync(temporary, progressPath);
      } catch {
        // Progress evidence must never replace the authoritative journey failure.
      }
    }
  };
}

export async function runMyBeeM1ProductGoldenJourney({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missing = REQUIRED.filter(name => !environ[name]);
  if (missing.length > 0) return failure("required_env_missing", { missing_count: missing.length });
  let prompts;
  try {
    prompts = parseProductPrompts(environ[ENV.promptsJson]);
  } catch (error) {
    return failure(safeFailureCode(error));
  }
  const { actionTimeout, semanticSubmitTimeout, resultTimeout } =
    myBeeM1RuntimeTimeouts(environ);
  const captures = screenCapture(environ[ENV.screenshotDir], "journey");
  const progress = journeyProgressReporter(environ[ENV.progressPath]);
  let browser;
  let requesterContext;
  let businessApproverContext;
  let accountingApproverContext;
  let requesterPage;
  let businessApproverPage;
  let accountingApproverPage;
  let stage = "launch";
  let semanticFailureStage = null;
  const responses = [];
  const transactions = [];
  const markStage = (nextStage, details = {}) => {
    stage = nextStage;
    progress.record(stage, "RUNNING", details);
  };
  try {
    markStage("launch");
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    requesterContext = await browser.newContext(contextOptions());
    businessApproverContext = await browser.newContext(contextOptions());
    accountingApproverContext = await browser.newContext(contextOptions());
    const requester = requesterPage = await configuredPage(requesterContext);
    const businessApprover = businessApproverPage = await configuredPage(
      businessApproverContext
    );
    const accountingApprover = accountingApproverPage = await configuredPage(
      accountingApproverContext
    );
    observeResponses(requester, responses);
    observeResponses(businessApprover, responses);
    observeResponses(accountingApprover, responses);

    markStage("anonymous_boundary");
    await requester.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout: actionTimeout });
    await requester.getByRole("heading", { name: UI.loginHeading }).waitFor({ timeout: actionTimeout });
    const anonymousProtectedSurfaceHidden =
      (await requester.getByRole("navigation", { name: UI.primaryNavigation }).count()) === 0 &&
      (await requester.getByRole("heading", { name: UI.approvalHeading }).count()) === 0;
    await captures.capture(requester, "login");

    markStage("requester_login");
    await login(requester, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.requesterEmployeeId],
      password: environ[ENV.requesterPassword],
      timeout: actionTimeout
    });
    await captures.capture(requester, "requester-workspace");

    markStage("business_approver_login");
    await businessApprover.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout: actionTimeout
    });
    await login(businessApprover, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.businessApproverEmployeeId],
      password: environ[ENV.businessApproverPassword],
      timeout: actionTimeout
    });
    await captures.capture(businessApprover, "business-approver-workspace");

    markStage("accounting_approver_login");
    await accountingApprover.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout: actionTimeout
    });
    await login(accountingApprover, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.accountingApproverEmployeeId],
      password: environ[ENV.accountingApproverPassword],
      timeout: actionTimeout
    });
    await captures.capture(accountingApprover, "accounting-approver-workspace");

    let workspace = null;
    for (let index = 0; index < prompts.length; index += 1) {
      markStage(`transaction_${index + 1}_submit`, { transaction_index: index + 1 });
      const admitted = await submitPrompt(requester, prompts[index], semanticSubmitTimeout, {
        observeWorkspace: index === 0
      });
      if (index === 0) {
        workspace = admitted.workspace;
        if (!workspace?.workspace_id || !workspace?.chat_document_id) {
          throw new Error("ProductWorkspaceObservationMissing");
        }
      }
      await captures.capture(requester, `transaction-${index + 1}-submitted`);
      if (
        admitted.status !== 202 ||
        admitted.payload?.generation?.semantic_planning?.status !== "COMPILED" ||
        !admitted.payload?.interaction_id
      ) {
        semanticFailureStage = apiSemanticFailureStage(admitted);
        throw new Error(apiFailureCode(admitted, `ProductAdmissionStatus${admitted.status}`));
      }
      const interactionId = admitted.payload.interaction_id;
      markStage(`transaction_${index + 1}_approval_and_result`, {
        transaction_index: index + 1,
        approval_count: 0,
        pending_gate_count: 0,
        poll_count: 0
      });
      const completed = await driveApprovalsUntilResult({
        requester,
        approvers: [
          { role: "BUSINESS_APPROVER", page: businessApprover },
          { role: "ACCOUNTING_APPROVER", page: accountingApprover }
        ],
        interactionId,
        actionTimeout,
        resultTimeout,
        captures,
        transactionIndex: index + 1,
        onProgress: details => progress.record(stage, "RUNNING", {
          transaction_index: index + 1,
          ...details
        })
      });
      if (completed.result?.status !== "SUCCEEDED") {
        throw new Error("ProductAgentResultNotSucceeded");
      }
      transactions.push({
        interaction_id: interactionId,
        semantic_stages: admitted.payload.generation.semantic_planning.stages || [],
        approval_domains: completed.approvalDomains,
        approval_actor_roles: completed.approvalActorRoles,
        approval_replay_statuses: completed.replayStatuses,
        result_projection: completed
      });
      await captures.capture(requester, `transaction-${index + 1}-result`);
    }

    markStage("logout", { transaction_index: transactions.length });
    await logout(accountingApprover, actionTimeout);
    await logout(businessApprover, actionTimeout);
    await logout(requester, actionTimeout);
    await captures.capture(requester, "requester-logged-out");
    const requiredDomains = new Set(["BUSINESS_FORMAL", "ACCOUNTING_REVIEW", "NSL_WRITE"]);
    const observedDomains = new Set(transactions.flatMap(item => item.approval_domains));
    const checks = {
      chromium_launched: true,
      anonymous_protected_surface_hidden: anonymousProtectedSurfaceHidden,
      requester_authenticated: true,
      business_approver_authenticated: true,
      accounting_approver_authenticated: true,
      two_non_identical_business_requests: transactions.length >= 2,
      all_live_plans_compiled: transactions.every(item =>
        item.semantic_stages.length === 3 &&
        item.semantic_stages.every(stageItem => stageItem.directive === "CONTINUE")
      ),
      all_required_approval_domains_observed: [...requiredDomains].every(domain =>
        observedDomains.has(domain)
      ),
      approval_replay_idempotent: transactions.every(item =>
        item.approval_replay_statuses.every(status => status === 200)
      ),
      business_approval_role_separated: transactions.every(item =>
        item.approval_domains.every((domain, index) =>
          domain !== "BUSINESS_FORMAL" ||
          item.approval_actor_roles[index] === "BUSINESS_APPROVER"
        )
      ),
      accounting_approval_role_separated: transactions.every(item =>
        item.approval_domains.every((domain, index) =>
          domain !== "ACCOUNTING_REVIEW" ||
          item.approval_actor_roles[index] === "ACCOUNTING_APPROVER"
        )
      ),
      all_results_terminal: transactions.every(item =>
        item.result_projection.terminal === true
      ),
      all_results_succeeded: transactions.every(item =>
        item.result_projection.result?.status === "SUCCEEDED"
      ),
      all_deliveries_acknowledged: transactions.every(item =>
        item.result_projection.result?.delivery?.state === "ACKNOWLEDGED"
      ),
      requester_logout_returned_to_login:
        await requester.getByRole("heading", { name: UI.loginHeading }).isVisible(),
      business_approver_logout_returned_to_login:
        await businessApprover.getByRole("heading", { name: UI.loginHeading }).isVisible(),
      accounting_approver_logout_returned_to_login:
        await accountingApprover.getByRole("heading", { name: UI.loginHeading }).isVisible()
    };
    const evidence = {
      smoke_schema_version: MYBEE_M1_PRODUCT_GOLDEN_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        client_mode: "fetch",
        session_count: 3
      },
      observations: {
        transaction_count: transactions.length,
        approval_domains: [...observedDomains].sort(),
        authenticated_http_response_count: responses.length
      },
      screen_capture: captures.evidence(),
      checks,
      runtime: {
        workspace_id: workspace?.workspace_id,
        chat_document_id: workspace?.chat_document_id,
        transactions
      }
    };
    progress.record("completed", "PASS", {
      transaction_index: transactions.length
    });
    assertRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    progress.record(stage, "FAIL");
    const failedPage = stage.startsWith("business_approver")
      ? businessApproverPage
      : stage.startsWith("accounting_approver")
        ? accountingApproverPage
        : requesterPage;
    if (failedPage) {
      try {
        await captures.capture(failedPage, `${stage}-failure`);
      } catch {
        // The original bounded failure remains authoritative if capture also fails.
      }
    }
    const observations = {
      stage,
      response_count: responses.length,
      recent_api_responses: responses.slice(-8)
    };
    if (semanticFailureStage) observations.semantic_stage = semanticFailureStage;
    const evidence = failure(safeFailureCode(error), observations);
    evidence.screen_capture = captures.evidence();
    assertRedacted(evidence, environ);
    return evidence;
  } finally {
    if (accountingApproverContext) await accountingApproverContext.close();
    if (businessApproverContext) await businessApproverContext.close();
    if (requesterContext) await requesterContext.close();
    if (browser) await browser.close();
  }
}

export async function runMyBeeM1ProductPostRestartRecovery({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missing = RECOVERY_REQUIRED.filter(name => !environ[name]);
  if (missing.length > 0) return failure("recovery_env_missing", { missing_count: missing.length });
  const actionTimeout = positiveTimeout(environ[ENV.timeoutMs]);
  const resultTimeout = positiveTimeout(
    environ[ENV.resultTimeoutMs],
    DEFAULT_RESULT_TIMEOUT_MS
  );
  const captures = screenCapture(environ[ENV.screenshotDir], "recovery");
  let browser;
  let context;
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    context = await browser.newContext(contextOptions());
    const page = await configuredPage(context);
    await page.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout: actionTimeout
    });
    await login(page, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.requesterEmployeeId],
      password: environ[ENV.requesterPassword],
      timeout: actionTimeout
    });
    const projection = await waitForResult(
      page,
      environ[ENV.recoveryInteractionId],
      resultTimeout
    );
    await captures.capture(page, "recovered-result");
    const checks = {
      authenticated_after_restart: true,
      authoritative_result_recovered: projection.terminal === true,
      recovered_result_succeeded: projection.result?.status === "SUCCEEDED",
      recovered_delivery_acknowledged:
        projection.result?.delivery?.state === "ACKNOWLEDGED"
    };
    const evidence = {
      smoke_schema_version: MYBEE_M1_PRODUCT_GOLDEN_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      recovery_mode: true,
      screen_capture: captures.evidence(),
      checks,
      runtime: {
        interaction_id: environ[ENV.recoveryInteractionId],
        result_projection: projection
      }
    };
    assertRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = failure(safeFailureCode(error), { recovery_mode: true });
    evidence.screen_capture = captures.evidence();
    assertRedacted(evidence, environ);
    return evidence;
  } finally {
    if (context) await context.close();
    if (browser) await browser.close();
  }
}

async function driveApprovalsUntilResult({
  requester,
  approvers,
  interactionId,
  actionTimeout,
  resultTimeout,
  captures,
  transactionIndex,
  onProgress = () => {}
}) {
  const deadline = Date.now() + resultTimeout;
  const approvalDomains = [];
  const approvalActorRoles = [];
  const replayStatuses = [];
  const decidedGateIds = new Set();
  let pollCount = 0;
  let lastProgressAt = 0;
  while (Date.now() < deadline) {
    pollCount += 1;
    const current = await readResult(requester, interactionId);
    if (current?.terminal === true) {
      onProgress({
        poll_count: pollCount,
        approval_count: approvalDomains.length,
        pending_gate_count: 0
      });
      return { ...current, approvalDomains, approvalActorRoles, replayStatuses };
    }
    const pending = await pendingApprovalGates(approvers, decidedGateIds);
    if (pending.length > 1) throw new Error("ApprovalGateAmbiguous");
    if (pending.length === 1) {
      const { gate, role, page } = pending[0];
      onProgress({
        poll_count: pollCount,
        approval_count: approvalDomains.length,
        pending_gate_count: 1
      });
      const decision = await decideGateInUi(
        page,
        gate,
        actionTimeout,
        `M1 product acceptance ${transactionIndex}`
      );
      decidedGateIds.add(gate.gate_id);
      approvalDomains.push(gate.approval_domain);
      approvalActorRoles.push(role);
      replayStatuses.push(decision.replayStatus);
      await captures.capture(
        page,
        `transaction-${transactionIndex}-approval-${approvalDomains.length}-${gate.approval_domain}`
      );
      onProgress({
        poll_count: pollCount,
        approval_count: approvalDomains.length,
        pending_gate_count: 0
      });
      continue;
    }
    if (Date.now() - lastProgressAt >= 5_000) {
      onProgress({
        poll_count: pollCount,
        approval_count: approvalDomains.length,
        pending_gate_count: 0
      });
      lastProgressAt = Date.now();
    }
    await requester.waitForTimeout(500);
  }
  throw new Error("ProductResultTimeout");
}

export async function pendingApprovalGates(approvers, decidedGateIds = new Set()) {
  const responses = await Promise.all(
    approvers.map(async ({ role, page }) => ({
      role,
      page,
      response: await browserJson(page, "/ae-api/api/v1/approval-gates?limit=100")
    }))
  );
  return responses.flatMap(({ role, page, response }) => {
    if (response.status !== 200) {
      throw new Error(
        apiFailureCode(response, `ApprovalGateListStatus${response.status}`)
      );
    }
    return (response.payload?.gates || [])
      .filter(item => item.state === "PENDING" && !decidedGateIds.has(item.gate_id))
      .map(gate => ({ role, page, gate }));
  });
}

async function decideGateInUi(page, gate, timeout, comment) {
  let decisionRequest = null;
  const observe = request => {
    const route = new URL(request.url()).pathname;
    if (request.method() === "POST" && route.endsWith("/decisions")) {
      decisionRequest = { route, payload: request.postDataJSON() };
    }
  };
  page.on("request", observe);
  try {
    void comment;
    await prepareApprovalInbox(page, timeout);
    const pendingList = page.getByLabel("대기 중인 승인 요청");
    const gateButton = pendingList.getByRole("button").filter({ hasText: gate.title });
    await gateButton.waitFor({ timeout });
    await gateButton.click();
    await page.getByRole("heading", { name: gate.title, exact: true }).waitFor({ timeout });
    await page.getByRole("button", { name: UI.approveButton, exact: true }).click();
    await page.getByRole("button", { name: UI.confirmApprovalButton, exact: true }).click();
    await page.getByRole("heading", { name: UI.decisionRecordedHeading }).waitFor({ timeout });
    if (!decisionRequest) throw new Error("ApprovalDecisionRequestMissing");
    const replay = await browserJson(page, decisionRequest.route, {
      method: "POST",
      body: decisionRequest.payload
    });
    return { replayStatus: replay.status };
  } finally {
    page.off("request", observe);
  }
}

export async function prepareApprovalInbox(page, timeout) {
  await page.getByRole("link", { name: UI.approvalLink, exact: true }).click();
  await page.getByRole("heading", { name: UI.approvalHeading, exact: true }).waitFor({ timeout });
  const nextReview = page.getByRole("button", { name: UI.nextReviewButton, exact: true });
  if ((await nextReview.count()) > 0 && (await nextReview.isVisible())) {
    await nextReview.click();
    return "NEXT_REVIEW";
  }
  await page.getByRole("button", { name: UI.refreshButton, exact: true }).click();
  return "REFRESH";
}

async function submitPrompt(page, prompt, timeout, { observeWorkspace = false } = {}) {
  const workspaceResponsePromise = observeWorkspace
    ? page.waitForResponse(response => {
        const route = new URL(response.url()).pathname;
        return response.request().method() === "POST" && route === "/ae-api/api/v1/workspaces";
      }, { timeout })
    : null;
  const evidenceToggle = page.getByLabel(UI.evidenceLabel, { exact: true });
  if (await evidenceToggle.isChecked()) await evidenceToggle.uncheck();
  await page.getByLabel(UI.promptLabel, { exact: true }).fill(prompt);
  const responsePromise = page.waitForResponse(response => {
    const route = new URL(response.url()).pathname;
    return response.request().method() === "POST" && route === "/ae-api/api/v1/chat/interactions";
  }, { timeout });
  await page.getByRole("button", { name: UI.submitButton, exact: true }).click();
  const response = await responsePromise;
  let workspace = null;
  if (workspaceResponsePromise) {
    const workspaceResponse = await workspaceResponsePromise;
    if (workspaceResponse.status() !== 200) {
      throw new Error(`WorkspaceCreateStatus${workspaceResponse.status()}`);
    }
    workspace = await workspaceResponse.json();
  }
  return { status: response.status(), payload: await response.json(), workspace };
}

async function readResult(page, interactionId) {
  const route = `/ae-api/api/v1/chat/interactions/${encodeURIComponent(interactionId)}/agent-result`;
  const response = await browserJson(page, route);
  if (response.status === 200) return response.payload;
  if (response.status === 404) return null;
  throw new Error(`AgentResultStatus${response.status}`);
}

async function waitForResult(page, interactionId, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await readResult(page, interactionId);
    if (result?.terminal === true) return result;
    await page.waitForTimeout(750);
  }
  throw new Error("AgentResultTimeout");
}

async function login(page, { tenantId, employeeId, password, timeout }) {
  void tenantId;
  await page.locator(`input[name="${UI.employeeInputName}"]`).fill(employeeId);
  await page.locator(`input[name="${UI.passwordInputName}"]`).fill(password);
  const responsePromise = page.waitForResponse(response =>
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/ae-api/api/v1/auth/session/login",
  { timeout });
  await page.locator('form button[type="submit"]').click();
  const response = await responsePromise;
  if (response.status() !== 200) {
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    const errorCode = String(payload?.error_code || "");
    throw new Error(
      /^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(errorCode)
        ? errorCode.replaceAll(/[^A-Za-z0-9]/g, "")
        : `CredentialLoginStatus${response.status()}`
    );
  }
  await page.getByRole("navigation", { name: UI.primaryNavigation }).waitFor({ timeout });
  await page.getByRole("heading", { name: UI.workspaceHeading, exact: true }).waitFor({ timeout });
}

async function logout(page, timeout) {
  const responsePromise = page.waitForResponse(response =>
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/ae-api/api/v1/auth/session/logout",
  { timeout });
  await page.getByRole("button", { name: UI.logoutButton, exact: true }).click({ timeout });
  const response = await responsePromise;
  if (response.status() !== 200) throw new Error(`CredentialLogoutStatus${response.status()}`);
  await page.getByRole("heading", { name: UI.loginHeading }).waitFor({ timeout });
}

async function launchBrowser(playwright, environ) {
  return playwright.chromium.launch({
    headless: true,
    args: ["--host-resolver-rules=MAP ae.nex-staging.test 127.0.0.1"],
    ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
      ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
      : {})
  });
}

function contextOptions() {
  return { ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } };
}

async function configuredPage(context) {
  const page = await context.newPage();
  await page.addInitScript(config => {
    globalThis.__NEX_AE_WEB_CONFIG__ = config;
  }, myBeeM1RuntimeConfig());
  return page;
}

function observeResponses(page, responses) {
  page.on("response", response => {
    const route = new URL(response.url()).pathname;
    if (route.startsWith("/ae-api/api/v1/")) {
      responses.push({ route: routeClass(route), status: response.status() });
    }
  });
}

function screenCapture(directory, prefix) {
  const captures = [];
  let index = 0;
  return {
    async capture(page, stage) {
      if (!directory) return;
      await mkdir(directory, { recursive: true });
      index += 1;
      const file = `mybee-m1-${prefix}-${String(index).padStart(2, "0")}-${stage}.png`;
      await page.screenshot({
        path: path.join(directory, file),
        fullPage: true,
        animations: "disabled"
      });
      captures.push({ stage, file });
    },
    evidence() {
      return { enabled: Boolean(directory), count: captures.length, captures: [...captures] };
    }
  };
}

async function browserJson(page, route, { method = "GET", body = null } = {}) {
  return page.evaluate(async request => {
    const response = await fetch(request.route, {
      method: request.method,
      credentials: "same-origin",
      headers: request.body == null ? undefined : { "content-type": "application/json" },
      body: request.body == null ? undefined : JSON.stringify(request.body)
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    return { status: response.status, payload };
  }, { route, method, body });
}

function routeClass(route) {
  if (route.includes("/auth/session")) return "auth_session";
  if (route.includes("/approval-gates")) return "approval";
  if (route.includes("/agent-result")) return "agent_result";
  if (route.includes("/chat/interactions")) return "chat";
  if (route.includes("/workspaces")) return "workspace";
  return "other";
}

function positiveTimeout(value, fallback = DEFAULT_TIMEOUT_MS) {
  const parsed = Number(value || fallback);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function apiFailureCode(response, fallback) {
  const candidate = String(response?.payload?.error_code || "");
  return /^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(candidate) ? candidate : fallback;
}

export function apiSemanticFailureStage(response) {
  const candidate = String(response?.payload?.details?.semantic_stage || "");
  return ["INTENT", "CONTEXT", "PLAN"].includes(candidate) ? candidate : null;
}

function safeFailureCode(error) {
  const value = String(error?.message || error?.constructor?.name || "playwright_failed");
  if (/^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(value)) return value;
  const name = String(error?.name || error?.constructor?.name || "playwright_failed");
  return /^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(name) ? name : "playwright_failed";
}

function failure(failureCode, observations = {}) {
  return {
    smoke_schema_version: MYBEE_M1_PRODUCT_GOLDEN_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    observations,
    checks: {}
  };
}

function assertRedacted(evidence, environ) {
  const serialized = JSON.stringify(evidence);
  for (const name of SENSITIVE) {
    const value = environ[name];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`MyBee M1 evidence leaked ${name}`);
    }
  }
  for (const fragment of ["access_token", "api_key", "database_url", "password_hash", "service_token"]) {
    if (serialized.toLowerCase().includes(fragment)) {
      throw new Error("MyBee M1 evidence leaked protected material");
    }
  }
}

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `mybee_m1_product_golden=pass transactions=${evidence.observations.transaction_count}`
    : `mybee_m1_product_golden=fail reason=${evidence.failure_code || "checks_failed"}`;
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const evidence = argv.includes("--recovery")
    ? await runMyBeeM1ProductPostRestartRecovery()
    : await runMyBeeM1ProductGoldenJourney();
  output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence));
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
