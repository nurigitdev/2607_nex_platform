#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";
import { createServer } from "vite";

import { evaluateUxAcceptanceV2Page, verifyKeyboardFocusVisible } from "./uxAcceptanceV2Browser.mjs";

export const MODERN_SECURITY_BOUNDARY_SMOKE_SCHEMA_VERSION =
  "ae_web_modern_security_boundary_smoke.uxm_s07.v1";

const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_EVIDENCE_DIR = resolve(
  APP_ROOT,
  "../../reports/uiux/security-boundary",
);
const PROTECTED_SERVICE_PORTS = new Set(["8101", "8102", "8103", "8104", "8105"]);

export async function runModernSecurityBoundaryPlaywrightSmoke({
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
    const protectedServiceRequests = [];

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api")) {
        businessRequests.push({
          method: request.method(),
          origin: url.origin,
          pathname: url.pathname,
          body: request.postData() ?? "",
        });
      }
      if (PROTECTED_SERVICE_PORTS.has(url.port)) protectedServiceRequests.push(request.url());
    });
    await page.route("**/ae-api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname.endsWith("/session") && request.method() === "GET") {
        await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
        return;
      }
      if (url.pathname.endsWith("/session/login") && request.method() === "POST") {
        const input = request.postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(activeSession(input)),
        });
        return;
      }
      if (url.pathname.endsWith("/session/logout") && request.method() === "POST") {
        await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
        return;
      }
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });

    await mkdir(evidenceDir, { recursive: true });
    await page.goto(`${origin}/modern.html`, { waitUntil: "networkidle", timeout: 30_000 });
    await page.getByRole("heading", { name: "사번 로그인" }).waitFor();
    await page.screenshot({
      path: resolve(evidenceDir, "01-login-desktop.png"),
      fullPage: true,
    });
    const anonymousSurface = await page.evaluate(() => ({
      title: document.title,
      body: document.body.innerText,
      runtimeConfig: document.querySelector("#ae-web-runtime-config")?.textContent ?? "",
    }));
    const loginAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "login", viewport: "desktop", requestUrls: businessRequests.map(item => `${item.origin}${item.pathname}`),
    });

    await page.getByLabel(/^사번\s*\*?$/).fill("EMP-UXM-S07");
    await page.getByLabel(/^비밀번호\s*\*?$/).fill("protected-smoke-password");
    await page.getByRole("button", { name: "로그인" }).click();
    await page.getByRole("heading", { name: "작업 공간" }).waitFor();
    await page.screenshot({
      path: resolve(evidenceDir, "02-workspace-desktop.png"),
      fullPage: true,
    });
    const workspaceDesktopAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "workspace", viewport: "desktop", requestUrls: businessRequests.map(item => `${item.origin}${item.pathname}`),
    });
    const keyboardFocusVisible = await verifyKeyboardFocusVisible(page);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: resolve(evidenceDir, "03-workspace-mobile.png"),
      fullPage: false,
    });
    const mobile = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      viewportWidth: window.innerWidth,
    }));
    const workspaceMobileAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "workspace", viewport: "mobile", requestUrls: businessRequests.map(item => `${item.origin}${item.pathname}`),
    });

    await page.getByRole("button", { name: "로그아웃" }).click();
    await page.getByRole("heading", { name: "사번 로그인" }).waitFor();

    const businessBoundaryPass = businessRequests.length >= 3 && businessRequests.every(
      request => request.origin === origin &&
        (request.pathname === "/ae-api" || request.pathname.startsWith("/ae-api/")),
    );
    const browserCredentialPass = businessRequests.every(request =>
      !/(?:service_token|api_key|authorization)/i.test(request.body),
    );
    const checks = Object.freeze({
      production_config_is_fetch_facade:
        anonymousSurface.runtimeConfig.includes('"client_mode":"fetch"') &&
        anonymousSurface.runtimeConfig.includes('"ae_base_url":"/ae-api"'),
      anonymous_surface_hides_internal_details:
        !/(?:8101|8102|8103|8104|8105|database|provider endpoint)/i.test(anonymousSurface.body),
      all_business_requests_use_same_origin_ae_facade: businessBoundaryPass,
      no_protected_service_port_requested: protectedServiceRequests.length === 0,
      no_service_credential_in_browser_requests: browserCredentialPass,
      authenticated_workspace_rendered: true,
      mobile_has_no_horizontal_overflow: !mobile.overflow,
      logout_returns_to_login: true,
      login_acceptance_v2: loginAcceptance.status === "PASS",
      workspace_desktop_acceptance_v2: workspaceDesktopAcceptance.status === "PASS",
      workspace_mobile_acceptance_v2: workspaceMobileAcceptance.status === "PASS",
      keyboard_focus_visible: keyboardFocusVisible,
    });

    return Object.freeze({
      smoke_schema_version: MODERN_SECURITY_BOUNDARY_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: Object.freeze({ tool: "Playwright", browser: "chromium", headless: true }),
      observations: Object.freeze({
        business_request_count: businessRequests.length,
        protected_service_request_count: protectedServiceRequests.length,
        screenshot_count: 3,
        mobile_viewport_width: mobile.viewportWidth,
        evidence_dir: evidenceDir,
        acceptance_v2: Object.freeze({
          login: loginAcceptance,
          workspace_desktop: workspaceDesktopAcceptance,
          workspace_mobile: workspaceMobileAcceptance,
        }),
      }),
      checks,
    });
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

function activeSession(input) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-uxm-s07",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: input.tenant_id },
    subject_ref: { type: "oa.user", id: "subject-uxm-s07" },
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

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `modern_security_boundary_playwright_smoke=pass requests=${evidence.observations.business_request_count} checks=${Object.keys(evidence.checks).length}`
    : "modern_security_boundary_playwright_smoke=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runModernSecurityBoundaryPlaywrightSmoke();
    output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`modern_security_boundary_playwright_smoke=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
