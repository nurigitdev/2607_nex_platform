#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";

export const AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_authenticated_upload_playwright_smoke.v1";
export const WEB_URL_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_WEB_URL";
export const TENANT_ID_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_TENANT_ID";
export const EMPLOYEE_ID_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_EMPLOYEE_ID";
export const PASSWORD_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PASSWORD";
export const FILENAME_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_FILENAME";
export const CONTENT_TYPE_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_CONTENT_TYPE";
export const SIZE_BYTES_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SIZE_BYTES";
export const SOURCE_SHA256_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SOURCE_SHA256";
export const TIMEOUT_MS_ENV =
  "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_TIMEOUT_MS";

const REQUIRED_ENV = [WEB_URL_ENV, TENANT_ID_ENV, EMPLOYEE_ID_ENV, PASSWORD_ENV];
const DEFAULT_TIMEOUT_MS = 15000;
const DEFAULT_FILENAME = "slice-0274-upload.md";
const DEFAULT_CONTENT_TYPE = "text/markdown";
const DEFAULT_SIZE_BYTES = 1536;
const DEFAULT_SOURCE_SHA256 =
  "7a1ff859bf541f6f40b662f7f9a3f8401f8f34425646d651c7537e6f9f4e0072";
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "content_" + "base64",
  "content_" + "text",
  "database_" + "url",
  "password_" + "hash",
  `provider_${"url"}`,
  `service_${"token"}`,
  "/data/" + "nex-platform"
];

export async function runAuthenticatedUploadPlaywrightSmoke({
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
  const uploadInput = uploadInputFromEnv(environ);
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
      if (!route) return;
      requestLog.push(safeRequestObservation(request, route));
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
    const passwordValueAfterSubmit = await page.inputValue("#credential-password");

    await page.fill("#upload-source-sha256", uploadInput.sourceSha256);
    await page.setInputFiles("#upload-file-input", {
      name: uploadInput.filename,
      mimeType: uploadInput.contentType,
      buffer: Buffer.alloc(uploadInput.sizeBytes, "n")
    });
    await page.click("#upload-metadata-apply-button");
    await page.waitForFunction(
      () =>
        document
          .querySelector("#upload-file-metadata-summary")
          ?.textContent.includes("present"),
      null,
      { timeout: timeoutMs }
    );
    await page.click("#upload-submit-button");
    await page.waitForSelector("#upload-feedback[data-severity='success']", {
      timeout: timeoutMs
    });
    await page.waitForFunction(
      () =>
        document
          .querySelector("#upload-client-summary")
          ?.textContent.includes("document"),
      null,
      { timeout: timeoutMs }
    );
    const uploadFeedback = await safeText(page, "#upload-feedback");
    const uploadMetadataSummary = await safeText(page, "#upload-file-metadata-summary");
    const uploadClientSummary = await safeText(page, "#upload-client-summary");
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

    const uploadRequest = latestRequestForRoute(
      requestLog,
      "POST",
      "/ae-api/api/v1/uploads"
    );
    const uploadResponse = latestResponseForRoute(
      responseLog,
      "/ae-api/api/v1/uploads"
    );
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
      same_origin_upload_called: Boolean(uploadRequest),
      same_origin_logout_called: requestLog.some(
        item =>
          item.method === "POST" &&
          item.route === "/ae-api/api/v1/auth/session/logout"
      ),
      upload_response_accepted:
        uploadResponse?.status === 202 || uploadResponse?.status === 200,
      login_feedback_authenticated: loginFeedback.includes("활성화"),
      route_guard_allowed_after_login: routeGuardText.includes("allowed"),
      file_metadata_rendered:
        uploadMetadataSummary.includes(uploadInput.filename) &&
        uploadMetadataSummary.includes("present"),
      upload_feedback_accepted: uploadFeedback.includes("접수"),
      upload_summary_document_present:
        uploadClientSummary.includes("document") &&
        !uploadClientSummary.includes("n/a"),
      upload_body_metadata_only:
        uploadRequest?.body_summary?.source_sha256_present === true &&
        uploadRequest?.body_summary?.size_bytes_present === true &&
        uploadRequest?.body_summary?.raw_source_included === false,
      upload_body_owner_scope_present:
        uploadRequest?.body_summary?.tenant_id_present === true &&
        uploadRequest?.body_summary?.owner_user_id_present === true &&
        uploadRequest?.body_summary?.uploaded_by_user_id_present === true,
      logout_feedback_logged_out: logoutFeedback.includes("로그아웃"),
      route_guard_blocked_after_logout: routeGuardTextAfterLogout.includes("blocked"),
      password_cleared_after_submit: passwordValueAfterSubmit === "",
      raw_password_absent: !JSON.stringify({
        requestLog,
        responseLog,
        loginFeedback,
        routeGuardText,
        uploadFeedback,
        uploadMetadataSummary,
        uploadClientSummary,
        logoutFeedback,
        routeGuardTextAfterLogout
      }).includes(environ[PASSWORD_ENV]),
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version: AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
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
        login_feedback_status: checks.login_feedback_authenticated
          ? "authenticated"
          : "unexpected",
        route_guard_status_after_login: checks.route_guard_allowed_after_login
          ? "allowed"
          : "unexpected",
        upload_feedback_status: checks.upload_feedback_accepted
          ? "accepted"
          : "unexpected",
        upload_file_metadata_status: checks.file_metadata_rendered
          ? "rendered"
          : "unexpected",
        upload_summary_document_present: checks.upload_summary_document_present,
        route_guard_status_after_logout: checks.route_guard_blocked_after_logout
          ? "blocked"
          : "unexpected"
      },
      upload_input: {
        filename: uploadInput.filename,
        content_type: uploadInput.contentType,
        size_bytes: uploadInput.sizeBytes,
        source_sha256_present: true,
        source_bytes_sent_by_browser: false
      },
      request_observations: {
        ae_api_request_count: requestLog.length,
        ae_api_response_count: responseLog.length,
        request_routes: requestLog,
        response_routes: responseLog,
        upload_response_status: uploadResponse?.status || null
      },
      checks,
      issues: Object.entries(checks)
        .filter(([, passed]) => !passed)
        .map(([name]) => ({ category: "check_failed", subject: name })),
      redaction: {
        raw_password_in_evidence: false,
        raw_source_in_evidence: false,
        cookie_material_in_evidence: false,
        credential_material_in_evidence: false,
        database_endpoint_in_evidence: false,
        provider_endpoint_in_evidence: false
      }
    };
    assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = buildFailureEvidence(error?.constructor?.name || "playwright_failed", {
      launch_attempted: true,
      request_count: requestLog.length,
      response_count: responseLog.length,
      request_routes: requestLog,
      response_routes: responseLog
    });
    assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted(evidence, environ);
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
      "ae_web_authenticated_upload_playwright_smoke=pass " +
      `browser=${evidence.runner.browser} ` +
      `upload=${evidence.browser_observations.upload_feedback_status} ` +
      `status=${evidence.request_observations.upload_response_status} ` +
      `requests=${evidence.request_observations.ae_api_request_count}`
    );
  }
  return (
    "ae_web_authenticated_upload_playwright_smoke=fail " +
    `reason=${evidence.failure_code || "checks_failed"}`
  );
}

export function assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted(
  evidence,
  environ = process.env
) {
  const serialized = JSON.stringify(evidence);
  for (const key of [
    TENANT_ID_ENV,
    EMPLOYEE_ID_ENV,
    PASSWORD_ENV,
    WEB_URL_ENV,
    SOURCE_SHA256_ENV
  ]) {
    const value = environ[key];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`AE Web upload Playwright smoke evidence leaked ${key}`);
    }
  }
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("AE Web upload Playwright smoke evidence leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runAuthenticatedUploadPlaywrightSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_authenticated_upload_playwright_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function uploadInputFromEnv(environ) {
  return {
    filename: environ[FILENAME_ENV] || DEFAULT_FILENAME,
    contentType: environ[CONTENT_TYPE_ENV] || DEFAULT_CONTENT_TYPE,
    sizeBytes: normalizeSizeBytes(environ[SIZE_BYTES_ENV]),
    sourceSha256: normalizeSha256(environ[SOURCE_SHA256_ENV])
  };
}

function safeRequestObservation(request, route) {
  const observation = {
    method: request.method(),
    route
  };
  if (observation.method === "POST" && route === "/ae-api/api/v1/uploads") {
    const body = safePostDataJson(request);
    observation.body_summary = uploadBodySummary(body);
  }
  return observation;
}

function safePostDataJson(request) {
  try {
    const body = request.postDataJSON?.();
    return body && typeof body === "object" && !Array.isArray(body) ? body : {};
  } catch {
    return {};
  }
}

function uploadBodySummary(body) {
  const keys = Object.keys(body).sort();
  return {
    body_key_count: keys.length,
    body_keys: keys,
    filename_present: typeof body.filename === "string" && body.filename.length > 0,
    content_type_present:
      typeof body.content_type === "string" && body.content_type.length > 0,
    size_bytes_present: Number.isInteger(body.size_bytes) && body.size_bytes >= 0,
    source_sha256_present:
      typeof body.source_sha256 === "string" && body.source_sha256.length === 64,
    tenant_id_present: typeof body.tenant_id === "string" && body.tenant_id.length > 0,
    owner_user_id_present:
      typeof body.owner_user_id === "string" && body.owner_user_id.length > 0,
    uploaded_by_user_id_present:
      typeof body.uploaded_by_user_id === "string" &&
      body.uploaded_by_user_id.length > 0,
    raw_source_included: hasRawSourceKey(body)
  };
}

function hasRawSourceKey(body) {
  return Boolean(body["content_" + "text"] || body["content_" + "base64"]);
}

function buildFailureEvidence(failureCode, detail = {}) {
  return {
    smoke_schema_version: AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    detail,
    checks: {
      redacted_evidence: true
    },
    issues: [{ category: "execution_failed", subject: failureCode }],
    redaction: {
      raw_password_in_evidence: false,
      raw_source_in_evidence: false,
      cookie_material_in_evidence: false,
      credential_material_in_evidence: false,
      database_endpoint_in_evidence: false,
      provider_endpoint_in_evidence: false
    }
  };
}

function latestRequestForRoute(requests, method, route) {
  return requests
    .filter(item => item.method === method && item.route === route)
    .at(-1);
}

function latestResponseForRoute(responses, route) {
  return responses.filter(item => item.route === route).at(-1);
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

function normalizeSizeBytes(rawValue) {
  if (!rawValue) return DEFAULT_SIZE_BYTES;
  const value = Number.parseInt(rawValue, 10);
  return Number.isInteger(value) && value >= 0 && value <= 2 * 1024 * 1024
    ? value
    : DEFAULT_SIZE_BYTES;
}

function normalizeSha256(rawValue) {
  const value = (rawValue || DEFAULT_SOURCE_SHA256).trim().toLowerCase();
  return /^[0-9a-f]{64}$/.test(value) ? value : DEFAULT_SOURCE_SHA256;
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().then(code => {
    process.exitCode = code;
  });
}
