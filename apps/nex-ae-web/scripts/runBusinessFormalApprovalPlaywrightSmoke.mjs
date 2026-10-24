#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import { PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV } from "./runCredentialLoginPlaywrightReadiness.mjs";
import { protectedApprovalRuntimeConfig } from "./runApprovalProtectedPlaywrightSmoke.mjs";
import { captureResponsiveScreenshotEvidence } from "./responsiveScreenshotEvidence.mjs";

export const AE_WEB_BUSINESS_FORMAL_PLAYWRIGHT_SCHEMA_VERSION =
  "ae_web_business_formal_playwright.p8.v1";

const ENV = {
  webUrl: "NEX_P8_S74_WEB_URL",
  tenantId: "NEX_P8_S74_TENANT_ID",
  employeeId: "NEX_P8_S74_EMPLOYEE_ID",
  password: "NEX_P8_S74_PASSWORD",
  formalGateId: "NEX_P8_S74_FORMAL_GATE_ID",
  nslGateId: "NEX_P8_S74_NSL_GATE_ID",
  expectedRole: "NEX_P8_S74_EXPECTED_ROLE",
  expectedTarget: "NEX_P8_S74_EXPECTED_TARGET",
  expectedStage: "NEX_P8_S74_EXPECTED_STAGE",
  expectedStageCount: "NEX_P8_S74_EXPECTED_STAGE_COUNT",
  screenshotDir: "NEX_P8_S91_SCREENSHOT_DIR",
  timeoutMs: "NEX_P8_S74_TIMEOUT_MS"
};

const REQUIRED_ENV = Object.entries(ENV)
  .filter(([key]) => !["screenshotDir", "timeoutMs"].includes(key))
  .map(([, name]) => name);
const DEFAULT_TIMEOUT_MS = 25000;
const FORBIDDEN_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "database_" + "url",
  "password_" + "hash",
  "protected_" + "request",
  "raw_" + "payload",
  "resume_" + "target_ref",
  "semantic_" + "hash",
  "service_" + "token",
  "source_" + "ref",
  "/data/" + "nex-platform"
];

export async function runBusinessFormalApprovalPlaywrightSmoke({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missing = REQUIRED_ENV.filter(name => !environ[name]);
  if (missing.length > 0) {
    return failure("required_env_missing", { missing_count: missing.length });
  }

  const timeout = positiveTimeout(environ[ENV.timeoutMs]);
  let browser = null;
  let page = null;
  let stage = "launch";
  let approvalPostCount = 0;
  const approvalResponseStatuses = [];
  try {
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("request", request => {
      if (
        request.method() === "POST" &&
        new URL(request.url()).pathname.endsWith("/decisions")
      ) {
        approvalPostCount += 1;
      }
    });
    page.on("response", response => {
      if (new URL(response.url()).pathname.startsWith("/ae-api/api/v1/approval-gates")) {
        approvalResponseStatuses.push(response.status());
      }
    });
    await page.addInitScript(config => {
      globalThis.__NEX_AE_WEB_CONFIG__ = config;
    }, protectedApprovalRuntimeConfig());

    stage = "anonymous_boundary";
    await page.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout
    });
    const anonymousApprovalHidden = await page.isHidden("#approval-panel");

    stage = "credential_login";
    await page.fill("#credential-tenant-id", environ[ENV.tenantId]);
    await page.fill("#credential-employee-id", environ[ENV.employeeId]);
    await page.fill("#credential-password", environ[ENV.password]);
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#authenticated-shell:not([hidden])", { timeout });

    stage = "approval_inbox";
    await page.click('[data-shell-view="approvals"]');
    await waitForPhase(page, "READY", timeout);
    const inbox = await page.evaluate(ids => ({
      domains: [...document.querySelectorAll("[data-approval-domain]")].map(
        node => node.getAttribute("data-approval-domain")
      ),
      formalVisible: Boolean(
        document.querySelector(`[data-approval-gate-id="${ids.formal}"]`)
      ),
      nslVisible: Boolean(
        document.querySelector(`[data-approval-gate-id="${ids.nsl}"]`)
      )
    }), {
      formal: environ[ENV.formalGateId],
      nsl: environ[ENV.nslGateId]
    });

    stage = "formal_detail";
    await page.click(
      `[data-approval-gate-id="${environ[ENV.formalGateId]}"]`
    );
    await waitForPhase(page, "DETAIL_READY", timeout);
    const formal = await page.locator("[data-business-formal='true']").evaluate(node => ({
      currentStage: node.getAttribute("data-formal-current-stage"),
      stageCount: node.getAttribute("data-formal-stage-count"),
      requestedRole: node.getAttribute("data-formal-requested-role"),
      eosTarget: node.getAttribute("data-formal-eos-target"),
      terminalState: node.getAttribute("data-formal-terminal-state")
    }));
    const detailText = await page.locator(".approval-detail-surface").innerText();
    const responsiveEvidence = await captureResponsiveScreenshotEvidence({
      page,
      screenshotDir: environ[ENV.screenshotDir],
      prefix: "business-formal-detail"
    });

    stage = "formal_decision";
    await page.fill("#approval-decision-comment", "P8-S74 formal approval smoke");
    await page.click('[data-approval-decision="APPROVE"]');
    await waitForPhase(page, "DECIDED", timeout);
    const terminalState = await page
      .locator("[data-business-formal='true']")
      .getAttribute("data-formal-terminal-state");
    const panelHtml = await page.locator("#approval-panel").innerHTML();

    stage = "logout";
    await page.click("#credential-logout-button");
    await page.waitForSelector("#authentication-shell:not([hidden])", { timeout });

    const checks = {
      playwright_browser_launched: true,
      anonymous_approval_surface_hidden: anonymousApprovalHidden,
      authenticated_domain_separation_preserved:
        inbox.formalVisible &&
        inbox.nslVisible &&
        inbox.domains.includes("BUSINESS_FORMAL") &&
        inbox.domains.includes("NSL_WRITE"),
      eos_provider_visible: detailText.includes("EOS"),
      current_stage_visible: formal.currentStage === environ[ENV.expectedStage],
      stage_count_visible:
        formal.stageCount === environ[ENV.expectedStageCount],
      requested_role_visible:
        formal.requestedRole === environ[ENV.expectedRole],
      eos_target_visible: formal.eosTarget === environ[ENV.expectedTarget],
      pending_state_visible: formal.terminalState === "PENDING",
      formal_approval_committed:
        terminalState === "APPROVED" && approvalPostCount === 1,
      responsive_layout_has_no_horizontal_overflow:
        responsiveEvidence.noHorizontalOverflow,
      requested_screenshots_captured:
        !responsiveEvidence.requested || responsiveEvidence.captureCount === 2,
      logout_returned_to_login: await page.isVisible("#credential-login-panel"),
      protected_payload_absent: FORBIDDEN_FRAGMENTS.every(
        fragment => !panelHtml.toLowerCase().includes(fragment.toLowerCase())
      )
    };
    const evidence = {
      smoke_schema_version: AE_WEB_BUSINESS_FORMAL_PLAYWRIGHT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        client_mode: "fetch",
        postgresql_used: true
      },
      observations: {
        visible_gate_count: inbox.domains.length,
        visible_domain_count: new Set(inbox.domains).size,
        projected_stage_count: Number(formal.stageCount),
        approval_post_count: approvalPostCount,
        responsive_capture_count: responsiveEvidence.captureCount,
        responsive_layouts: responsiveEvidence.layouts
      },
      checks
    };
    assertBusinessFormalEvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const observedPhase = page
      ? await page.locator(".approval-feedback").getAttribute("data-phase").catch(() => null)
      : null;
    const evidence = failure(error?.constructor?.name || "playwright_failed", {
      stage,
      approval_post_count: approvalPostCount,
      approval_response_statuses: approvalResponseStatuses,
      observed_phase: observedPhase
    });
    assertBusinessFormalEvidenceRedacted(evidence, environ);
    return evidence;
  } finally {
    if (browser) await browser.close();
  }
}

export function formatBusinessFormalSummary(evidence) {
  if (evidence.status !== "PASS") {
    return `p8_s74_business_formal_playwright=fail reason=${evidence.failure_code || "checks_failed"}`;
  }
  return (
    "p8_s74_business_formal_playwright=pass " +
    `gates=${evidence.observations.visible_gate_count} ` +
    `domains=${evidence.observations.visible_domain_count} ` +
    `checks=${Object.keys(evidence.checks).length}`
  );
}

export function assertBusinessFormalEvidenceRedacted(evidence, environ = process.env) {
  const serialized = JSON.stringify(evidence);
  for (const name of REQUIRED_ENV) {
    const value = environ[name];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`P8-S74 evidence leaked ${name}`);
    }
  }
  const lowered = serialized.toLowerCase();
  for (const fragment of FORBIDDEN_FRAGMENTS) {
    if (lowered.includes(fragment.toLowerCase())) {
      throw new Error("P8-S74 evidence leaked protected material");
    }
  }
}

async function waitForPhase(page, phase, timeout) {
  await page.waitForSelector(`.approval-feedback[data-phase="${phase}"]`, {
    timeout
  });
}

function positiveTimeout(value) {
  const parsed = Number(value || DEFAULT_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

function failure(failureCode, observations = {}) {
  return {
    smoke_schema_version: AE_WEB_BUSINESS_FORMAL_PLAYWRIGHT_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    observations,
    checks: {}
  };
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const evidence = await runBusinessFormalApprovalPlaywrightSmoke();
  output(
    argv.includes("--summary")
      ? formatBusinessFormalSummary(evidence)
      : JSON.stringify(evidence, null, 2)
  );
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
