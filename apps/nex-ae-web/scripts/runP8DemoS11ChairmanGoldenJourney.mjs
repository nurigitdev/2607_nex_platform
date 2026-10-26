#!/usr/bin/env node
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";

import { PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV } from "./runCredentialLoginPlaywrightReadiness.mjs";

export const P8_DEMO_S11_PLAYWRIGHT_SCHEMA_VERSION =
  "p8_demo_s11_chairman_golden_journey_playwright.v1";

const ENV = {
  webUrl: "NEX_P8_DEMO_S11_WEB_URL",
  tenantId: "NEX_P8_DEMO_S11_TENANT_ID",
  requesterEmployeeId: "NEX_P8_DEMO_S11_REQUESTER_EMPLOYEE_ID",
  requesterPassword: "NEX_P8_DEMO_S11_REQUESTER_PASSWORD",
  approverEmployeeId: "NEX_P8_DEMO_S11_APPROVER_EMPLOYEE_ID",
  approverPassword: "NEX_P8_DEMO_S11_APPROVER_PASSWORD",
  prompt: "NEX_P8_DEMO_S11_PROMPT",
  recoveryInteractionId: "NEX_P8_DEMO_S11_RECOVERY_INTERACTION_ID",
  timeoutMs: "NEX_P8_DEMO_S11_TIMEOUT_MS"
};
const REQUIRED_ENV = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.requesterEmployeeId,
  ENV.requesterPassword,
  ENV.approverEmployeeId,
  ENV.approverPassword,
  ENV.prompt
];
const RECOVERY_REQUIRED_ENV = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.requesterEmployeeId,
  ENV.requesterPassword,
  ENV.recoveryInteractionId
];
const DEFAULT_TIMEOUT_MS = 300_000;

export function p8DemoS11RuntimeConfig() {
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

export async function runP8DemoS11ChairmanGoldenJourney({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missing = REQUIRED_ENV.filter(name => !environ[name]);
  if (missing.length > 0) return failure("required_env_missing", { missing_count: missing.length });

  const timeout = positiveTimeout(environ[ENV.timeoutMs]);
  const interactionId = randomUUID();
  let browser = null;
  let requesterContext = null;
  let approverContext = null;
  let stage = "launch";
  let decisionRequest = null;
  let problemCode = null;
  const responses = [];
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    requesterContext = await browser.newContext(browserContextOptions());
    const requesterPage = await configuredPage(requesterContext);
    observeApiResponses(requesterPage, responses);

    stage = "anonymous_shell";
    await requesterPage.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout
    });
    const anonymousProtectedSurfaceHidden =
      (await requesterPage.isHidden("#authenticated-shell")) &&
      (await requesterPage.isHidden("#approval-panel"));

    stage = "requester_login";
    await login(requesterPage, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.requesterEmployeeId],
      password: environ[ENV.requesterPassword],
      timeout
    });

    stage = "workspace_create";
    const workspace = await browserJson(requesterPage, "/ae-api/api/v1/workspaces", {
      method: "POST",
      body: {
        title: `P8 Demo S11 ${interactionId.slice(0, 8)}`,
        runtime_defaults: {
          locale: "ko-KR",
          execution_mode: "GENERAL_ANSWER",
          generation_alias: "general-llm-default"
        }
      }
    });
    if (workspace.status !== 200) throw new Error(`WorkspaceCreateStatus${workspace.status}`);

    stage = "live_plan_admission";
    const admission = await browserJson(
      requesterPage,
      "/ae-api/api/v1/chat/interactions",
      {
        method: "POST",
        body: {
          interaction_id: interactionId,
          workspace_id: workspace.payload.workspace_id,
          chat_document_id: workspace.payload.chat_document_id,
          conversation_id: workspace.payload.chat_document_id,
          user_message: environ[ENV.prompt],
          generation: {
            execution_strategy: "ASYNCHRONOUS",
            execution_mode: "GENERAL_ANSWER",
            reasoning_mode: "disabled"
          },
          retrieval: {
            enabled: false,
            execution_mode: "GENERAL_CHAT",
            document_scope: null,
            retrieval_profile: { search_strategy: "hybrid" },
            top_k: 5,
            include_neighbors: false,
            include_source_preview: false,
            purpose: "search"
          }
        }
      }
    );
    if (
      admission.status !== 202 ||
      admission.payload?.generation?.semantic_planning?.status !== "COMPILED"
    ) {
      problemCode = publicProblemCode(admission.payload);
      throw new Error(`LivePlanAdmissionStatus${admission.status}`);
    }
    const semanticStages = admission.payload.generation.semantic_planning.stages || [];

    stage = "approver_login";
    approverContext = await browser.newContext(browserContextOptions());
    const approverPage = await configuredPage(approverContext);
    observeApiResponses(approverPage, responses);
    approverPage.on("request", request => {
      const route = new URL(request.url()).pathname;
      if (request.method() === "POST" && route.endsWith("/decisions")) {
        decisionRequest = { route, payload: request.postDataJSON() };
      }
    });
    await approverPage.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout
    });
    await login(approverPage, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.approverEmployeeId],
      password: environ[ENV.approverPassword],
      timeout
    });

    stage = "approval_wait";
    const gateId = await waitForNslWriteGate(approverPage, timeout);
    await approverPage.click('[data-shell-view="approvals"]');
    await approverPage.waitForSelector('.approval-feedback[data-phase="READY"]', { timeout });
    await approverPage.waitForSelector(`[data-approval-gate-id="${gateId}"]`, { timeout });

    stage = "approval_decision";
    await approverPage.click(`[data-approval-gate-id="${gateId}"]`);
    await approverPage.waitForSelector('.approval-feedback[data-phase="DETAIL_READY"]', { timeout });
    await approverPage.fill("#approval-decision-comment", "P8-DEMO-S11 protected acceptance");
    await approverPage.click('[data-approval-decision="APPROVE"]');
    await approverPage.waitForSelector('.approval-feedback[data-phase="DECIDED"]', { timeout });
    if (!decisionRequest) throw new Error("ApprovalDecisionRequestMissing");

    stage = "approval_replay";
    const replay = await browserJson(approverPage, decisionRequest.route, {
      method: "POST",
      body: decisionRequest.payload
    });

    stage = "result_wait";
    const resultProjection = await waitForAgentResult(
      requesterPage,
      interactionId,
      timeout
    );
    const rendered = await renderAgentResult(requesterPage, resultProjection);

    stage = "logout";
    await logout(approverPage, timeout);
    await logout(requesterPage, timeout);
    const checks = {
      chromium_launched: true,
      anonymous_protected_surface_hidden: anonymousProtectedSurfaceHidden,
      requester_authenticated: true,
      approver_authenticated: true,
      workspace_created: true,
      live_plan_compiled: true,
      all_semantic_stages_admitted:
        semanticStages.length === 3 &&
        semanticStages.every(item => item.directive === "CONTINUE"),
      nsl_write_gate_rendered: true,
      approval_committed: true,
      exact_decision_replay_idempotent: replay.status === 200,
      agent_result_terminal: resultProjection.terminal === true,
      agent_result_succeeded: resultProjection.result?.status === "SUCCEEDED",
      result_delivery_acknowledged:
        resultProjection.result?.delivery?.state === "ACKNOWLEDGED",
      eos_business_reference_visible: (resultProjection.result?.business_refs || []).some(
        value => value.startsWith("EOS:BUSINESS_OPERATION:")
      ),
      browser_result_presented: rendered,
      requester_logout_returned_to_login:
        await requesterPage.isVisible("#credential-login-panel"),
      approver_logout_returned_to_login:
        await approverPage.isVisible("#credential-login-panel")
    };
    const evidence = {
      smoke_schema_version: P8_DEMO_S11_PLAYWRIGHT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        client_mode: "fetch",
        session_count: 2
      },
      observations: {
        semantic_stage_count: semanticStages.length,
        approval_gate_count: 1,
        approval_replay_status: replay.status,
        authenticated_http_response_count: responses.length,
        result_business_ref_count:
          resultProjection.result?.business_refs?.length || 0,
        result_external_ref_count:
          resultProjection.result?.external_refs?.length || 0
      },
      checks,
      runtime: {
        interaction_id: interactionId,
        workspace_id: workspace.payload.workspace_id,
        chat_document_id: workspace.payload.chat_document_id,
        result_projection: resultProjection
      }
    };
    assertP8DemoS11EvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = failure(safeFailureCode(error), {
      stage,
      response_count: responses.length,
      recent_api_responses: responses.slice(-5),
      problem_code: problemCode
    });
    assertP8DemoS11EvidenceRedacted(evidence, environ);
    return evidence;
  } finally {
    if (approverContext) await approverContext.close();
    if (requesterContext) await requesterContext.close();
    if (browser) await browser.close();
  }
}

export async function runP8DemoS11PostRestartRecovery({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missing = RECOVERY_REQUIRED_ENV.filter(name => !environ[name]);
  if (missing.length > 0) return failure("recovery_env_missing", { missing_count: missing.length });
  const timeout = positiveTimeout(environ[ENV.timeoutMs]);
  let browser = null;
  let context = null;
  let stage = "launch";
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    context = await browser.newContext(browserContextOptions());
    const page = await configuredPage(context);
    stage = "requester_login";
    await page.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout });
    await login(page, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.requesterEmployeeId],
      password: environ[ENV.requesterPassword],
      timeout
    });
    stage = "authoritative_result_recovery";
    const projection = await waitForAgentResult(
      page,
      environ[ENV.recoveryInteractionId],
      timeout
    );
    const rendered = await renderAgentResult(page, projection);
    await logout(page, timeout);
    const checks = {
      authenticated_after_restart: true,
      authoritative_result_recovered: projection.terminal === true,
      recovered_result_succeeded: projection.result?.status === "SUCCEEDED",
      recovered_delivery_acknowledged:
        projection.result?.delivery?.state === "ACKNOWLEDGED",
      browser_result_presented_after_restart: rendered,
      logout_returned_to_login: await page.isVisible("#credential-login-panel")
    };
    const evidence = {
      smoke_schema_version: P8_DEMO_S11_PLAYWRIGHT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      recovery_mode: true,
      observations: {
        result_business_ref_count: projection.result?.business_refs?.length || 0,
        result_external_ref_count: projection.result?.external_refs?.length || 0
      },
      checks,
      runtime: {
        interaction_id: environ[ENV.recoveryInteractionId],
        result_projection: projection
      }
    };
    assertP8DemoS11EvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = failure(safeFailureCode(error), { stage, recovery_mode: true });
    assertP8DemoS11EvidenceRedacted(evidence, environ);
    return evidence;
  } finally {
    if (context) await context.close();
    if (browser) await browser.close();
  }
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

function browserContextOptions() {
  return {
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 }
  };
}

async function configuredPage(context) {
  const page = await context.newPage();
  await page.addInitScript(config => {
    globalThis.__NEX_AE_WEB_CONFIG__ = config;
  }, p8DemoS11RuntimeConfig());
  return page;
}

function observeApiResponses(page, responses) {
  page.on("response", response => {
    const route = new URL(response.url()).pathname;
    if (route.startsWith("/ae-api/api/v1/")) {
      responses.push({ route: publicRouteClass(route), status: response.status() });
    }
  });
}

async function login(page, { tenantId, employeeId, password, timeout }) {
  await page.fill("#credential-tenant-id", tenantId);
  await page.fill("#credential-employee-id", employeeId);
  await page.fill("#credential-password", password);
  const responsePromise = page.waitForResponse(response => {
    const route = new URL(response.url()).pathname;
    return (
      response.request().method() === "POST" &&
      route === "/ae-api/api/v1/auth/session/login"
    );
  }, { timeout });
  await page.click("#credential-login-submit-button");
  const response = await responsePromise;
  if (response.status() !== 200) {
    throw new Error(`CredentialLoginStatus${response.status()}`);
  }
  await page.waitForSelector("#authenticated-shell:not([hidden])", { timeout });
}

async function logout(page, timeout) {
  await page.click("#credential-logout-button");
  await page.waitForSelector("#authentication-shell:not([hidden])", { timeout });
}

async function waitForNslWriteGate(page, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const response = await browserJson(page, "/ae-api/api/v1/approval-gates?limit=50");
    if (response.status === 200) {
      const gates = (response.payload?.gates || []).filter(
        item => item.approval_domain === "NSL_WRITE" && item.state === "PENDING"
      );
      if (gates.length > 1) throw new Error("ApprovalGateAmbiguous");
      if (gates[0]?.gate_id) return gates[0].gate_id;
    }
    await page.waitForTimeout(500);
  }
  throw new Error("ApprovalGateTimeout");
}

async function waitForAgentResult(page, interactionId, timeout) {
  const route = `/ae-api/api/v1/chat/interactions/${encodeURIComponent(
    interactionId
  )}/agent-result`;
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const response = await browserJson(page, route);
    if (response.status === 200 && response.payload?.terminal === true) {
      return response.payload;
    }
    if (![200, 404].includes(response.status)) {
      throw new Error(`AgentResultStatus${response.status}`);
    }
    await page.waitForTimeout(750);
  }
  throw new Error("AgentResultTimeout");
}

async function renderAgentResult(page, projection) {
  return page.evaluate(async value => {
    const module = await import("/src/interactionAgentResultClient.js");
    const projected = module.projectInteractionAgentResult(value, {
      clientMode: "fetch",
      route: "owner-scoped-agent-result"
    });
    const container = document.querySelector("#message-list");
    container.insertAdjacentHTML("beforeend", module.renderInteractionAgentResult(projected));
    const card = container.querySelector(".agent-result[data-agent-result-state='SUCCEEDED']");
    return Boolean(card && card.textContent.includes("업무 처리 결과"));
  }, projection);
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

function publicRouteClass(route) {
  if (route.includes("/auth/session")) return "auth_session";
  if (route.includes("/approval-gates")) return "approval";
  if (route.includes("/agent-result")) return "agent_result";
  if (route.includes("/chat/interactions")) return "chat";
  if (route.includes("/workspaces")) return "workspace";
  return "other";
}

function publicProblemCode(payload) {
  const value = payload?.error_code;
  return typeof value === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(value)
    ? value
    : null;
}

function positiveTimeout(value) {
  const parsed = Number(value || DEFAULT_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

function safeFailureCode(error) {
  const value = String(error?.message || error?.constructor?.name || "playwright_failed");
  return /^[A-Za-z][A-Za-z0-9]{0,95}$/.test(value) ? value : "playwright_failed";
}

function failure(failureCode, observations = {}) {
  return {
    smoke_schema_version: P8_DEMO_S11_PLAYWRIGHT_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    observations,
    checks: {}
  };
}

export function publicP8DemoS11PlaywrightEvidence(evidence) {
  const { runtime: _runtime, ...publicEvidence } = evidence;
  return publicEvidence;
}

export function assertP8DemoS11EvidenceRedacted(evidence, environ = process.env) {
  const serialized = JSON.stringify(evidence);
  for (const name of [...new Set([...REQUIRED_ENV, ...RECOVERY_REQUIRED_ENV])]) {
    const value = environ[name];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`P8-DEMO-S11 evidence leaked ${name}`);
    }
  }
  for (const fragment of ["access_token", "api_key", "database_url", "password_hash", "service_token"]) {
    if (serialized.toLowerCase().includes(fragment)) {
      throw new Error("P8-DEMO-S11 evidence leaked protected material");
    }
  }
}

export function formatP8DemoS11Summary(evidence) {
  return evidence.status === "PASS"
    ? `p8_demo_s11_playwright=pass checks=${Object.keys(evidence.checks).length}`
    : `p8_demo_s11_playwright=fail reason=${evidence.failure_code || "checks_failed"}`;
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const evidence = argv.includes("--recovery")
    ? await runP8DemoS11PostRestartRecovery()
    : await runP8DemoS11ChairmanGoldenJourney();
  output(
    argv.includes("--summary")
      ? formatP8DemoS11Summary(evidence)
      : JSON.stringify(evidence)
  );
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
