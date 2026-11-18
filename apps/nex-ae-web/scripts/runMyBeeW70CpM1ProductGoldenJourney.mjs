#!/usr/bin/env node
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
  approverEmployeeId: "NEX_MYBEE_M1_GOLDEN_APPROVER_EMPLOYEE_ID",
  approverPassword: "NEX_MYBEE_M1_GOLDEN_APPROVER_PASSWORD",
  promptsJson: "NEX_MYBEE_M1_GOLDEN_PROMPTS_JSON",
  recoveryInteractionId: "NEX_MYBEE_M1_GOLDEN_RECOVERY_INTERACTION_ID",
  screenshotDir: "NEX_MYBEE_M1_GOLDEN_SCREENSHOT_DIR",
  timeoutMs: "NEX_MYBEE_M1_GOLDEN_TIMEOUT_MS"
};
const REQUIRED = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.requesterEmployeeId,
  ENV.requesterPassword,
  ENV.approverEmployeeId,
  ENV.approverPassword,
  ENV.promptsJson
];
const RECOVERY_REQUIRED = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.requesterEmployeeId,
  ENV.requesterPassword,
  ENV.recoveryInteractionId
];
const SENSITIVE = [ENV.requesterPassword, ENV.approverPassword, ENV.promptsJson];
const DEFAULT_TIMEOUT_MS = 900_000;

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
  const timeout = positiveTimeout(environ[ENV.timeoutMs]);
  const captures = screenCapture(environ[ENV.screenshotDir], "journey");
  let browser;
  let requesterContext;
  let approverContext;
  let requesterPage;
  let approverPage;
  let stage = "launch";
  const responses = [];
  const transactions = [];
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    requesterContext = await browser.newContext(contextOptions());
    approverContext = await browser.newContext(contextOptions());
    const requester = requesterPage = await configuredPage(requesterContext);
    const approver = approverPage = await configuredPage(approverContext);
    observeResponses(requester, responses);
    observeResponses(approver, responses);

    stage = "anonymous_boundary";
    await requester.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout });
    await requester.getByRole("heading", { name: UI.loginHeading }).waitFor({ timeout });
    const anonymousProtectedSurfaceHidden =
      (await requester.getByRole("navigation", { name: UI.primaryNavigation }).count()) === 0 &&
      (await requester.getByRole("heading", { name: UI.approvalHeading }).count()) === 0;
    await captures.capture(requester, "login");

    stage = "requester_login";
    await login(requester, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.requesterEmployeeId],
      password: environ[ENV.requesterPassword],
      timeout
    });
    await captures.capture(requester, "requester-workspace");

    stage = "approver_login";
    await approver.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout });
    await login(approver, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.approverEmployeeId],
      password: environ[ENV.approverPassword],
      timeout
    });
    await captures.capture(approver, "approver-workspace");

    let workspace = null;
    for (let index = 0; index < prompts.length; index += 1) {
      stage = `transaction_${index + 1}_submit`;
      const admitted = await submitPrompt(requester, prompts[index], timeout, {
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
        throw new Error(apiFailureCode(admitted, `ProductAdmissionStatus${admitted.status}`));
      }
      const interactionId = admitted.payload.interaction_id;
      stage = `transaction_${index + 1}_approval_and_result`;
      const completed = await driveApprovalsUntilResult({
        requester,
        approver,
        interactionId,
        timeout,
        captures,
        transactionIndex: index + 1
      });
      if (completed.result?.status !== "SUCCEEDED") {
        throw new Error("ProductAgentResultNotSucceeded");
      }
      transactions.push({
        interaction_id: interactionId,
        semantic_stages: admitted.payload.generation.semantic_planning.stages || [],
        approval_domains: completed.approvalDomains,
        approval_replay_statuses: completed.replayStatuses,
        result_projection: completed
      });
      await captures.capture(requester, `transaction-${index + 1}-result`);
    }

    stage = "logout";
    await logout(approver, timeout);
    await logout(requester, timeout);
    await captures.capture(requester, "requester-logged-out");
    const requiredDomains = new Set(["BUSINESS_FORMAL", "ACCOUNTING_REVIEW", "NSL_WRITE"]);
    const observedDomains = new Set(transactions.flatMap(item => item.approval_domains));
    const checks = {
      chromium_launched: true,
      anonymous_protected_surface_hidden: anonymousProtectedSurfaceHidden,
      requester_authenticated: true,
      approver_authenticated: true,
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
      approver_logout_returned_to_login:
        await approver.getByRole("heading", { name: UI.loginHeading }).isVisible()
    };
    const evidence = {
      smoke_schema_version: MYBEE_M1_PRODUCT_GOLDEN_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        client_mode: "fetch",
        session_count: 2
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
    assertRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const failedPage = stage.startsWith("approver") ? approverPage : requesterPage;
    if (failedPage) {
      try {
        await captures.capture(failedPage, `${stage}-failure`);
      } catch {
        // The original bounded failure remains authoritative if capture also fails.
      }
    }
    const evidence = failure(safeFailureCode(error), {
      stage,
      response_count: responses.length,
      recent_api_responses: responses.slice(-8)
    });
    evidence.screen_capture = captures.evidence();
    assertRedacted(evidence, environ);
    return evidence;
  } finally {
    if (approverContext) await approverContext.close();
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
  const timeout = positiveTimeout(environ[ENV.timeoutMs]);
  const captures = screenCapture(environ[ENV.screenshotDir], "recovery");
  let browser;
  let context;
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    context = await browser.newContext(contextOptions());
    const page = await configuredPage(context);
    await page.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout });
    await login(page, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.requesterEmployeeId],
      password: environ[ENV.requesterPassword],
      timeout
    });
    const projection = await waitForResult(
      page,
      environ[ENV.recoveryInteractionId],
      timeout
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
  approver,
  interactionId,
  timeout,
  captures,
  transactionIndex
}) {
  const deadline = Date.now() + timeout;
  const approvalDomains = [];
  const replayStatuses = [];
  const decidedGateIds = new Set();
  while (Date.now() < deadline) {
    const current = await readResult(requester, interactionId);
    if (current?.terminal === true) {
      return { ...current, approvalDomains, replayStatuses };
    }
    const gates = await browserJson(approver, "/ae-api/api/v1/approval-gates?limit=100");
    if (gates.status !== 200) throw new Error(`ApprovalGateListStatus${gates.status}`);
    const pending = (gates.payload?.gates || []).filter(
      item => item.state === "PENDING" && !decidedGateIds.has(item.gate_id)
    );
    if (pending.length > 1) throw new Error("ApprovalGateAmbiguous");
    if (pending.length === 1) {
      const gate = pending[0];
      const decision = await decideGateInUi(
        approver,
        gate,
        timeout,
        `M1 product acceptance ${transactionIndex}`
      );
      decidedGateIds.add(gate.gate_id);
      approvalDomains.push(gate.approval_domain);
      replayStatuses.push(decision.replayStatus);
      await captures.capture(
        approver,
        `transaction-${transactionIndex}-approval-${approvalDomains.length}-${gate.approval_domain}`
      );
      continue;
    }
    await requester.waitForTimeout(500);
  }
  throw new Error("ProductResultTimeout");
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
    await page.getByRole("link", { name: UI.approvalLink, exact: true }).click();
    await page.getByRole("heading", { name: UI.approvalHeading, exact: true }).waitFor({ timeout });
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

function positiveTimeout(value) {
  const parsed = Number(value || DEFAULT_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

export function apiFailureCode(response, fallback) {
  const candidate = String(response?.payload?.error_code || "");
  return /^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(candidate) ? candidate : fallback;
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
