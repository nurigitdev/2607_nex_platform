#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import { createAeWebServer } from "./serve.mjs";

export const AE_WEB_AUTH_FIRST_SHELL_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_auth_first_shell_playwright_smoke.p8_s42a.v1";

const PROTECTED_SERVICE_PORTS = new Set(["8101", "8102", "8103", "8104", "8105"]);

export async function runAuthenticationFirstShellPlaywrightSmoke({
  importPlaywright = () => import("playwright")
} = {}) {
  const server = createAeWebServer();
  let browser = null;
  try {
    const port = await listen(server);
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const protectedServiceRequests = [];
    page.on("request", request => {
      const url = new URL(request.url());
      if (PROTECTED_SERVICE_PORTS.has(url.port)) {
        protectedServiceRequests.push(`${url.port}${url.pathname}`);
      }
    });

    await page.goto(`http://127.0.0.1:${port}/`, {
      waitUntil: "domcontentloaded",
      timeout: 25_000
    });
    await page.waitForSelector("#authentication-shell:not([hidden])");
    const anonymous = await page.evaluate(() => ({
      loginVisible: !document.querySelector("#authentication-shell")?.hidden,
      applicationHidden: document.querySelector("#authenticated-shell")?.hidden === true,
      serviceDetailsEmpty: !document.querySelector("#service-list")?.textContent?.trim(),
      runtimeDetailsEmpty:
        !document.querySelector("#runtime-diagnostics-summary")?.textContent?.trim() &&
        !document.querySelector("#runtime-diagnostics-preview")?.textContent?.trim()
    }));

    await page.fill("#credential-employee-id", "EMP-S42A-SMOKE");
    await page.fill("#credential-password", "mock-password");
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#authenticated-shell:not([hidden])");
    await page.waitForSelector('#golden-chat[data-shell-view-panel="workspace"]:not([hidden])');

    const routedViews = [];
    for (const [view, selector] of [
      ["approvals", "#approval-panel"],
      ["upload", "#upload-surface-panel"],
      ["documents", "#document-detail-panel"],
      ["retrieval", "#retrieval-scope-panel"],
      ["artifacts", "#artifact-panel"]
    ]) {
      await page.click(`[data-shell-view="${view}"]`);
      await page.waitForSelector(`${selector}:not([hidden])`);
      routedViews.push(view);
    }

    const authenticated = await page.evaluate(() => ({
      activeView: document.querySelector("#authenticated-shell")?.dataset.activeView,
      authenticationHidden: document.querySelector("#authentication-shell")?.hidden === true,
      applicationTitle: document.querySelector("#golden-topbar h1")?.textContent?.trim(),
      currentUserVisible:
        document.querySelector("#current-session-user")?.hidden === false,
      currentUserAccount:
        document.querySelector("#current-session-user-account")?.textContent?.trim(),
      employeeOperationsHidden:
        document.querySelector('[data-shell-view="operations"]')?.hidden === true,
      visibleProtectedPanelCount: [...document.querySelectorAll("[data-shell-view-panel]")]
        .filter(panel => !panel.hidden).length,
      logoutVisible: !document.querySelector("#credential-logout-button")?.hidden,
      timelineTopOffsets: [...document.querySelectorAll("#progress-timeline li")]
        .map(item => Math.round(item.getBoundingClientRect().top)),
      timelinePanelHeight:
        Math.round(document.querySelector("#golden-timeline")?.getBoundingClientRect().height || 0)
    }));

    await page.click('[data-shell-view="workspace"]');
    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await page.evaluate(() => ({
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      chatWidth: document.querySelector("#golden-chat")?.getBoundingClientRect().width || 0,
      viewportWidth: window.innerWidth,
      timelineTopOffsets: [...document.querySelectorAll("#progress-timeline li")]
        .map(item => Math.round(item.getBoundingClientRect().top)),
      timelinePanelHeight:
        Math.round(document.querySelector("#golden-timeline")?.getBoundingClientRect().height || 0)
    }));

    await page.click("#credential-logout-button");
    await page.waitForSelector("#authentication-shell:not([hidden])");
    const loggedOut = await page.evaluate(() => ({
      applicationHidden: document.querySelector("#authenticated-shell")?.hidden === true,
      protectedMessageCount: document.querySelectorAll("#message-list .message").length,
      protectedApprovalCount: document.querySelectorAll("[data-approval-domain]").length,
      passwordCleared: document.querySelector("#credential-password")?.value === "",
      loginFeedback: document.querySelector("#credential-login-feedback")?.textContent?.trim()
    }));

    const checks = {
      playwright_browser_launched: true,
      anonymous_login_only: anonymous.loginVisible && anonymous.applicationHidden,
      anonymous_service_details_absent: anonymous.serviceDetailsEmpty,
      anonymous_runtime_details_absent: anonymous.runtimeDetailsEmpty,
      anonymous_service_probes_absent: protectedServiceRequests.length === 0,
      login_opens_authenticated_shell:
        authenticated.authenticationHidden && authenticated.logoutVisible,
      authenticated_header_is_product_named:
        authenticated.applicationTitle === "NeX-Platform",
      current_account_precedes_logout:
        authenticated.currentUserVisible &&
        authenticated.currentUserAccount === "EMP-S42A-SMOKE",
      employee_operations_hidden: authenticated.employeeOperationsHidden,
      authenticated_views_routed:
        routedViews.length === 5 && new Set(routedViews).size === 5,
      one_view_surface_active: authenticated.visibleProtectedPanelCount === 1,
      desktop_timeline_is_single_row:
        new Set(authenticated.timelineTopOffsets).size === 1 &&
        authenticated.timelinePanelHeight <= 72,
      mobile_has_no_horizontal_overflow:
        !mobile.horizontalOverflow && mobile.chatWidth <= mobile.viewportWidth,
      mobile_timeline_is_single_row:
        new Set(mobile.timelineTopOffsets).size === 1 && mobile.timelinePanelHeight <= 72,
      logout_returns_to_login: loggedOut.applicationHidden,
      logout_clears_protected_surfaces:
        loggedOut.protectedMessageCount === 0 && loggedOut.protectedApprovalCount === 0,
      credential_field_cleared: loggedOut.passwordCleared,
      logout_feedback_visible: loggedOut.loginFeedback === "로그아웃되었습니다."
    };
    return {
      smoke_schema_version: AE_WEB_AUTH_FIRST_SHELL_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        client_mode: "mock",
        live_network_used: false,
        postgresql_used: false
      },
      observations: {
        routed_view_count: routedViews.length,
        protected_service_request_count: protectedServiceRequests.length,
        mobile_viewport_width: mobile.viewportWidth,
        desktop_timeline_height: authenticated.timelinePanelHeight,
        mobile_timeline_height: mobile.timelinePanelHeight
      },
      checks
    };
  } finally {
    if (browser) await browser.close();
    await close(server);
  }
}

export function formatSummary(evidence) {
  if (evidence.status !== "PASS") {
    return "ae_web_auth_first_shell_playwright_smoke=fail reason=checks_failed";
  }
  return (
    "ae_web_auth_first_shell_playwright_smoke=pass " +
    `views=${evidence.observations.routed_view_count} ` +
    `service_probes=${evidence.observations.protected_service_request_count} ` +
    `checks=${Object.keys(evidence.checks).length}`
  );
}

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve(server.address().port);
    });
  });
}

function close(server) {
  if (!server.listening) return Promise.resolve();
  return new Promise((resolve, reject) => {
    server.close(error => (error ? reject(error) : resolve()));
  });
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runAuthenticationFirstShellPlaywrightSmoke();
    output(
      argv.includes("--summary")
        ? formatSummary(evidence)
        : JSON.stringify(evidence, null, 2)
    );
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_auth_first_shell_playwright_smoke=fail " +
        `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
