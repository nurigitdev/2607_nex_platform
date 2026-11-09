#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";
import { createServer } from "vite";

import { evaluateUxAcceptanceV2Page } from "./uxAcceptanceV2Browser.mjs";

export const MODERN_OPERATIONS_SMOKE_SCHEMA_VERSION = "ae_web_modern_operations_smoke.uxm_s17.v1";
const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_EVIDENCE_DIR = resolve(APP_ROOT, "../../reports/uiux/operations-isolation");
const PROTECTED_PORTS = new Set(["8101", "8102", "8103", "8104", "8105", "8106", "8107", "8108"]);

export async function runModernOperationsPlaywrightSmoke({ evidenceDir = DEFAULT_EVIDENCE_DIR } = {}) {
  const server = await createServer({ root: APP_ROOT, logLevel: "error", server: { host: "127.0.0.1", port: 0, strictPort: false } });
  let browser;
  try {
    await server.listen();
    const address = server.httpServer?.address();
    if (!address || typeof address === "string") throw new Error("Vite port is unavailable");
    const origin = `http://127.0.0.1:${address.port}`;
    const requests = [];
    const directRequests = [];
    let session = null;
    let operationsUnavailable = false;
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    context.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api")) requests.push({ origin: url.origin, path: url.pathname, method: request.method(), body: request.postData() ?? "" });
      if (PROTECTED_PORTS.has(url.port)) directRequests.push(request.url());
    });
    await context.route("**/ae-api/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.slice("/ae-api".length);
      if (path.endsWith("/session") && request.method() === "GET") return session ? json(route, 200, session) : json(route, 401, {});
      if (path.endsWith("/session/login") && request.method() === "POST") {
        const input = request.postDataJSON();
        session = activeSession(input, String(input.employee_id).startsWith("OP-") ? "operator" : "employee");
        return json(route, 200, session);
      }
      if (path.endsWith("/session/logout") && request.method() === "POST") {
        session = null;
        return json(route, 401, {});
      }
      if (path === "/api/v1/web/operations/summary" && request.method() === "GET") {
        return operationsUnavailable
          ? json(route, 503, { error_code: "AE_WEB_OPERATIONS_UNAVAILABLE", retryable: true })
          : json(route, 200, operationsSummary());
      }
      return json(route, 404, {});
    });

    await mkdir(evidenceDir, { recursive: true });
    const page = await context.newPage();
    await page.goto(`${origin}/modern.html`, { waitUntil: "networkidle" });
    await login(page, "EMP-UXM-S17");
    const employeeMenuHidden = await page.getByRole("link", { name: "운영/진단" }).count() === 0;
    await page.evaluate(() => {
      history.pushState({}, "", "/operations");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.getByRole("heading", { name: "작업 공간" }).waitFor();
    const employeeRequestBlocked = !requests.some(item => item.path.endsWith("/web/operations/summary"));
    await page.getByRole("button", { name: "로그아웃" }).click();
    await page.getByRole("heading", { name: "사번 로그인" }).waitFor();

    await login(page, "OP-UXM-S17");
    await page.getByRole("link", { name: "운영/진단" }).click();
    await page.getByRole("heading", { name: "운영/진단" }).waitFor();
    await page.getByText("ae-web-operations-summary").waitFor();
    await page.screenshot({ path: resolve(evidenceDir, "01-operations-desktop.png"), fullPage: true });
    const desktop = await snapshot(page);
    const desktopAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "application",
      viewport: "desktop",
      requestUrls: requests.map(item => `${item.origin}${item.path}`),
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: resolve(evidenceDir, "02-operations-mobile.png"), fullPage: true });
    const mobile = await snapshot(page);
    const mobileAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "application",
      viewport: "mobile",
      requestUrls: requests.map(item => `${item.origin}${item.path}`),
    });

    operationsUnavailable = true;
    await page.getByRole("button", { name: "새로고침" }).click();
    await page.getByRole("alert").waitFor();
    const boundedUnavailable = await page.getByRole("alert").textContent();
    const checks = {
      employee_menu_hidden: employeeMenuHidden,
      employee_direct_route_blocked: employeeRequestBlocked,
      operator_projection_visible: desktop.body.includes("서비스 상태") && desktop.body.includes("런타임 진단"),
      bounded_unavailable_guidance: boundedUnavailable?.includes("운영 정보를 불러오지 못했습니다.") === true,
      no_private_detail: !/127\.0\.0\.1:81\d\d|service_token|database_url|provider_endpoint|\/data\//i.test(desktop.body),
      desktop_no_overflow: !desktop.overflow,
      mobile_no_overflow: !mobile.overflow,
      same_origin_only: requests.every(item => item.origin === origin && item.path.startsWith("/ae-api/")),
      no_direct_service_request: directRequests.length === 0,
      no_browser_service_credential: requests.every(item => !/authorization|service_token|api_key/i.test(item.body)),
      desktop_acceptance_v2: desktopAcceptance.status === "PASS",
      mobile_acceptance_v2: mobileAcceptance.status === "PASS",
    };
    return {
      schema_version: MODERN_OPERATIONS_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      checks,
      observations: { request_count: requests.length, direct_request_count: directRequests.length, screenshot_count: 2, acceptance_v2: { desktop: desktopAcceptance, mobile: mobileAcceptance } },
    };
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

async function login(page, employeeId) {
  await page.getByLabel(/^사번\s*\*?$/).fill(employeeId);
  await page.getByLabel(/^비밀번호\s*\*?$/).fill("protected-smoke-password");
  await page.getByRole("button", { name: "로그인" }).click();
  await page.getByRole("heading", { name: "작업 공간" }).waitFor();
}

function activeSession(input, role) {
  return {
    browser_session_schema_version: "oa_browser_session.v1", session_id: `session-uxm-s17-${role}`, status: "ACTIVE", issuer: "nex-oa", audience: "nex-ae-api", token_use: "user",
    tenant_ref: { type: "oa.tenant", id: input.tenant_id }, subject_ref: { type: "oa.user", id: `subject-uxm-s17-${role}` }, scopes: input.requested_scopes, roles: [role],
    issued_at: "2026-11-09T00:00:00Z", expires_at: "2026-11-09T01:00:00Z",
    metadata: { raw_token_included: false, service_token_included: false, password_included: false, browser_payload_owner_authoritative: false, claim_owner_authoritative: true },
  };
}

function operationsSummary() {
  return {
    operations_summary_schema_version: "ae_web_operations_summary.v1", overall_status: "READY",
    services: [
      { service_id: "nex-oa", health_status: "HEALTHY", readiness_status: "READY", version: "2.1.0" },
      { service_id: "nex-ae-api", health_status: "HEALTHY", readiness_status: "READY", version: "2.1.0" },
      { service_id: "nex-mo", health_status: "UNKNOWN", readiness_status: "NOT_OBSERVED", version: null },
    ],
    runtime: { database_status: "AVAILABLE", agent_runtime_status: "AVAILABLE", provider_route_status: "CONFIGURED" },
    safe_routes: [{ route_id: "ae-web-operations-summary", method: "GET", path: "/api/v1/web/operations/summary" }],
    metadata: { read_only: true, same_origin_required: true, direct_service_requests_allowed: false, protected_material_included: false, private_content_included: false },
  };
}

async function snapshot(page) {
  return page.evaluate(() => ({ body: document.body.innerText, overflow: document.documentElement.scrollWidth > window.innerWidth + 1 }));
}

async function json(route, status, body) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `modern_operations_playwright_smoke=pass requests=${evidence.observations.request_count} screenshots=${evidence.observations.screenshot_count} checks=${Object.keys(evidence.checks).length}`
    : "modern_operations_playwright_smoke=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runModernOperationsPlaywrightSmoke();
    output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`modern_operations_playwright_smoke=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await main();
