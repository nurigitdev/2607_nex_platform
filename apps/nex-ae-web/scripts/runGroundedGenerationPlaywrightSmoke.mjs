#!/usr/bin/env node
import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";

export const AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_grounded_generation_playwright_smoke.v1";

export const ENV = {
  webUrl: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_WEB_URL",
  tenantId: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_TENANT_ID",
  ownerUserId: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_OWNER_USER_ID",
  employeeId: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_EMPLOYEE_ID",
  password: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_PASSWORD",
  documentId: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_DOCUMENT_ID",
  workspaceId: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_WORKSPACE_ID",
  chatDocumentId:
    "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_CHAT_DOCUMENT_ID",
  timeoutMs: "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_TIMEOUT_MS"
};

const REQUIRED_ENV = [
  ENV.webUrl,
  ENV.tenantId,
  ENV.ownerUserId,
  ENV.employeeId,
  ENV.password,
  ENV.documentId,
  ENV.workspaceId,
  ENV.chatDocumentId
];
const DEFAULT_TIMEOUT_MS = 120000;
const FORBIDDEN_FRAGMENTS = [
  "api_" + "key",
  "database_" + "url",
  "provider_" + "url",
  "service_" + "token",
  "access_" + "token",
  "/data/" + "nex-platform"
];

export async function runGroundedGenerationPlaywrightSmoke({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const missingEnv = REQUIRED_ENV.filter(name => !environ[name]);
  if (missingEnv.length > 0) {
    return failureEvidence("required_env_missing", {
      missing_env: missingEnv,
      launch_attempted: false
    });
  }

  const timeoutMs = normalizeTimeout(environ[ENV.timeoutMs]);
  const requestLog = [];
  const responseLog = [];
  const pageErrorNames = [];
  let submittedInteractionRef = null;
  let browser = null;
  let page = null;
  try {
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    });
    page = await browser.newPage();
    page.on("pageerror", error => {
      pageErrorNames.push(error?.name || "Error");
    });
    page.on("request", request => {
      const route = sameOriginAeApiRoute(request.url());
      if (!route) return;
      const headers = request.headers();
      const normalizedRoute = normalizeInteractionRoute(route);
      if (
        request.method() === "POST" &&
        normalizedRoute === "/ae-api/api/v1/chat/interactions"
      ) {
        try {
          submittedInteractionRef = request.postDataJSON()?.interaction_id || null;
        } catch {
          submittedInteractionRef = null;
        }
      }
      requestLog.push({
        method: request.method(),
        route: normalizedRoute,
        browser_secret_header_present: Boolean(
          headers.authorization || headers["x-service-id"] || headers["x-api-key"]
        )
      });
    });
    page.on("response", async response => {
      const route = sameOriginAeApiRoute(response.url());
      if (route) {
        let errorCode = null;
        let errorDetail = null;
        let progressState = null;
        const normalizedRoute = normalizeInteractionRoute(route);
        if (response.status() >= 400) {
          try {
            const body = await response.json();
            errorCode = typeof body?.error_code === "string"
              ? body.error_code
              : null;
            errorDetail = safeErrorDetail(body?.detail);
          } catch {
            errorCode = null;
          }
        } else if (normalizedRoute.endsWith("/progress")) {
          try {
            const body = await response.json();
            progressState = {
              lifecycle_status: body?.lifecycle_status || null,
              cx_job_status: body?.cx_job_status || null,
              handoff_status: body?.handoff_status || null,
              next_action: body?.next_action || null
            };
          } catch {
            progressState = null;
          }
        }
        responseLog.push({
          status: response.status(),
          route: normalizedRoute,
          ...(errorCode ? { error_code: errorCode } : {}),
          ...(errorDetail ? { error_detail: errorDetail } : {}),
          ...(progressState ? { progress_state: progressState } : {})
        });
      }
    });
    await page.addInitScript(
      ({ runtimeConfig, documentBootstrap, workspaceBootstrap }) => {
        globalThis.__NEX_AE_WEB_CONFIG__ = runtimeConfig;
        globalThis.__NEX_AE_WEB_DOCUMENT_BOOTSTRAP__ = documentBootstrap;
        globalThis.__NEX_AE_WEB_WORKSPACE_BOOTSTRAP__ = workspaceBootstrap;
      },
      {
        runtimeConfig: safeFetchRuntimeConfig(),
        documentBootstrap: safeDocumentBootstrap(environ),
        workspaceBootstrap: safeWorkspaceBootstrap(environ)
      }
    );
    await page.goto(environ[ENV.webUrl], {
      waitUntil: "domcontentloaded",
      timeout: timeoutMs
    });
    await page.fill("#credential-tenant-id", environ[ENV.tenantId]);
    await page.fill("#credential-employee-id", environ[ENV.employeeId]);
    await page.fill("#credential-password", environ[ENV.password]);
    await page.click("#credential-login-submit-button");
    await page.waitForSelector(
      "#credential-login-feedback[data-severity='success']",
      { timeout: timeoutMs }
    );
    await page.waitForFunction(
      () => document.querySelector("#session-route-guard-summary")
        ?.textContent.includes("allowed"),
      null,
      { timeout: timeoutMs }
    );
    await page.fill(
      "#prompt",
      "문서의 확인 문구를 근거로 답하고 반드시 [1] 인용을 포함해줘."
    );
    await page.click("#composer button[type='submit']");
    await page.waitForFunction(
      () => document.querySelector("#runtime-diagnostics-summary")
        ?.textContent.includes("VERIFIED_RESPONSE"),
      null,
      { timeout: timeoutMs }
    );

    const browserResult = await page.evaluate(() => {
      const assistantMessages = [
        ...document.querySelectorAll("#message-list .message.assistant")
      ];
      const latest = assistantMessages.at(-1);
      const diagnostics = document.querySelector("#runtime-diagnostics-summary")
        ?.textContent || "";
      return {
        interaction_id: latest?.dataset.interactionId || null,
        assistant_message_count: assistantMessages.length,
        latest_response_present: Boolean(latest?.querySelector("p")?.textContent?.trim()),
        verified_response_visible: diagnostics.includes("VERIFIED_RESPONSE"),
        present_response_action_visible: diagnostics.includes("PRESENT_RESPONSE"),
        fetch_runtime_visible: diagnostics.includes("fetch"),
        quality_surface_visible: Boolean(
          latest?.querySelector(".grounded-response-quality-chip")
        ),
        timeline_event_count: document.querySelectorAll("#progress-timeline li").length,
        cancel_disabled: document.querySelector("#generation-cancel-button")?.disabled,
        retry_disabled: document.querySelector("#generation-retry-button")?.disabled,
        password_cleared: document.querySelector("#credential-password")?.value === ""
      };
    });
    await browser.close();
    browser = null;

    const routeChecks = groundedGenerationRouteChecks(requestLog);
    const checks = {
      playwright_browser_launched: true,
      authenticated_fetch_runtime: browserResult.fetch_runtime_visible === true,
      document_bootstrap_applied: true,
      interaction_admission_called: routeChecks.interaction_admission_called,
      progress_called: routeChecks.progress_called,
      refresh_called: routeChecks.refresh_called,
      generated_response_called: routeChecks.generated_response_called,
      citation_quality_called: routeChecks.citation_quality_called,
      verified_response_visible: browserResult.verified_response_visible === true,
      present_response_action_visible:
        browserResult.present_response_action_visible === true,
      generated_response_content_present:
        browserResult.latest_response_present === true,
      grounded_quality_visible: browserResult.quality_surface_visible === true,
      lifecycle_timeline_present: browserResult.timeline_event_count >= 4,
      terminal_controls_fail_closed:
        browserResult.cancel_disabled === true &&
        browserResult.retry_disabled === true,
      password_cleared_after_login: browserResult.password_cleared === true,
      browser_secret_headers_absent: requestLog.every(
        item => item.browser_secret_header_present === false
      ),
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version:
        AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        same_origin_route_prefix: "/ae-api"
      },
      browser_observations: {
        assistant_message_count: browserResult.assistant_message_count,
        interaction_id_present: Boolean(browserResult.interaction_id),
        timeline_event_count: browserResult.timeline_event_count,
        display_mode: browserResult.verified_response_visible
          ? "VERIFIED_RESPONSE"
          : "UNEXPECTED",
        next_action: browserResult.present_response_action_visible
          ? "PRESENT_RESPONSE"
          : "UNEXPECTED"
      },
      request_observations: {
        ae_api_request_count: requestLog.length,
        ae_api_response_count: responseLog.length,
        request_routes: requestLog,
        response_routes: responseLog
      },
      interaction_ref: browserResult.interaction_id,
      checks,
      issues: Object.entries(checks)
        .filter(([, passed]) => !passed)
        .map(([name]) => ({ category: "check_failed", subject: name })),
      redaction: {
        prompt_content_included: false,
        generated_content_included: false,
        source_content_included: false,
        credential_material_included: false,
        server_material_included: false
      }
    };
    assertEvidenceRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const failureStage = page
      ? await collectFailureStage(page)
      : { page_created: false };
    const evidence = failureEvidence(error?.constructor?.name || "playwright_failed", {
      launch_attempted: true,
      request_count: requestLog.length,
      response_count: responseLog.length,
      request_routes: requestLog,
      response_routes: responseLog,
      page_error_names: pageErrorNames,
      failure_stage: failureStage
    });
    evidence.interaction_ref = submittedInteractionRef;
    assertEvidenceRedacted(evidence, environ);
    return evidence;
  } finally {
    if (browser) await browser.close();
  }
}

export function safeErrorDetail(value) {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    value.length > 160 ||
    !/^[A-Za-z0-9 ._-]+$/.test(value) ||
    /[0-9a-f]{8}-[0-9a-f-]{27,}/i.test(value)
  ) {
    return null;
  }
  return value;
}

async function collectFailureStage(page) {
  try {
    return await page.evaluate(() => {
      const diagnostics = document.querySelector("#runtime-diagnostics-summary")
        ?.textContent || "";
      return {
        page_created: true,
        credential_form_present: Boolean(
          document.querySelector("#credential-login-form")
        ),
        login_feedback_severity:
          document.querySelector("#credential-login-feedback")?.dataset.severity ||
          "missing",
        route_guard_allowed:
          document.querySelector("#session-route-guard-summary")
            ?.textContent.includes("allowed") === true,
        verified_response_visible: diagnostics.includes("VERIFIED_RESPONSE"),
        present_response_action_visible: diagnostics.includes("PRESENT_RESPONSE")
      };
    });
  } catch {
    return { page_created: true, inspection_failed: true };
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

export function safeDocumentBootstrap(environ) {
  return {
    schema_version: "ae_web_document_bootstrap.v1",
    documents: [
      {
        document_id: environ[ENV.documentId],
        filename: "s109-grounded-generation.md",
        tenant_id: environ[ENV.tenantId],
        owner_user_id: environ[ENV.ownerUserId],
        processing_status: "COMPLETED",
        extraction_status: "COMPLETED",
        summary_status: "READY",
        confidence_bucket: "HIGH",
        best_score: 0.9
      }
    ]
  };
}

export function safeWorkspaceBootstrap(environ) {
  return {
    schema_version: "ae_web_workspace_bootstrap.v1",
    workspace_id: environ[ENV.workspaceId],
    chat_document_id: environ[ENV.chatDocumentId]
  };
}

export function groundedGenerationRouteChecks(requestLog) {
  const has = (method, route) => requestLog.some(
    item => item.method === method && item.route === route
  );
  return {
    interaction_admission_called: has("POST", "/ae-api/api/v1/chat/interactions"),
    progress_called: has(
      "GET",
      "/ae-api/api/v1/chat/interactions/{interaction_id}/progress"
    ),
    refresh_called: has(
      "POST",
      "/ae-api/api/v1/chat/interactions/{interaction_id}/refresh"
    ),
    generated_response_called: has(
      "GET",
      "/ae-api/api/v1/chat/interactions/{interaction_id}/response"
    ),
    citation_quality_called: has(
      "GET",
      "/ae-api/api/v1/chat/interactions/{interaction_id}/citation-quality"
    )
  };
}

export function normalizeInteractionRoute(route) {
  return route
    .replace(
      /\/chat\/interactions\/[^/?]+/,
      "/chat/interactions/{interaction_id}"
    )
    .replace(/\/documents\/[^/?]+/, "/documents/{document_id}");
}

export function sameOriginAeApiRoute(url) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.startsWith("/ae-api/") ? parsed.pathname : null;
  } catch {
    return null;
  }
}

export function assertEvidenceRedacted(evidence, environ = process.env) {
  const serialized = JSON.stringify(evidence);
  for (const key of REQUIRED_ENV) {
    const value = environ[key];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`Grounded generation evidence leaked ${key}`);
    }
  }
  for (const fragment of FORBIDDEN_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("Grounded generation evidence leaked server material");
    }
  }
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_grounded_generation_playwright_smoke=pass " +
      `display=${evidence.browser_observations.display_mode} ` +
      `events=${evidence.browser_observations.timeline_event_count} ` +
      `requests=${evidence.request_observations.ae_api_request_count}`
    );
  }
  return (
    "ae_web_grounded_generation_playwright_smoke=fail " +
    `reason=${evidence.failure_code || "checks_failed"}`
  );
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const evidence = await runGroundedGenerationPlaywrightSmoke();
  output(argv.includes("--summary")
    ? formatSummary(evidence)
    : JSON.stringify(evidence, null, 2));
  return evidence.status === "PASS" ? 0 : 1;
}

function failureEvidence(failureCode, observations = {}) {
  return {
    smoke_schema_version:
      AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    runner: { tool: "Playwright", browser: "chromium", headless: true },
    observations,
    checks: { redacted_evidence: true },
    redaction: {
      prompt_content_included: false,
      generated_content_included: false,
      source_content_included: false,
      credential_material_included: false,
      server_material_included: false
    }
  };
}

function normalizeTimeout(value) {
  if (value == null || value === "") return DEFAULT_TIMEOUT_MS;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1000 || parsed > 300000) {
    throw new Error("Playwright timeout is invalid");
  }
  return parsed;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exitCode = await main();
}
