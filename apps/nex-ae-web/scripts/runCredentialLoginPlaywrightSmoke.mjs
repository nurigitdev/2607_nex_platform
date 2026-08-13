#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";

export const AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_credential_login_playwright_smoke.v1";
export const WEB_URL_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_WEB_URL";
export const TENANT_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TENANT_ID";
export const EMPLOYEE_ID_ENV =
  "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_EMPLOYEE_ID";
export const PASSWORD_ENV =
  "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD";
export const TIMEOUT_MS_ENV =
  "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TIMEOUT_MS";

const REQUIRED_ENV = [WEB_URL_ENV, TENANT_ID_ENV, EMPLOYEE_ID_ENV, PASSWORD_ENV];
const DEFAULT_TIMEOUT_MS = 15000;
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "database_" + "url",
  "password_" + "hash",
  `provider_${"url"}`,
  `service_${"token"}`,
  "/data/" + "nex-platform"
];

export async function runCredentialLoginPlaywrightSmoke({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missingEnv = REQUIRED_ENV.filter(name => !environ[name]);
  if (missingEnv.length > 0) {
    return buildFailureEvidence("required_env_missing", {
      missing_env: missingEnv,
      launch_attempted: false
    });
  }

  const timeoutMs = normalizeTimeout(environ[TIMEOUT_MS_ENV]);
  const requestLog = [];
  const responseLog = [];
  let browser = null;
  try {
    const playwright = await importPlaywright();
    const launchOptions = {
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    };
    browser = await playwright.chromium.launch(launchOptions);
    const page = await browser.newPage();
    page.on("request", request => {
      const route = sameOriginAeApiRoute(request.url());
      if (route) {
        requestLog.push({ method: request.method(), route });
      }
    });
    page.on("response", response => {
      const route = sameOriginAeApiRoute(response.url());
      if (route) {
        responseLog.push({ status: response.status(), route });
      }
    });
    await page.addInitScript(config => {
      globalThis.__NEX_AE_WEB_CONFIG__ = config;
    }, safeFetchRuntimeConfig());
    await page.goto(environ[WEB_URL_ENV], {
      waitUntil: "domcontentloaded",
      timeout: timeoutMs
    });
    await page.fill("#credential-tenant-id", environ[TENANT_ID_ENV]);
    await page.fill("#credential-employee-id", environ[EMPLOYEE_ID_ENV]);
    await page.fill("#credential-password", environ[PASSWORD_ENV]);
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#credential-login-feedback[data-severity='success']", {
      timeout: timeoutMs
    });
    await page.waitForFunction(
      () =>
        document
          .querySelector("#session-route-guard-summary")
          ?.textContent.includes("allowed"),
      null,
      { timeout: timeoutMs }
    );
    const loginFeedback = await safeText(page, "#credential-login-feedback");
    const routeGuardText = await safeText(page, "#session-route-guard-summary");
    const loginSummaryText = await safeText(page, "#credential-login-summary");
    const passwordValueAfterSubmit = await page.inputValue("#credential-password");
    const logoutVisible = await page.isVisible("#credential-logout-button");
    await page.click("#credential-logout-button");
    await page.waitForFunction(
      () =>
        document
          .querySelector("#credential-login-feedback")
          ?.textContent.includes("로그아웃"),
      null,
      { timeout: timeoutMs }
    );
    const logoutFeedback = await safeText(page, "#credential-login-feedback");
    const routeGuardTextAfterLogout = await safeText(
      page,
      "#session-route-guard-summary"
    );
    await browser.close();
    browser = null;

    const checks = {
      playwright_browser_launched: true,
      runtime_config_fetch_mode: true,
      same_origin_session_read_called: requestLog.some(
        item => item.method === "GET" && item.route === "/ae-api/api/v1/auth/session"
      ),
      same_origin_login_called: requestLog.some(
        item =>
          item.method === "POST" &&
          item.route === "/ae-api/api/v1/auth/session/login"
      ),
      same_origin_logout_called: requestLog.some(
        item =>
          item.method === "POST" &&
          item.route === "/ae-api/api/v1/auth/session/logout"
      ),
      login_feedback_authenticated: loginFeedback.includes("활성화"),
      route_guard_allowed_after_login: routeGuardText.includes("allowed"),
      logout_button_visible_after_login: logoutVisible,
      password_cleared_after_submit: passwordValueAfterSubmit === "",
      logout_feedback_logged_out: logoutFeedback.includes("로그아웃"),
      route_guard_blocked_after_logout: routeGuardTextAfterLogout.includes("blocked"),
      raw_password_absent: !JSON.stringify({
        requestLog,
        responseLog,
        loginFeedback,
        routeGuardText,
        loginSummaryText,
        logoutFeedback,
        routeGuardTextAfterLogout
      }).includes(environ[PASSWORD_ENV]),
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version: AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        system_chromium_executable_configured: Boolean(
          environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ),
        web_url_configured: true
      },
      browser_runtime_config: safeFetchRuntimeConfig(),
      browser_observations: {
        credential_form_present: true,
        login_feedback_status: checks.login_feedback_authenticated
          ? "authenticated"
          : "unexpected",
        route_guard_status_after_login: checks.route_guard_allowed_after_login
          ? "allowed"
          : "unexpected",
        logout_feedback_status: checks.logout_feedback_logged_out
          ? "logged_out"
          : "unexpected",
        route_guard_status_after_logout: checks.route_guard_blocked_after_logout
          ? "blocked"
          : "unexpected",
        login_summary_employee_present: loginSummaryText.includes("present")
      },
      request_observations: {
        ae_api_request_count: requestLog.length,
        ae_api_response_count: responseLog.length,
        request_routes: requestLog,
        response_routes: responseLog
      },
      checks,
      issues: Object.entries(checks)
        .filter(([, passed]) => !passed)
        .map(([name]) => ({ category: "check_failed", subject: name })),
      redaction: {
        raw_password_in_evidence: false,
        cookie_material_in_evidence: false,
        token_material_in_evidence: false,
        database_endpoint_in_evidence: false,
        provider_endpoint_in_evidence: false
      }
    };
    assertPlaywrightSmokeEvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = buildFailureEvidence(error?.constructor?.name || "playwright_failed", {
      launch_attempted: true,
      request_count: requestLog.length,
      response_count: responseLog.length,
      request_routes: requestLog,
      response_routes: responseLog
    });
    assertPlaywrightSmokeEvidenceRedacted(evidence, environ);
    return evidence;
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

export function safeFetchRuntimeConfig() {
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

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_credential_login_playwright_smoke=pass " +
      `browser=${evidence.runner.browser} ` +
      `route_guard=${evidence.browser_observations.route_guard_status_after_login} ` +
      `requests=${evidence.request_observations.ae_api_request_count}`
    );
  }
  return (
    "ae_web_credential_login_playwright_smoke=fail " +
    `reason=${evidence.failure_code || "checks_failed"}`
  );
}

export function assertPlaywrightSmokeEvidenceRedacted(evidence, environ = process.env) {
  const serialized = JSON.stringify(evidence);
  for (const key of [TENANT_ID_ENV, EMPLOYEE_ID_ENV, PASSWORD_ENV, WEB_URL_ENV]) {
    const value = environ[key];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`AE Web Playwright smoke evidence leaked ${key}`);
    }
  }
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("AE Web Playwright smoke evidence leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runCredentialLoginPlaywrightSmoke();
    output(
      summary
        ? formatSummary(evidence)
        : JSON.stringify(evidence, null, 2)
    );
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_credential_login_playwright_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function buildFailureEvidence(failureCode, detail = {}) {
  return {
    smoke_schema_version: AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    detail,
    checks: {
      redacted_evidence: true
    },
    issues: [{ category: "execution_failed", subject: failureCode }],
    redaction: {
      raw_password_in_evidence: false,
      cookie_material_in_evidence: false,
      token_material_in_evidence: false,
      database_endpoint_in_evidence: false,
      provider_endpoint_in_evidence: false
    }
  };
}

function sameOriginAeApiRoute(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.pathname === "/ae-api" || parsed.pathname.startsWith("/ae-api/")) {
      return parsed.pathname;
    }
  } catch {
    if (rawUrl.startsWith("/ae-api")) {
      return rawUrl.split("?")[0];
    }
  }
  return null;
}

async function safeText(page, selector) {
  return (await page.textContent(selector)) || "";
}

function normalizeTimeout(rawValue) {
  if (!rawValue) return DEFAULT_TIMEOUT_MS;
  const value = Number.parseInt(rawValue, 10);
  return Number.isInteger(value) && value >= 1000 && value <= 120000
    ? value
    : DEFAULT_TIMEOUT_MS;
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().then(code => {
    process.exitCode = code;
  });
}
