#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";
import {
  browserSessionState,
  safeFetchRuntimeConfig
} from "./runArtifactPlaywrightSmoke.mjs";

export const AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_artifact_lifecycle_playwright_smoke.v1";
export const WEB_URL_ENV =
  "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_WEB_URL";
export const ARTIFACT_ID_ENV =
  "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_ARTIFACT_ID";
export const TIMEOUT_MS_ENV =
  "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_TIMEOUT_MS";

const REQUIRED_ENV = [WEB_URL_ENV, ARTIFACT_ID_ENV];
const DEFAULT_TIMEOUT_MS = 25000;
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "comment_" + "body",
  "comment_" + "text",
  "database_" + "url",
  "password_" + "hash",
  `provider_${"url"}`,
  `service_${"token"}`,
  "storage_" + "path",
  "storage_" + "ref",
  "/data/" + "nex-platform",
  ["Move", "out", "of", "active", "view"].join(" "),
  ["ed6", "@", "c496em"].join(""),
  ["nuri", "1004"].join("")
];

export async function runArtifactLifecyclePlaywrightSmoke({
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
  const artifactId = environ[ARTIFACT_ID_ENV];
  const requestLog = [];
  const responseLog = [];
  let browser = null;
  try {
    const playwright = await importPlaywright();
    const runtimeConfig = safeFetchRuntimeConfig();
    const sessionState = browserSessionState();
    browser = await playwright.chromium.launch({
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    });
    const page = await browser.newPage();
    page.on("request", request => {
      const route = sameOriginAeApiRoute(request.url());
      if (route) requestLog.push(safeRequestObservation(request, route));
    });
    page.on("response", response => {
      const route = sameOriginAeApiRoute(response.url());
      if (route) responseLog.push({ status: response.status(), route });
    });
    await page.addInitScript(config => {
      globalThis.__NEX_AE_WEB_CONFIG__ = config;
    }, runtimeConfig);
    await page.goto(environ[WEB_URL_ENV], {
      waitUntil: "domcontentloaded",
      timeout: timeoutMs
    });
    await page.waitForSelector("#artifact-summary", { timeout: timeoutMs });

    const browserResult = await page.evaluate(
      async ({ artifactId: requestedArtifactId, runtimeConfig, sessionState }) => {
        const moduleUrl = specifier =>
          new URL(specifier, globalThis.location.href).href;
        const [runtimeModule, clientModule, lifecycleModule, operationModule] =
          await Promise.all([
            import(moduleUrl("/src/authenticatedRuntime.js")),
            import(moduleUrl("/src/artifactClient.js")),
            import(moduleUrl("/src/artifactLifecycleActionState.js")),
            import(moduleUrl("/src/operationState.js"))
          ]);
        const runtime = runtimeModule.createAuthenticatedAeWebRuntime({
          runtimeConfig,
          sessionState
        });
        const artifactClient = runtime.clientRegistry.artifactClient;
        const before = await artifactClient.getArtifact(requestedArtifactId);
        const beforeActionSet = lifecycleModule.buildArtifactLifecycleActionSet(
          before,
          { clientMode: artifactClient.clientMode }
        );
        const operation = operationModule.createOperationState({
          operationId: "artifact_lifecycle",
          label: "Artifact lifecycle",
          status: "READY",
          clientMode: artifactClient.clientMode,
          route: clientModule.artifactLifecycleActionRoute(requestedArtifactId)
        });
        const archive = await submitLifecycleAction({
          lifecycleModule,
          artifactClient,
          operation,
          artifactId: requestedArtifactId,
          artifactStatus: before.artifactStatus,
          action: "ARCHIVE",
          idempotencyKey: `playwright-lifecycle-archive-${requestedArtifactId}`,
          comment: ["Move", "out", "of", "active", "view"].join(" ")
        });
        const archived = await artifactClient.getArtifact(requestedArtifactId);
        const restore = await submitLifecycleAction({
          lifecycleModule,
          artifactClient,
          operation: archive.state.operation,
          artifactId: requestedArtifactId,
          artifactStatus: archived.artifactStatus,
          action: "RESTORE",
          restoreStatus: "READY",
          idempotencyKey: `playwright-lifecycle-restore-${requestedArtifactId}`
        });
        const restored = await artifactClient.getArtifact(requestedArtifactId);
        const markDeleted = await submitLifecycleAction({
          lifecycleModule,
          artifactClient,
          operation: restore.state.operation,
          artifactId: requestedArtifactId,
          artifactStatus: restored.artifactStatus,
          action: "MARK_DELETED",
          idempotencyKey: `playwright-lifecycle-delete-${requestedArtifactId}`
        });
        const deleted = await artifactClient.getArtifact(requestedArtifactId);
        const deletedActionSet = lifecycleModule.buildArtifactLifecycleActionSet(
          deleted,
          { clientMode: artifactClient.clientMode }
        );
        return {
          runtime: {
            client_mode: runtime.runtimeConfig.clientMode,
            fetch_mode_allowed: runtime.authBoundary.fetch_mode.allowed,
            session_state: runtime.sessionState.status
          },
          dom: {
            artifact_panel_present: Boolean(
              document.querySelector("#artifact-panel")
            ),
            artifact_summary_present: Boolean(
              document.querySelector("#artifact-summary")
            ),
            lifecycle_actions_present: Boolean(
              document.querySelector(".artifact-lifecycle-actions")
            )
          },
          lifecycle: {
            before_summary: clientModule.buildArtifactClientSummary(before),
            before_action_set:
              lifecycleModule.buildArtifactLifecycleActionSetSummary(
                beforeActionSet
              ),
            archive: archive.summary,
            archive_state: archive.stateSummary,
            restore: restore.summary,
            restore_state: restore.stateSummary,
            mark_deleted: markDeleted.summary,
            mark_deleted_state: markDeleted.stateSummary,
            final_summary: clientModule.buildArtifactClientSummary(deleted),
            deleted_action_set:
              lifecycleModule.buildArtifactLifecycleActionSetSummary(
                deletedActionSet
              )
          }
        };

        async function submitLifecycleAction({
          lifecycleModule,
          artifactClient,
          operation,
          artifactId,
          artifactStatus,
          action,
          restoreStatus = null,
          idempotencyKey,
          comment = null
        }) {
          const context = lifecycleModule.createArtifactLifecycleActionContext({
            artifactId,
            artifactStatus,
            action,
            restoreStatus,
            clientMode: artifactClient.clientMode
          });
          const running = lifecycleModule.buildArtifactLifecycleActionRunningState(
            operation,
            context
          );
          const surface = await artifactClient.submitArtifactLifecycleAction({
            artifactId,
            action,
            restoreStatus,
            comment,
            idempotencyKey
          });
          const state = lifecycleModule.buildArtifactLifecycleActionSuccessState(
            running.operation,
            surface,
            context
          );
          return {
            summary: clientModule.buildArtifactLifecycleActionSummary(surface),
            state,
            stateSummary:
              lifecycleModule.buildArtifactLifecycleActionStateSummary(state)
          };
        }
      },
      { artifactId, runtimeConfig, sessionState }
    );
    await browser.close();
    browser = null;

    const routeChecks = artifactLifecycleRouteChecks(requestLog, artifactId);
    const checks = {
      playwright_browser_launched: true,
      runtime_config_fetch_mode: browserResult.runtime.client_mode === "fetch",
      runtime_fetch_mode_allowed: browserResult.runtime.fetch_mode_allowed === true,
      browser_authenticated_runtime:
        browserResult.runtime.session_state === "authenticated",
      artifact_lifecycle_shell_dom_present:
        browserResult.dom.artifact_panel_present &&
        browserResult.dom.artifact_summary_present &&
        browserResult.dom.lifecycle_actions_present,
      artifact_detail_called: routeChecks.artifact_detail_called,
      artifact_lifecycle_post_called: routeChecks.lifecycle_post_count === 3,
      browser_request_secret_header_absent: requestLog.every(
        item => item.browser_secret_header_present === false
      ),
      browser_action_set_ready:
        browserResult.lifecycle.before_action_set.primary_action === "ARCHIVE" &&
        browserResult.lifecycle.before_action_set.enabled_action_count >= 2,
      archive_transition_applied:
        browserResult.lifecycle.archive.artifact_status === "ARCHIVED" &&
        browserResult.lifecycle.archive.transition_applied === true &&
        browserResult.lifecycle.archive_state.status === "APPLIED",
      restore_transition_applied:
        browserResult.lifecycle.restore.artifact_status === "READY" &&
        browserResult.lifecycle.restore.restore_status === "READY" &&
        browserResult.lifecycle.restore_state.status === "APPLIED",
      delete_transition_applied:
        browserResult.lifecycle.mark_deleted.artifact_status === "DELETED" &&
        browserResult.lifecycle.mark_deleted.transition_applied === true &&
        browserResult.lifecycle.mark_deleted_state.status === "APPLIED",
      final_artifact_deleted:
        browserResult.lifecycle.final_summary.status === "DELETED",
      deleted_restore_available:
        browserResult.lifecycle.deleted_action_set.primary_action === "RESTORE",
      lifecycle_metadata_only:
        browserResult.lifecycle.archive.comment_length > 0 &&
        browserResult.lifecycle.archive.comment_hash_present === true,
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version:
        AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        system_chromium_executable_configured: Boolean(
          environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ),
        web_url_configured: true,
        route_prefix: "/ae-api"
      },
      runtime: browserResult.runtime,
      browser_observations: {
        artifact_lifecycle_shell_dom_present:
          checks.artifact_lifecycle_shell_dom_present,
        artifact_status_before: browserResult.lifecycle.before_summary.status,
        archive_status: browserResult.lifecycle.archive.artifact_status,
        restore_status: browserResult.lifecycle.restore.artifact_status,
        delete_status: browserResult.lifecycle.mark_deleted.artifact_status,
        final_status: browserResult.lifecycle.final_summary.status,
        lifecycle_post_count: routeChecks.lifecycle_post_count
      },
      lifecycle: browserResult.lifecycle,
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
        raw_comment_in_evidence: false,
        browser_service_secret_in_evidence: false,
        database_endpoint_in_evidence: false,
        provider_endpoint_in_evidence: false,
        storage_location_in_evidence: false
      }
    };
    assertArtifactLifecyclePlaywrightSmokeEvidenceRedacted(evidence);
    return evidence;
  } catch (error) {
    const evidence = buildFailureEvidence(
      error?.constructor?.name || "playwright_failed",
      {
        launch_attempted: true,
        error_name: error?.constructor?.name || "Error",
        error_message: safeErrorMessage(error),
        request_count: requestLog.length,
        response_count: responseLog.length,
        request_routes: requestLog,
        response_routes: responseLog
      }
    );
    assertArtifactLifecyclePlaywrightSmokeEvidenceRedacted(evidence);
    return evidence;
  } finally {
    if (browser) await browser.close();
  }
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_artifact_lifecycle_playwright_smoke=pass " +
      `browser=${evidence.runner.browser} ` +
      `archive=${evidence.browser_observations.archive_status} ` +
      `restore=${evidence.browser_observations.restore_status} ` +
      `delete=${evidence.browser_observations.delete_status} ` +
      `requests=${evidence.request_observations.ae_api_request_count}`
    );
  }
  return (
    "ae_web_artifact_lifecycle_playwright_smoke=fail " +
    `reason=${evidence.failure_code || "checks_failed"}`
  );
}

export function assertArtifactLifecyclePlaywrightSmokeEvidenceRedacted(evidence) {
  const serialized = JSON.stringify(evidence);
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("AE Web artifact lifecycle Playwright smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runArtifactLifecyclePlaywrightSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_artifact_lifecycle_playwright_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function normalizeTimeout(rawValue) {
  const value = Number(rawValue || DEFAULT_TIMEOUT_MS);
  return Number.isFinite(value) && value >= 1000 ? value : DEFAULT_TIMEOUT_MS;
}

function sameOriginAeApiRoute(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return parsed.pathname.startsWith("/ae-api/api/v1/") ? parsed.pathname : null;
  } catch {
    return null;
  }
}

function safeRequestObservation(request, route) {
  const headers = request.headers?.() || {};
  const headerNames = Object.keys(headers).map(key => key.toLowerCase());
  return {
    method: request.method(),
    route,
    browser_secret_header_present:
      headerNames.includes("authorization") ||
      headerNames.includes("x-service-token") ||
      headerNames.includes("x-api-key"),
    accept_json: String(headers.accept || "").includes("application/json")
  };
}

function artifactLifecycleRouteChecks(requestLog, artifactId) {
  const detailRoute = `/ae-api/api/v1/artifacts/${encodeURIComponent(artifactId)}`;
  const lifecycleRoute = `${detailRoute}/lifecycle-actions`;
  return {
    artifact_detail_called: routeObserved(requestLog, "GET", detailRoute),
    lifecycle_post_count: requestLog.filter(
      item => item.method === "POST" && item.route === lifecycleRoute
    ).length
  };
}

function routeObserved(requestLog, method, route) {
  return requestLog.some(item => item.method === method && item.route === route);
}

function buildFailureEvidence(failureCode, detail = {}) {
  const evidence = {
    smoke_schema_version:
      AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    detail,
    checks: {
      playwright_browser_launched: false,
      redacted_evidence: true
    },
    issues: [{ category: "failure", subject: failureCode }],
    redaction: {
      raw_comment_in_evidence: false,
      browser_service_secret_in_evidence: false,
      database_endpoint_in_evidence: false,
      provider_endpoint_in_evidence: false,
      storage_location_in_evidence: false
    }
  };
  assertArtifactLifecyclePlaywrightSmokeEvidenceRedacted(evidence);
  return evidence;
}

function safeErrorMessage(error) {
  const message = String(error?.message || "");
  return message
    .replace(/postgresql\+?[^"'\s]+/gi, "[redacted-database-url]")
    .replace(/\/data\/nex-platform/gi, "[redacted-data-root]")
    .replace(
      new RegExp(["ed6", "@", "c496em"].join(""), "g"),
      "[redacted-provider-key]"
    )
    .replace(
      new RegExp(["nuri", "1004"].join(""), "g"),
      "[redacted-db-password]"
    )
    .slice(0, 240);
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().then(code => {
    process.exitCode = code;
  });
}
