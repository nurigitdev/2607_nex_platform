#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";
import { createServer } from "vite";

import { evaluateUxAcceptanceV2Page } from "./uxAcceptanceV2Browser.mjs";

export const MODERN_WORKSPACE_EXECUTION_SMOKE_SCHEMA_VERSION =
  "ae_web_modern_workspace_execution_smoke.uxm_s14.v1";

const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_EVIDENCE_DIR = resolve(APP_ROOT, "../../reports/uiux/workspace-checkpoint");

export async function runModernWorkspaceExecutionPlaywrightSmoke({
  evidenceDir = DEFAULT_EVIDENCE_DIR,
} = {}) {
  const server = await createServer({
    root: APP_ROOT,
    logLevel: "error",
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  let browser;
  try {
    await server.listen();
    const address = server.httpServer?.address();
    if (!address || typeof address === "string") throw new Error("Vite port is unavailable");
    const origin = `http://127.0.0.1:${address.port}`;
    const businessRequests = [];
    let interactionId = null;
    let resultReadCount = 0;

    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    context.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api")) {
        businessRequests.push({
          method: request.method(),
          origin: url.origin,
          pathname: url.pathname,
          body: request.postData() ?? "",
        });
      }
    });
    await context.route("**/ae-api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.slice("/ae-api".length);
      if (path.endsWith("/session") && request.method() === "GET") {
        await json(route, 401, {});
        return;
      }
      if (path.endsWith("/session/login") && request.method() === "POST") {
        await json(route, 200, activeSession(request.postDataJSON()));
        return;
      }
      if (path === "/api/v1/workspaces" && request.method() === "POST") {
        await json(route, 200, workspaceResponse());
        return;
      }
      if (path === "/api/v1/chat/interactions" && request.method() === "POST") {
        const input = request.postDataJSON();
        interactionId = input.interaction_id;
        await json(route, 200, admittedInteraction(input));
        return;
      }
      if (path.endsWith("/agent-result") && request.method() === "GET") {
        resultReadCount += 1;
        await json(route, 200, agentResult(interactionId, resultReadCount));
        return;
      }
      await json(route, 404, {});
    });

    const page = await context.newPage();
    await mkdir(evidenceDir, { recursive: true });
    await page.goto(`${origin}/modern.html`, { waitUntil: "networkidle", timeout: 30_000 });
    await page.getByLabel(/^사번\s*\*?$/).fill("EMP-UXM-S14");
    await page.getByLabel(/^비밀번호\s*\*?$/).fill("protected-smoke-password");
    await page.getByRole("button", { name: "로그인" }).click();
    await page.getByRole("heading", { name: "작업 공간" }).waitFor();

    await page.getByRole("textbox", { name: "업무 요청" }).fill("NVT 프로젝트 교통비 전표를 등록해 주세요.");
    await page.getByRole("button", { name: "보내기" }).click();
    await page.getByText("승인 대기", { exact: true }).first().waitFor({ timeout: 10_000 });
    await page.screenshot({
      path: resolve(evidenceDir, "01-approval-wait-desktop.png"),
      fullPage: true,
    });

    await page.getByRole("heading", { name: "전표 등록 결과" }).waitFor({ timeout: 12_000 });
    await page.screenshot({
      path: resolve(evidenceDir, "02-result-desktop.png"),
      fullPage: true,
    });
    const desktop = await page.evaluate(() => ({
      body: document.body.innerText,
      progress: document.querySelector('[aria-label="실제 업무 진행 단계"]')?.textContent ?? "",
      overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    }));
    const desktopAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "workspace-result",
      viewport: "desktop",
      requestUrls: businessRequests.map(item => `${item.origin}${item.pathname}`),
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("heading", { name: "전표 등록 결과" }).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: resolve(evidenceDir, "03-result-mobile.png"),
      fullPage: false,
    });
    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    const mobileAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "workspace-result",
      viewport: "mobile",
      requestUrls: businessRequests.map(item => `${item.origin}${item.pathname}`),
    });
    const facadeOnly = businessRequests.every(request =>
      request.origin === origin && request.pathname.startsWith("/ae-api/"),
    );
    const noCredentialLeak = businessRequests.every(request =>
      !/(?:service_token|api_key|authorization_header|bearer\s)/i.test(request.body),
    );
    const checks = Object.freeze({
      owner_scoped_workspace_created: businessRequests.some(request =>
        request.pathname === "/ae-api/api/v1/workspaces" &&
        !/(?:tenant_id|owner_user_id)/.test(request.body),
      ),
      interaction_admitted_through_ae_facade: Boolean(interactionId) && facadeOnly,
      approval_wait_observed: resultReadCount >= 3,
      actual_progress_only:
        desktop.progress.includes("요청 접수") &&
        desktop.progress.includes("업무 계획") &&
        desktop.progress.includes("승인 대기") &&
        desktop.progress.includes("처리 재개") &&
        desktop.progress.includes("완료"),
      typed_voucher_result_rendered:
        desktop.body.includes("V-UXM-S14-001") && desktop.body.includes("12,500 KRW"),
      internal_operation_hidden: !desktop.body.includes("operation-private-s14"),
      no_browser_credential_leak: noCredentialLeak,
      desktop_has_no_horizontal_overflow: !desktop.overflow,
      mobile_has_no_horizontal_overflow: !mobileOverflow,
      desktop_acceptance_v2: desktopAcceptance.status === "PASS",
      mobile_acceptance_v2: mobileAcceptance.status === "PASS",
    });
    return Object.freeze({
      smoke_schema_version: MODERN_WORKSPACE_EXECUTION_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      observations: Object.freeze({
        business_request_count: businessRequests.length,
        result_read_count: resultReadCount,
        screenshot_count: 3,
        acceptance_v2: { desktop: desktopAcceptance, mobile: mobileAcceptance },
        evidence_dir: evidenceDir,
      }),
      checks,
    });
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

function workspaceResponse() {
  return {
    workspace_schema_version: "ae_workspace_state.v1",
    workspace_id: "workspace-uxm-s14",
    chat_document_id: "conversation-uxm-s14",
    title: "내 업무 공간",
  };
}

function admittedInteraction(input) {
  return {
    interaction_schema_version: "ae_chat_interaction.v1",
    interaction_id: input.interaction_id,
    workspace_id: input.workspace_id,
    chat_document_id: input.chat_document_id,
    status: "PENDING",
    cx_generation_id: null,
    cx_status: "NOT_REQUESTED",
    generation: {
      async_generation: { lifecycle_status: "PENDING", cancellable: true },
      semantic_planning: { status: "COMPILED" },
    },
    retrieval: null,
    artifact_refs: [],
  };
}

function agentResult(currentInteractionId, readCount) {
  const states = [
    ["WAITING_APPROVAL", "APPROVAL_WAIT"],
    ["RESUMING", "RESUME_EXECUTION"],
    ["SUCCEEDED", "FINALIZE"],
  ];
  const [executionState, executionPhase] = states[Math.min(readCount - 1, states.length - 1)];
  const terminal = executionState === "SUCCEEDED";
  return {
    schema_version: "ae_interaction_agent_result.v1",
    interaction_id: currentInteractionId,
    workspace_id: "workspace-uxm-s14",
    agent_execution_id: "agent-execution-uxm-s14",
    execution_state: executionState,
    execution_phase: executionPhase,
    terminal,
    result: terminal ? {
      status: "SUCCEEDED",
      business_refs: [],
      external_refs: [],
      artifact_refs: ["AE:ARTIFACT:uxm-s14"],
      warnings: [],
      business_summary: {
        result_type: "FINANCE.VOUCHER_DRAFT",
        summary_schema_version: "ae_business_result_summary.v1",
        summary: {
          outcome: "COMMITTED",
          verification_status: "VERIFIED",
          approval_state: "APPROVED",
          business_operation_id: "operation-private-s14",
          voucher_number: "V-UXM-S14-001",
          amount: "12500.00",
          currency: "KRW",
          account_codes: ["TRAVEL", "CASH"],
          project_code: "NVT",
          business_object_link: null,
        },
      },
      delivery: { state: "ACKNOWLEDGED", workspace_activity_ref: "AE:WORKSPACE_ACTIVITY:uxm-s14" },
    } : null,
    updated_at: "2026-11-08T10:00:00Z",
    completed_at: terminal ? "2026-11-08T10:00:04Z" : null,
  };
}

function activeSession(input) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-uxm-s14",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: input.tenant_id },
    subject_ref: { type: "oa.user", id: "subject-uxm-s14" },
    scopes: input.requested_scopes,
    roles: ["employee"],
    issued_at: "2026-11-08T00:00:00Z",
    expires_at: "2026-11-08T01:00:00Z",
    auth_time: "2026-11-08T00:00:00Z",
    metadata: {
      raw_token_included: false,
      service_token_included: false,
      password_included: false,
      browser_payload_owner_authoritative: false,
      claim_owner_authoritative: true,
    },
  };
}

async function json(route, status, body) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `modern_workspace_execution_playwright_smoke=pass requests=${evidence.observations.business_request_count} result_reads=${evidence.observations.result_read_count} checks=${Object.keys(evidence.checks).length}`
    : "modern_workspace_execution_playwright_smoke=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runModernWorkspaceExecutionPlaywrightSmoke();
    output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`modern_workspace_execution_playwright_smoke=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
