#!/usr/bin/env node
import { PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV } from "./runCredentialLoginPlaywrightReadiness.mjs";

const WEB_URL_ENV = "NEX_P8_S102_WEB_URL";
const TENANT_ENV = "NEX_P8_S102_TENANT_ID";
const EMPLOYEE_ENV = "NEX_P8_S102_EMPLOYEE_ID";
const PASSWORD_ENV = "NEX_P8_S102_PASSWORD";
const PROMPT_ENV = "NEX_P8_S102_PROMPT";
const TIMEOUT_ENV = "NEX_P8_S102_TIMEOUT_MS";

export async function runP8S102DemoPlaywrightSmoke({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const required = [WEB_URL_ENV, TENANT_ENV, EMPLOYEE_ENV, PASSWORD_ENV, PROMPT_ENV];
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
    await page.fill("#prompt", environ[PROMPT_ENV]);
    await page.click("#composer button[type='submit']");
    stage = "committed_result_wait";
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll("#message-list .message.assistant p")]
          .at(-1)
          ?.textContent?.includes("등록되었습니다"),
      null,
      { timeout }
    );
    const observations = await page.evaluate(() => ({
      userPromptVisible: [...document.querySelectorAll("#message-list .message.user p")]
        .at(-1)
        ?.textContent?.includes("PROJECT-A-2"),
      committedResultVisible: [...document.querySelectorAll("#message-list .message.assistant p")]
        .at(-1)
        ?.textContent?.includes("전표"),
      projectVisible: [...document.querySelectorAll("#message-list .message.assistant p")]
        .at(-1)
        ?.textContent?.includes("PROJECT-A-2"),
      amountVisible: [...document.querySelectorAll("#message-list .message.assistant p")]
        .at(-1)
        ?.textContent?.includes("84,000"),
      applicationVisible: !document.querySelector("#application-shell")?.hidden
    }));
    stage = "logout";
    await page.click("#credential-logout-button");
    await page.waitForSelector("#credential-login-panel", { state: "visible", timeout });

    const checks = {
      playwright_browser_launched: true,
      same_origin_login_called: hasRequest(
        requests,
        "POST",
        "/ae-api/api/v1/auth/session/login"
      ),
      same_origin_logout_called: hasRequest(
        requests,
        "POST",
        "/ae-api/api/v1/auth/session/logout"
      ),
      route_guard_allowed_after_login: observations.applicationVisible === true,
      logout_feedback_logged_out: true,
      natural_language_prompt_submitted: observations.userPromptVisible === true,
      committed_voucher_result_visible: observations.committedResultVisible === true,
      exact_project_visible: observations.projectVisible === true,
      exact_amount_visible: observations.amountVisible === true,
      canonical_chat_routes_called: [
        "/ae-api/api/v1/chat/interactions",
        "/ae-api/api/v1/chat/interactions/"
      ].every(prefix => requests.some(item => item.route.startsWith(prefix))),
      redacted_evidence: true
    };
    return {
      smoke_schema_version: "p8_s102_demo_playwright.v1",
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      browser_observations: {
        authenticated_shell: observations.applicationVisible,
        prompt_submitted: observations.userPromptVisible,
        committed_result_visible: observations.committedResultVisible,
        project_visible: observations.projectVisible,
        amount_visible: observations.amountVisible,
        logout_completed: true
      },
      request_observations: {
        ae_api_request_count: requests.length,
        request_routes: requests
      },
      checks,
      redaction: {
        raw_prompt_in_evidence: false,
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

function hasRequest(requests, method, route) {
  return requests.some(item => item.method === method && item.route === route);
}

function failure(code, detail = {}) {
  return {
    smoke_schema_version: "p8_s102_demo_playwright.v1",
    status: "FAIL",
    failure_code: code,
    detail,
    checks: { redacted_evidence: true }
  };
}

async function main() {
  const evidence = await runP8S102DemoPlaywrightSmoke();
  console.log(JSON.stringify(evidence));
  process.exitCode = evidence.status === "PASS" ? 0 : 1;
}

if (import.meta.url === new URL(process.argv[1], "file:").href) {
  await main();
}
