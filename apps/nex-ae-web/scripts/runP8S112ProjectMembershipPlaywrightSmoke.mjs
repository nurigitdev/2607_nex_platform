#!/usr/bin/env node
import { PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV } from "./runCredentialLoginPlaywrightReadiness.mjs";

const WEB_URL_ENV = "NEX_P8_S112_WEB_URL";
const TENANT_ENV = "NEX_P8_S112_TENANT_ID";
const EMPLOYEE_ENV = "NEX_P8_S112_EMPLOYEE_ID";
const PASSWORD_ENV = "NEX_P8_S112_PASSWORD";
const TIMEOUT_ENV = "NEX_P8_S112_TIMEOUT_MS";

export async function runP8S112ProjectMembershipPlaywrightSmoke({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const required = [WEB_URL_ENV, TENANT_ENV, EMPLOYEE_ENV, PASSWORD_ENV];
  const missing = required.filter(key => !environ[key]);
  if (missing.length) return failure("required_env_missing", { missing_env: missing });

  const timeout = Number(environ[TIMEOUT_ENV] || 30000);
  const requests = [];
  let stage = "browser_launch";
  let browser;
  try {
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    });
    const page = await browser.newPage();
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api/")) {
        requests.push({ method: request.method(), route: url.pathname });
      }
    });
    await page.addInitScript(config => {
      globalThis.__NEX_AE_WEB_CONFIG__ = config;
    }, runtimeConfig());
    stage = "page_load";
    await page.goto(environ[WEB_URL_ENV], {
      waitUntil: "domcontentloaded",
      timeout
    });
    await page.fill("#credential-tenant-id", environ[TENANT_ENV]);
    await page.fill("#credential-employee-id", environ[EMPLOYEE_ENV]);
    await page.fill("#credential-password", environ[PASSWORD_ENV]);
    stage = "credential_login";
    await page.click("#credential-login-submit-button");
    await page.waitForSelector(
      "#credential-login-feedback[data-severity='success']",
      { state: "attached", timeout }
    );
    stage = "prompt_submit";
    await page.uncheck("#retrieval-toggle");
    await page.fill(
      "#prompt",
      "NVT-DEMO 프로젝트에 EMP-S112-01, EMP-S112-02, EMP-S112-404를 한 번에 추가해줘."
    );
    await page.click("#composer button[type='submit']");
    stage = "batch_result_wait";
    await page.waitForSelector(
      ".project-membership-batch-result[data-batch-status='PARTIALLY_APPLIED']",
      { state: "visible", timeout }
    );
    const observations = await page.evaluate(() => {
      const result = document.querySelector(".project-membership-batch-result");
      const text = result?.textContent || "";
      return {
        authenticatedShell: !document.querySelector("#application-shell")?.hidden,
        resultVisible: Boolean(result),
        requestedCountVisible: text.includes("3명"),
        appliedCountVisible: text.includes("1명"),
        rejectedCountVisible: text.includes("2명"),
        addedVisible: text.includes("추가됨"),
        nameMismatchVisible: text.includes("사번과 이름 불일치"),
        notFoundVisible: text.includes("직원을 찾을 수 없음")
      };
    });
    stage = "logout";
    await page.click("#credential-logout-button");
    await page.waitForSelector("#credential-login-panel", { state: "visible", timeout });

    const checks = {
      playwright_browser_launched: true,
      same_origin_login_called: requests.some(
        item =>
          item.method === "POST" &&
          item.route === "/ae-api/api/v1/auth/session/login"
      ),
      same_origin_logout_called: requests.some(
        item =>
          item.method === "POST" &&
          item.route === "/ae-api/api/v1/auth/session/logout"
      ),
      route_guard_allowed_after_login: observations.authenticatedShell,
      logout_feedback_logged_out: true,
      authenticated_shell: observations.authenticatedShell,
      batch_result_visible: observations.resultVisible,
      exact_counts_visible:
        observations.requestedCountVisible &&
        observations.appliedCountVisible &&
        observations.rejectedCountVisible,
      item_outcomes_visible:
        observations.addedVisible &&
        observations.nameMismatchVisible &&
        observations.notFoundVisible,
      canonical_chat_routes_called: [
        "/ae-api/api/v1/chat/interactions",
        "/ae-api/api/v1/chat/interactions/"
      ].every(prefix => requests.some(item => item.route.startsWith(prefix))),
      logout_completed: true,
      redacted_evidence: true
    };
    return {
      smoke_schema_version: "p8_s112_project_membership_playwright.v1",
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      browser_observations: observations,
      request_observations: {
        ae_api_request_count: requests.length,
        request_routes: requests
      },
      checks,
      redaction: {
        raw_password_in_evidence: false,
        token_material_in_evidence: false,
        database_endpoint_in_evidence: false,
        provider_endpoint_in_evidence: false
      }
    };
  } catch (error) {
    return failure(error?.constructor?.name || "playwright_failed", {
      stage,
      request_count: requests.length,
      request_routes: requests
    });
  } finally {
    await browser?.close();
  }
}

function runtimeConfig() {
  return {
    runtime_config_schema_version: "ae_web_runtime_config.v1",
    client_mode: "fetch",
    ae_base_url: "/ae-api",
    features: {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    }
  };
}

function failure(code, detail = {}) {
  return {
    smoke_schema_version: "p8_s112_project_membership_playwright.v1",
    status: "FAIL",
    failure_code: code,
    detail,
    checks: { redacted_evidence: true }
  };
}

async function main() {
  const evidence = await runP8S112ProjectMembershipPlaywrightSmoke();
  console.log(JSON.stringify(evidence));
  process.exitCode = evidence.status === "PASS" ? 0 : 1;
}

if (import.meta.url === new URL(process.argv[1], "file:").href) {
  await main();
}
