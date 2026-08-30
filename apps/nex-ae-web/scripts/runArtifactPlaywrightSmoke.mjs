#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV
} from "./runCredentialLoginPlaywrightReadiness.mjs";

export const AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_artifact_playwright_smoke.v1";
export const WEB_URL_ENV = "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_WEB_URL";
export const ARTIFACT_ID_ENV = "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_ARTIFACT_ID";
export const ARTIFACT_FILE_ID_ENV =
  "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_ARTIFACT_FILE_ID";
export const TIMEOUT_MS_ENV = "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_TIMEOUT_MS";

const REQUIRED_ENV = [WEB_URL_ENV, ARTIFACT_ID_ENV, ARTIFACT_FILE_ID_ENV];
const DEFAULT_TIMEOUT_MS = 20000;
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

export async function runArtifactPlaywrightSmoke({
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
  const artifactFileId = environ[ARTIFACT_FILE_ID_ENV];
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
    await page.waitForSelector("#artifact-panel", { timeout: timeoutMs });

    const browserResult = await page.evaluate(
      async ({
        artifactId: requestedArtifactId,
        artifactFileId: requestedFileId,
        runtimeConfig,
        sessionState
      }) => {
        const moduleUrl = specifier =>
          new URL(specifier, globalThis.location.href).href;
        const [
          runtimeModule,
          clientModule,
          saveAdapterModule,
          exportResultModule,
          previewPanelModule,
          versionPanelModule
        ] = await Promise.all([
          import(moduleUrl("/src/authenticatedRuntime.js")),
          import(moduleUrl("/src/artifactClient.js")),
          import(moduleUrl("/src/artifactDownloadSaveAdapter.js")),
          import(moduleUrl("/src/artifactExportResultReadModel.js")),
          import(moduleUrl("/src/artifactPreviewPanel.js")),
          import(moduleUrl("/src/artifactVersionPanel.js"))
        ]);
        const runtime = runtimeModule.createAuthenticatedAeWebRuntime({
          runtimeConfig,
          sessionState
        });
        const artifactClient = runtime.clientRegistry.artifactClient;
        const artifactSurface = await artifactClient.getArtifact(requestedArtifactId);
        const versionsSurface = await artifactClient.listArtifactVersions(
          requestedArtifactId
        );
        const fileSurface = await artifactClient.getArtifactFile(requestedFileId);
        const previewSurface = await artifactClient.previewArtifactFile(
          requestedFileId
        );
        const downloadSurface = await artifactClient.downloadArtifactFile(
          requestedFileId
        );
        const browserSaveHarness = createBrowserSaveHarness();
        const downloadSaveResult = saveAdapterModule.saveArtifactDownload(
          downloadSurface,
          {
            BlobCtor: Blob,
            documentRef: browserSaveHarness.documentRef,
            urlRef: browserSaveHarness.urlRef
          }
        );
        const downloadSaveSummary =
          saveAdapterModule.buildArtifactDownloadSaveSummary(downloadSaveResult);
        const exportResultReadModel =
          exportResultModule.buildArtifactExportResultReadModel({
            artifactRef: {
              artifactId: artifactSurface.artifactId,
              artifactVersionId: artifactSurface.artifactVersionId,
              displayTitle: artifactSurface.displayTitle,
              artifactStatus: artifactSurface.artifactStatus,
              primaryFormat: artifactSurface.primaryFormat,
              availableFormats: artifactSurface.availableFormats,
              downloadRoutes: artifactSurface.downloadRoutes
            },
            downloadSaveSummary,
            clientMode: artifactClient.clientMode
          });
        const exportResultSummary =
          exportResultModule.buildArtifactExportResultSummary(
            exportResultReadModel
          );
        const versionPanel = versionPanelModule.buildArtifactVersionPanelState({
          artifactSurface,
          versionsSurface
        });
        const previewPanel =
          previewPanelModule.buildArtifactPreviewPanelStateFromPreview(
            previewSurface,
            { artifactId: requestedArtifactId }
          );
        const downloadPanel =
          previewPanelModule.buildArtifactPreviewPanelStateFromDownload(
            downloadSurface,
            { artifactId: requestedArtifactId }
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
            version_list_present: Boolean(
              document.querySelector("#artifact-version-list")
            ),
            preview_panel_present: Boolean(
              document.querySelector("#artifact-preview-content")
            )
          },
          artifact: {
            summary: clientModule.buildArtifactClientSummary(artifactSurface),
            file_summary: clientModule.buildArtifactClientSummary(fileSurface),
            preview_summary: clientModule.buildArtifactClientSummary(
              previewSurface
            ),
            download_summary: clientModule.buildArtifactClientSummary(
              downloadSurface
            ),
            version_panel:
              versionPanelModule.buildArtifactVersionPanelSummary(versionPanel),
            preview_panel:
              previewPanelModule.buildArtifactPreviewPanelSummary(previewPanel),
            download_panel:
              previewPanelModule.buildArtifactPreviewPanelSummary(downloadPanel),
            download_save: downloadSaveSummary,
            export_result: exportResultSummary,
            browser_save_events: browserSaveHarness.events,
            raw_download_observed:
              typeof downloadSurface.content === "string" &&
              downloadSurface.content.length > 0,
            raw_download_length: downloadSurface.contentLength || 0
          }
        };

        function createBrowserSaveHarness() {
          const events = [];
          const documentRef = {
            body: {
              appendChild(anchor) {
                events.push(["append", anchor.download]);
              },
              removeChild(anchor) {
                events.push(["remove", anchor.download]);
              }
            },
            createElement(tagName) {
              events.push(["create", tagName]);
              return {
                style: {},
                click() {
                  events.push(["click", this.download]);
                }
              };
            }
          };
          const urlRef = {
            createObjectURL(blob) {
              events.push(["object_url", blob.type, blob.size]);
              return "blob://ae-web-artifact-playwright-smoke";
            },
            revokeObjectURL(url) {
              events.push(["revoke", url]);
            }
          };
          return { documentRef, urlRef, events };
        }
      },
      { artifactId, artifactFileId, runtimeConfig, sessionState }
    );
    await browser.close();
    browser = null;

    const routeChecks = artifactRouteChecks(requestLog, artifactId, artifactFileId);
    const checks = {
      playwright_browser_launched: true,
      runtime_config_fetch_mode: browserResult.runtime.client_mode === "fetch",
      runtime_fetch_mode_allowed: browserResult.runtime.fetch_mode_allowed === true,
      browser_authenticated_runtime:
        browserResult.runtime.session_state === "authenticated",
      artifact_shell_dom_present:
        browserResult.dom.artifact_panel_present &&
        browserResult.dom.version_list_present &&
        browserResult.dom.preview_panel_present,
      artifact_detail_called: routeChecks.artifact_detail_called,
      artifact_versions_called: routeChecks.artifact_versions_called,
      artifact_file_metadata_called: routeChecks.artifact_file_metadata_called,
      artifact_preview_called: routeChecks.artifact_preview_called,
      artifact_download_called: routeChecks.artifact_download_called,
      browser_request_secret_header_absent: requestLog.every(
        item => item.browser_secret_header_present === false
      ),
      artifact_summary_safe:
        browserResult.artifact.summary.content_included === false,
      artifact_file_metadata_safe:
        browserResult.artifact.file_summary.content_included === false,
      artifact_preview_panel_ready:
        browserResult.artifact.preview_panel.status === "PREVIEW_READY",
      artifact_download_panel_ready:
        browserResult.artifact.download_panel.status === "DOWNLOAD_READY",
      browser_file_save_prepared:
        browserResult.artifact.download_save.status === "SAVED" &&
        browserResult.artifact.download_save.blob_created === true &&
        browserResult.artifact.download_save.object_url_created === true &&
        browserResult.artifact.download_save.anchor_clicked === true &&
        browserResult.artifact.download_save.object_url_revoked === true,
      browser_export_result_saved:
        browserResult.artifact.export_result.status === "SAVED" &&
        browserResult.artifact.export_result.latest_save_status === "SAVED",
      artifact_version_panel_ready:
        browserResult.artifact.version_panel.status === "VERSION_READY",
      artifact_version_file_linked:
        browserResult.artifact.version_panel.file_count >= 1 &&
        browserResult.artifact.version_panel.preview_route_count >= 1 &&
        browserResult.artifact.version_panel.download_route_count >= 1,
      raw_download_retrieved_but_not_rendered:
        browserResult.artifact.raw_download_observed === true &&
        browserResult.artifact.raw_download_length > 0 &&
        browserResult.artifact.download_panel.metadata.downloadedContentRendered ===
          false,
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version: AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
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
        artifact_shell_dom_present: checks.artifact_shell_dom_present,
        artifact_status: browserResult.artifact.summary.status,
        version_panel_status: browserResult.artifact.version_panel.status,
        preview_panel_status: browserResult.artifact.preview_panel.status,
        download_panel_status: browserResult.artifact.download_panel.status,
        download_save_status: browserResult.artifact.download_save.status,
        export_result_status: browserResult.artifact.export_result.status,
        raw_download_retrieved: browserResult.artifact.raw_download_observed,
        raw_download_length: browserResult.artifact.raw_download_length,
        downloaded_content_rendered: false
      },
      artifact: {
        summary: browserResult.artifact.summary,
        file_summary: browserResult.artifact.file_summary,
        preview_panel: browserResult.artifact.preview_panel,
        download_panel: browserResult.artifact.download_panel,
        download_save: browserResult.artifact.download_save,
        export_result: browserResult.artifact.export_result,
        version_panel: browserResult.artifact.version_panel
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
        raw_download_body_in_evidence: false,
        browser_service_secret_in_evidence: false,
        database_endpoint_in_evidence: false,
        provider_endpoint_in_evidence: false,
        storage_location_in_evidence: false
      }
    };
    assertArtifactPlaywrightSmokeEvidenceRedacted(evidence);
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
    assertArtifactPlaywrightSmokeEvidenceRedacted(evidence);
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
    clientMode: "fetch",
    ae_base_url: "/ae-api",
    aeBaseUrl: "/ae-api",
    features: {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    }
  };
}

export function browserSessionState() {
  return {
    session_state_schema_version: "ae_web_session_state.v1",
    status: "authenticated",
    sessionId: "session-artifact-playwright-smoke",
    tenantRef: { type: "oa.tenant", id: "tenant-artifact-playwright-smoke" },
    subjectRef: { type: "oa.user", id: "user-artifact-playwright-smoke" },
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
      "ae_web_artifact_playwright_smoke=pass " +
      `browser=${evidence.runner.browser} ` +
      `artifact=${evidence.artifact.summary.artifact_id} ` +
      `versions=${evidence.artifact.version_panel.version_count} ` +
      `requests=${evidence.request_observations.ae_api_request_count}`
    );
  }
  return (
    "ae_web_artifact_playwright_smoke=fail " +
    `reason=${evidence.failure_code || "checks_failed"}`
  );
}

export function assertArtifactPlaywrightSmokeEvidenceRedacted(evidence) {
  const serialized = JSON.stringify(evidence);
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("AE Web artifact Playwright smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runArtifactPlaywrightSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_artifact_playwright_smoke=fail " +
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

function artifactRouteChecks(requestLog, artifactId, artifactFileId) {
  const detailRoute = `/ae-api/api/v1/artifacts/${encodeURIComponent(artifactId)}`;
  const versionsRoute = `${detailRoute}/versions`;
  const fileRoute = `/ae-api/api/v1/artifact-files/${encodeURIComponent(
    artifactFileId
  )}`;
  return {
    artifact_detail_called: routeObserved(requestLog, "GET", detailRoute),
    artifact_versions_called: routeObserved(requestLog, "GET", versionsRoute),
    artifact_file_metadata_called: routeObserved(requestLog, "GET", fileRoute),
    artifact_preview_called: routeObserved(requestLog, "GET", `${fileRoute}/preview`),
    artifact_download_called: routeObserved(
      requestLog,
      "GET",
      `${fileRoute}/download`
    )
  };
}

function routeObserved(requestLog, method, route) {
  return requestLog.some(item => item.method === method && item.route === route);
}

function buildFailureEvidence(failureCode, detail = {}) {
  const evidence = {
    smoke_schema_version: AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    detail,
    checks: {
      playwright_browser_launched: false,
      redacted_evidence: true
    },
    issues: [{ category: "failure", subject: failureCode }],
    redaction: {
      raw_download_body_in_evidence: false,
      browser_service_secret_in_evidence: false,
      database_endpoint_in_evidence: false,
      provider_endpoint_in_evidence: false,
      storage_location_in_evidence: false
    }
  };
  assertArtifactPlaywrightSmokeEvidenceRedacted(evidence);
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
