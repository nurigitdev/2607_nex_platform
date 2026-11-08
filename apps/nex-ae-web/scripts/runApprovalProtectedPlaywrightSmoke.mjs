#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";
import { captureResponsiveScreenshotEvidence } from "./responsiveScreenshotEvidence.mjs";

export const AE_WEB_APPROVAL_PROTECTED_PLAYWRIGHT_SCHEMA_VERSION =
  "ae_web_approval_protected_playwright.p8.v1";

const ENV = {
  webUrl: "NEX_P8_S43_WEB_URL",
  tenantId: "NEX_P8_S43_TENANT_ID",
  employeeId: "NEX_P8_S43_EMPLOYEE_ID",
  password: "NEX_P8_S43_PASSWORD",
  approveGateId: "NEX_P8_S43_APPROVE_GATE_ID",
  rejectGateId: "NEX_P8_S43_REJECT_GATE_ID",
  hiddenGateId: "NEX_P8_S43_HIDDEN_GATE_ID",
  expiredGateId: "NEX_P8_S43_EXPIRED_GATE_ID",
  screenshotDir: "NEX_P8_S91_SCREENSHOT_DIR",
  timeoutMs: "NEX_P8_S43_TIMEOUT_MS"
};

const REQUIRED_ENV = Object.entries(ENV)
  .filter(([key]) => !["screenshotDir", "timeoutMs"].includes(key))
  .map(([, name]) => name);
const DEFAULT_TIMEOUT_MS = 25000;
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "database_" + "url",
  "password_" + "hash",
  "protected_" + "request",
  "resume_" + "target_ref",
  "semantic_" + "hash",
  "service_" + "token",
  "source_" + "ref",
  "/data/" + "nex-platform"
];

export function protectedApprovalRuntimeConfig() {
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

export async function runApprovalProtectedPlaywrightSmoke({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missingEnv = REQUIRED_ENV.filter(name => !environ[name]);
  if (missingEnv.length > 0) {
    return failure("required_env_missing", { missing_count: missingEnv.length });
  }

  const timeout = positiveTimeout(environ[ENV.timeoutMs]);
  const requestLog = [];
  const responseLog = [];
  let decisionRequest = null;
  let browser = null;
  let stage = "launch";
  try {
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("request", request => {
      const route = approvalRoute(request.url());
      if (!route) return;
      requestLog.push({ method: request.method(), route });
      if (request.method() === "POST" && route.endsWith("/decisions")) {
        decisionRequest = {
          route,
          payload: request.postDataJSON()
        };
      }
    });
    page.on("response", response => {
      const route = approvalRoute(response.url());
      if (route) responseLog.push({ status: response.status(), route });
    });
    await page.addInitScript(config => {
      globalThis.__NEX_AE_WEB_CONFIG__ = config;
    }, protectedApprovalRuntimeConfig());
    stage = "open_login";
    await page.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout
    });
    const anonymousApprovalPanelHidden = await page.isHidden("#approval-panel");

    stage = "credential_login";
    await page.fill("#credential-tenant-id", environ[ENV.tenantId]);
    await page.fill("#credential-employee-id", environ[ENV.employeeId]);
    await page.fill("#credential-password", environ[ENV.password]);
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#authenticated-shell:not([hidden])", { timeout });
    stage = "load_inbox";
    await page.click('[data-shell-view="approvals"]');
    await waitForPhase(page, "READY", timeout);

    const inbox = await page.evaluate(() => ({
      gateCount: document.querySelectorAll("[data-approval-gate-id]").length,
      domains: [...document.querySelectorAll("[data-approval-domain]")].map(
        node => node.getAttribute("data-approval-domain")
      )
    }));
    const responsiveEvidence = await captureResponsiveScreenshotEvidence({
      page,
      screenshotDir: environ[ENV.screenshotDir],
      prefix: "approval-inbox"
    });

    stage = "approve_detail";
    await selectGate(page, environ[ENV.approveGateId], timeout);
    await page.fill("#approval-decision-comment", "P8-S43 protected approval");
    stage = "approve_decision";
    await page.click('[data-approval-decision="APPROVE"]');
    await waitForPhase(page, "DECIDED", timeout);
    const approveFeedback = await safeText(page, ".approval-feedback");

    if (!decisionRequest) throw new Error("ApprovalDecisionRequestMissing");
    stage = "approve_replay";
    const replayStatus = await page.evaluate(async request => {
      const response = await fetch(request.route, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request.payload)
      });
      return response.status;
    }, decisionRequest);

    stage = "reject_detail";
    await selectGate(page, environ[ENV.rejectGateId], timeout);
    await page.fill("#approval-decision-comment", "P8-S43 protected rejection");
    stage = "reject_decision";
    await page.click('[data-approval-decision="REJECT"]');
    await waitForPhase(page, "DECIDED", timeout);
    const rejectFeedback = await safeText(page, ".approval-feedback");

    stage = "denied_detail_reads";
    const deniedStatuses = await page.evaluate(async ids => {
      const read = async id =>
        (await fetch(`/ae-api/api/v1/approval-gates/${encodeURIComponent(id)}`)).status;
      return {
        hidden: await read(ids.hidden),
        expired: await read(ids.expired)
      };
    }, {
      hidden: environ[ENV.hiddenGateId],
      expired: environ[ENV.expiredGateId]
    });

    const panelHtml = await page.locator("#approval-panel").innerHTML();
    stage = "logout";
    await page.click("#credential-logout-button");
    await page.waitForSelector("#authentication-shell:not([hidden])", { timeout });

    const checks = {
      playwright_browser_launched: true,
      anonymous_approval_surface_hidden: anonymousApprovalPanelHidden,
      authenticated_pending_inbox_rendered: inbox.gateCount === 2,
      approval_domains_preserved:
        inbox.domains.includes("NSL_WRITE") &&
        inbox.domains.includes("BUSINESS_FORMAL"),
      approve_committed: approveFeedback.includes("승인"),
      exact_approve_replay_idempotent: replayStatus === 200,
      reject_committed: rejectFeedback.includes("반려"),
      target_mismatch_hidden: deniedStatuses.hidden === 404,
      expired_gate_hidden: deniedStatuses.expired === 404,
      authenticated_approval_http_observed:
        requestLog.some(item => item.method === "GET") &&
        requestLog.filter(item => item.method === "POST").length >= 3,
      responsive_layout_has_no_horizontal_overflow:
        responsiveEvidence.noHorizontalOverflow,
      requested_screenshots_captured:
        !responsiveEvidence.requested || responsiveEvidence.captureCount === 2,
      logout_returned_to_login: await page.isVisible("#credential-login-panel"),
      protected_payload_absent: FORBIDDEN_EVIDENCE_FRAGMENTS.every(
        fragment => !panelHtml.toLowerCase().includes(fragment.toLowerCase())
      )
    };
    const evidence = {
      smoke_schema_version: AE_WEB_APPROVAL_PROTECTED_PLAYWRIGHT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        client_mode: "fetch",
        postgresql_used: true
      },
      observations: {
        visible_gate_count: inbox.gateCount,
        visible_domain_count: new Set(inbox.domains).size,
        approval_request_count: requestLog.length,
        approval_response_count: responseLog.length,
        replay_status: replayStatus,
        hidden_status: deniedStatuses.hidden,
        expired_status: deniedStatuses.expired,
        responsive_capture_count: responsiveEvidence.captureCount,
        responsive_layouts: responsiveEvidence.layouts
      },
      checks
    };
    assertProtectedApprovalEvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = failure(error?.constructor?.name || "playwright_failed", {
      stage,
      request_count: requestLog.length,
      response_count: responseLog.length
    });
    assertProtectedApprovalEvidenceRedacted(evidence, environ);
    return evidence;
  } finally {
    if (browser) await browser.close();
  }
}

export function formatProtectedApprovalSummary(evidence) {
  if (evidence.status !== "PASS") {
    return `p8_s43_approval_playwright=fail reason=${evidence.failure_code || "checks_failed"}`;
  }
  return (
    "p8_s43_approval_playwright=pass " +
    `gates=${evidence.observations.visible_gate_count} ` +
    `domains=${evidence.observations.visible_domain_count} ` +
    `checks=${Object.keys(evidence.checks).length}`
  );
}

export function assertProtectedApprovalEvidenceRedacted(
  evidence,
  environ = process.env
) {
  const serialized = JSON.stringify(evidence);
  for (const name of REQUIRED_ENV) {
    const value = environ[name];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`P8-S43 evidence leaked ${name}`);
    }
  }
  const lowered = serialized.toLowerCase();
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (lowered.includes(fragment.toLowerCase())) {
      throw new Error("P8-S43 evidence leaked protected material");
    }
  }
}

async function selectGate(page, gateId, timeout) {
  await page.click(`[data-approval-gate-id="${gateId}"]`);
  await waitForPhase(page, "DETAIL_READY", timeout);
}

async function waitForPhase(page, phase, timeout) {
  await page.waitForSelector(`.approval-feedback[data-phase="${phase}"]`, {
    timeout
  });
}

async function safeText(page, selector) {
  return (await page.locator(selector).textContent())?.trim() || "";
}

function approvalRoute(url) {
  const parsed = new URL(url);
  return parsed.pathname.startsWith("/ae-api/api/v1/approval-gates")
    ? `${parsed.pathname}${parsed.search}`
    : null;
}

function positiveTimeout(value) {
  const parsed = Number(value || DEFAULT_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

function failure(failureCode, observations = {}) {
  return {
    smoke_schema_version: AE_WEB_APPROVAL_PROTECTED_PLAYWRIGHT_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    observations,
    checks: {}
  };
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const evidence = await runApprovalProtectedPlaywrightSmoke();
  output(
    argv.includes("--summary")
      ? formatProtectedApprovalSummary(evidence)
      : JSON.stringify(evidence, null, 2)
  );
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
