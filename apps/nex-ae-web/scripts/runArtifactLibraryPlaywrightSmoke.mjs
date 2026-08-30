#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";
import {
  safeFetchRuntimeConfig
} from "./runArtifactPlaywrightSmoke.mjs";

export const AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_artifact_library_playwright_smoke.v1";
export const WEB_URL_ENV =
  "NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_WEB_URL";
export const TENANT_ID_ENV =
  "NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_TENANT_ID";
export const WORKSPACE_ID_ENV =
  "NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_WORKSPACE_ID";
export const OWNER_USER_ID_ENV =
  "NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_OWNER_USER_ID";
export const READY_ARTIFACT_ID_ENV =
  "NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_READY_ARTIFACT_ID";
export const TIMEOUT_MS_ENV =
  "NEX_AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_TIMEOUT_MS";

const REQUIRED_ENV = [
  WEB_URL_ENV,
  TENANT_ID_ENV,
  WORKSPACE_ID_ENV,
  OWNER_USER_ID_ENV,
  READY_ARTIFACT_ID_ENV
];
const DEFAULT_TIMEOUT_MS = 25000;
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "content_" + "base64",
  "content_" + "text",
  "database_" + "url",
  "password_" + "hash",
  `provider_${"url"}`,
  `service_${"token"}`,
  "storage_" + "path",
  "storage_" + "ref",
  "/data/" + "nex-platform",
  ["ed6", "@", "c496em"].join(""),
  ["nuri", "1004"].join("")
];

export async function runArtifactLibraryPlaywrightSmoke({
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
  const query = {
    tenantId: environ[TENANT_ID_ENV],
    workspaceId: environ[WORKSPACE_ID_ENV],
    ownerUserId: environ[OWNER_USER_ID_ENV],
    limit: 20
  };
  const readyArtifactId = environ[READY_ARTIFACT_ID_ENV];
  const requestLog = [];
  const responseLog = [];
  let browser = null;
  try {
    const playwright = await importPlaywright();
    const runtimeConfig = safeFetchRuntimeConfig();
    const sessionState = browserSessionState(query);
    browser = await playwright.chromium.launch({
      headless: true,
      ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
        ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
        : {})
    });
    const page = await browser.newPage();
    page.on("request", request => {
      const route = sameOriginAeApiRoute(request.url());
      if (route) {
        requestLog.push(safeRequestObservation(request, route));
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
    }, runtimeConfig);
    await page.goto(environ[WEB_URL_ENV], {
      waitUntil: "domcontentloaded",
      timeout: timeoutMs
    });
    await page.waitForSelector("#artifact-library-list", { timeout: timeoutMs });

    const browserResult = await page.evaluate(
      async ({ query, readyArtifactId, runtimeConfig, sessionState }) => {
        const moduleUrl = specifier =>
          new URL(specifier, globalThis.location.href).href;
        const [runtimeModule, clientModule, libraryModule] = await Promise.all([
          import(moduleUrl("/src/authenticatedRuntime.js")),
          import(moduleUrl("/src/artifactClient.js")),
          import(moduleUrl("/src/artifactLibraryPanel.js"))
        ]);
        const runtime = runtimeModule.createAuthenticatedAeWebRuntime({
          runtimeConfig,
          sessionState
        });
        const artifactClient = runtime.clientRegistry.artifactClient;
        const collectionSurface = await artifactClient.listArtifacts(query);
        const panel = libraryModule.buildArtifactLibraryPanelState(collectionSurface);
        const readyPanel = libraryModule.filterArtifactLibraryPanelState(
          panel,
          "ready"
        );
        const failedPanel = libraryModule.filterArtifactLibraryPanelState(
          panel,
          "failed"
        );
        const downloadablePanel = libraryModule.filterArtifactLibraryPanelState(
          panel,
          "downloadable"
        );
        const previewablePanel = libraryModule.filterArtifactLibraryPanelState(
          panel,
          "previewable"
        );
        const view = libraryModule.renderArtifactLibraryPanel(panel);
        const summary = libraryModule.buildArtifactLibraryPanelSummary(panel);
        const readySummary =
          libraryModule.buildArtifactLibraryPanelSummary(readyPanel);
        const failedSummary =
          libraryModule.buildArtifactLibraryPanelSummary(failedPanel);
        const downloadableSummary =
          libraryModule.buildArtifactLibraryPanelSummary(downloadablePanel);
        const previewableSummary =
          libraryModule.buildArtifactLibraryPanelSummary(previewablePanel);
        const summaryNode = document.querySelector("#artifact-library-summary");
        const listNode = document.querySelector("#artifact-library-list");
        if (summaryNode) summaryNode.innerHTML = view.summaryHtml;
        if (listNode) listNode.innerHTML = view.listHtml;
        const renderedItems = [
          ...document.querySelectorAll("[data-artifact-library-item]")
        ].map(item => item.getAttribute("data-artifact-library-item"));
        const selectedItem =
          panel.items.find(item => item.artifactId === readyArtifactId) ||
          readyPanel.items[0];
        const selectedArtifact = selectedItem
          ? await artifactClient.getArtifact(selectedItem.artifactId)
          : null;
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
            library_filter_present: Boolean(
              document.querySelector("#artifact-library-filter")
            ),
            library_feedback_present: Boolean(
              document.querySelector("#artifact-library-feedback")
            ),
            library_summary_present: Boolean(summaryNode),
            library_list_present: Boolean(listNode),
            rendered_item_count: renderedItems.length,
            ready_artifact_rendered: renderedItems.includes(readyArtifactId)
          },
          library: {
            collection_summary:
              clientModule.buildArtifactCollectionSummary(collectionSurface),
            panel_summary: summary,
            ready_summary: readySummary,
            failed_summary: failedSummary,
            downloadable_summary: downloadableSummary,
            previewable_summary: previewableSummary,
            selected_artifact_summary: selectedArtifact
              ? clientModule.buildArtifactClientSummary(selectedArtifact)
              : null,
            view: {
              status: view.status,
              severity: view.severity,
              item_count: panel.itemCount,
              html_escaped: view.metadata.htmlEscaped,
              content_rendered: view.metadata.contentRendered,
              storage_location_rendered:
                view.metadata.storageLocationRendered
            }
          }
        };
      },
      { query, readyArtifactId, runtimeConfig, sessionState }
    );
    await browser.close();
    browser = null;

    const routeChecks = artifactLibraryRouteChecks(requestLog, readyArtifactId);
    const checks = {
      playwright_browser_launched: true,
      runtime_config_fetch_mode: browserResult.runtime.client_mode === "fetch",
      runtime_fetch_mode_allowed: browserResult.runtime.fetch_mode_allowed === true,
      browser_authenticated_runtime:
        browserResult.runtime.session_state === "authenticated",
      artifact_library_shell_dom_present:
        browserResult.dom.artifact_panel_present &&
        browserResult.dom.library_filter_present &&
        browserResult.dom.library_feedback_present &&
        browserResult.dom.library_summary_present &&
        browserResult.dom.library_list_present,
      artifact_collection_called: routeChecks.artifact_collection_called,
      artifact_detail_called: routeChecks.artifact_detail_called,
      browser_request_secret_header_absent: requestLog.every(
        item => item.browser_secret_header_present === false
      ),
      artifact_library_panel_ready:
        browserResult.library.panel_summary.status === "READY",
      artifact_library_owner_scoped:
        browserResult.library.collection_summary.item_count >= 2 &&
        browserResult.library.collection_summary.filter.tenant_id ===
          query.tenantId &&
        browserResult.library.collection_summary.filter.workspace_id ===
          query.workspaceId &&
        browserResult.library.collection_summary.filter.owner_user_id ===
          query.ownerUserId,
      artifact_library_ready_filter:
        browserResult.library.ready_summary.item_count >= 1 &&
        browserResult.library.ready_summary.ready_count >= 1,
      artifact_library_failed_filter_empty:
        browserResult.library.failed_summary.item_count === 0,
      artifact_library_downloadable_filter:
        browserResult.library.downloadable_summary.item_count >= 1 &&
        browserResult.library.downloadable_summary.downloadable_count >= 1,
      artifact_library_previewable_filter:
        browserResult.library.previewable_summary.item_count >= 1 &&
        browserResult.library.previewable_summary.previewable_count >= 1,
      artifact_library_dom_rendered:
        browserResult.dom.rendered_item_count >= 2 &&
        browserResult.dom.ready_artifact_rendered === true,
      selected_artifact_detail_ready:
        browserResult.library.selected_artifact_summary?.artifact_id ===
          readyArtifactId &&
        browserResult.library.selected_artifact_summary?.status === "READY",
      artifact_library_metadata_only:
        browserResult.library.view.html_escaped === true &&
        browserResult.library.view.content_rendered === false &&
        browserResult.library.view.storage_location_rendered === false,
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version:
        AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
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
        artifact_library_shell_dom_present:
          checks.artifact_library_shell_dom_present,
        library_status: browserResult.library.panel_summary.status,
        library_item_count: browserResult.library.panel_summary.item_count,
        ready_count: browserResult.library.panel_summary.ready_count,
        downloadable_count:
          browserResult.library.panel_summary.downloadable_count,
        previewable_count: browserResult.library.panel_summary.previewable_count,
        rendered_item_count: browserResult.dom.rendered_item_count,
        ready_artifact_rendered: browserResult.dom.ready_artifact_rendered
      },
      library: browserResult.library,
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
        rendered_payload_in_evidence: false,
        browser_service_secret_in_evidence: false,
        database_endpoint_in_evidence: false,
        provider_endpoint_in_evidence: false,
        storage_location_in_evidence: false
      }
    };
    assertArtifactLibraryPlaywrightSmokeEvidenceRedacted(evidence);
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
    assertArtifactLibraryPlaywrightSmokeEvidenceRedacted(evidence);
    return evidence;
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

export function browserSessionState({
  tenantId,
  ownerUserId
}) {
  return {
    session_state_schema_version: "ae_web_session_state.v1",
    status: "authenticated",
    sessionId: "session-artifact-library-playwright-smoke",
    tenantRef: { type: "oa.tenant", id: tenantId },
    subjectRef: { type: "oa.user", id: ownerUserId },
    scopes: ["workspace:use", "documents:read"],
    roles: ["employee"],
    reason: null,
    issuedAt: "2026-08-30T00:00:00Z",
    expiresAt: "2026-08-30T01:00:00Z",
    metadata: {
      rawTokenIncluded: false,
      serviceTokenIncluded: false,
      passwordIncluded: false,
      browserPayloadOwnerAuthoritative: false,
      claimOwnerAuthoritative: true
    }
  };
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_artifact_library_playwright_smoke=pass " +
      `browser=${evidence.runner.browser} ` +
      `items=${evidence.browser_observations.library_item_count} ` +
      `ready=${evidence.browser_observations.ready_count} ` +
      `requests=${evidence.request_observations.ae_api_request_count}`
    );
  }
  return (
    "ae_web_artifact_library_playwright_smoke=fail " +
    `reason=${evidence.failure_code || "checks_failed"}`
  );
}

export function assertArtifactLibraryPlaywrightSmokeEvidenceRedacted(evidence) {
  const serialized = JSON.stringify(evidence);
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("AE Web artifact library Playwright smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runArtifactLibraryPlaywrightSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_artifact_library_playwright_smoke=fail " +
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
    return parsed.pathname.startsWith("/ae-api/api/v1/")
      ? `${parsed.pathname}${parsed.search}`
      : null;
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

function artifactLibraryRouteChecks(requestLog, readyArtifactId) {
  const collectionRoute = "/ae-api/api/v1/artifacts";
  const detailRoute = `${collectionRoute}/${encodeURIComponent(readyArtifactId)}`;
  return {
    artifact_collection_called: routeObservedPrefix(
      requestLog,
      "GET",
      collectionRoute
    ),
    artifact_detail_called: routeObserved(requestLog, "GET", detailRoute)
  };
}

function routeObserved(requestLog, method, route) {
  return requestLog.some(item => item.method === method && item.route === route);
}

function routeObservedPrefix(requestLog, method, routePrefix) {
  return requestLog.some(
    item => item.method === method && item.route.startsWith(routePrefix)
  );
}

function buildFailureEvidence(failureCode, detail = {}) {
  const evidence = {
    smoke_schema_version:
      AE_WEB_ARTIFACT_LIBRARY_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    detail,
    checks: {
      playwright_browser_launched: false,
      redacted_evidence: true
    },
    issues: [{ category: "failure", subject: failureCode }],
    redaction: {
      rendered_payload_in_evidence: false,
      browser_service_secret_in_evidence: false,
      database_endpoint_in_evidence: false,
      provider_endpoint_in_evidence: false,
      storage_location_in_evidence: false
    }
  };
  assertArtifactLibraryPlaywrightSmokeEvidenceRedacted(evidence);
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
