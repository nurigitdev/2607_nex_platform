import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ARTIFACT_FILE_ID_ENV,
  ARTIFACT_ID_ENV,
  WEB_URL_ENV,
  assertArtifactPlaywrightSmokeEvidenceRedacted,
  browserSessionState,
  formatSummary,
  main,
  runArtifactPlaywrightSmoke,
  safeFetchRuntimeConfig
} from "../scripts/runArtifactPlaywrightSmoke.mjs";

function smokeEnv() {
  return {
    [WEB_URL_ENV]: "http://127.0.0.1:5229/",
    [ARTIFACT_ID_ENV]: "artifact-playwright-0419",
    [ARTIFACT_FILE_ID_ENV]: "artifact-file-playwright-0419"
  };
}

function fakePlaywright({ launchFails = false, browserResult = fakeBrowserResult() } = {}) {
  const page = fakePage({ browserResult });
  return {
    chromium: {
      async launch() {
        if (launchFails) {
          throw new Error("browser launch failed");
        }
        return {
          async newPage() {
            return page;
          },
          async close() {
            page.closed = true;
          }
        };
      }
    }
  };
}

function fakePage({ browserResult }) {
  const handlers = { request: [], response: [] };
  return {
    closed: false,
    on(eventName, handler) {
      handlers[eventName].push(handler);
    },
    async addInitScript(_script, config) {
      this.runtimeConfig = config;
    },
    async goto() {},
    async waitForSelector() {},
    async evaluate(_script, { artifactId, artifactFileId }) {
      emitArtifactRequestSequence(handlers, artifactId, artifactFileId);
      return browserResult;
    }
  };
}

function fakeBrowserResult(overrides = {}) {
  return {
    runtime: {
      client_mode: "fetch",
      fetch_mode_allowed: true,
      session_state: "authenticated"
    },
    dom: {
      artifact_panel_present: true,
      version_list_present: true,
      preview_panel_present: true
    },
    artifact: {
      summary: {
        artifact_id: "artifact-playwright-0419",
        status: "READY",
        content_included: false
      },
      file_summary: {
        artifact_id: "artifact-file-playwright-0419",
        content_included: false
      },
      preview_summary: {
        artifact_id: "artifact-file-playwright-0419",
        content_included: false
      },
      download_summary: {
        artifact_id: "artifact-file-playwright-0419",
        content_included: true
      },
      version_panel: {
        status: "VERSION_READY",
        version_count: 1,
        file_count: 1,
        preview_route_count: 1,
        download_route_count: 1,
        metadata: { storageLocationRendered: false }
      },
      preview_panel: {
        status: "PREVIEW_READY",
        metadata: { downloadedContentRendered: false }
      },
      download_panel: {
        status: "DOWNLOAD_READY",
        metadata: { downloadedContentRendered: false }
      },
      download_save: {
        status: "SAVED",
        blob_created: true,
        object_url_created: true,
        anchor_clicked: true,
        object_url_revoked: true,
        browser_save_available: true,
        payload_kind: "text",
        metadata: {
          rawDownloadContentIncluded: false,
          rawBase64PayloadIncluded: false
        }
      },
      export_result: {
        status: "SAVED",
        latest_save_status: "SAVED",
        downloadable_format_count: 1,
        metadata: {
          rawDownloadContentIncluded: false,
          rawBase64PayloadIncluded: false
        }
      },
      raw_download_observed: true,
      raw_download_length: 128
    },
    ...overrides
  };
}

function emitArtifactRequestSequence(handlers, artifactId, artifactFileId) {
  for (const route of [
    `/ae-api/api/v1/artifacts/${artifactId}`,
    `/ae-api/api/v1/artifacts/${artifactId}/versions`,
    `/ae-api/api/v1/artifact-files/${artifactFileId}`,
    `/ae-api/api/v1/artifact-files/${artifactFileId}/preview`,
    `/ae-api/api/v1/artifact-files/${artifactFileId}/download`
  ]) {
    emitRequest(handlers, "GET", `http://127.0.0.1:5229${route}`, 200);
  }
}

function emitRequest(handlers, method, url, status) {
  handlers.request.forEach(handler =>
    handler({
      method: () => method,
      url: () => url,
      headers: () => ({ accept: "application/json" })
    })
  );
  handlers.response.forEach(handler =>
    handler({
      status: () => status,
      url: () => url
    })
  );
}

describe("AE Web artifact Playwright smoke", () => {
  it("drives artifact fetch client and panel builders through browser routes", async () => {
    const env = smokeEnv();
    const evidence = await runArtifactPlaywrightSmoke({
      environ: env,
      importPlaywright: async () => fakePlaywright()
    });

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.tool, "Playwright");
    assert.equal(evidence.runtime.client_mode, "fetch");
    assert.equal(evidence.browser_observations.version_panel_status, "VERSION_READY");
    assert.equal(evidence.checks.artifact_download_called, true);
    assert.equal(evidence.checks.browser_request_secret_header_absent, true);
    assert.equal(evidence.checks.browser_file_save_prepared, true);
    assert.equal(evidence.checks.browser_export_result_saved, true);
    assert.equal(evidence.browser_observations.download_save_status, "SAVED");
    assert.equal(evidence.browser_observations.export_result_status, "SAVED");
    assert.equal(evidence.request_observations.ae_api_request_count, 5);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_playwright_smoke=pass " +
        "browser=chromium artifact=artifact-playwright-0419 versions=1 requests=5"
    );
  });

  it("reports missing env, failed checks, and browser launch failures safely", async () => {
    const missing = await runArtifactPlaywrightSmoke({
      environ: {},
      importPlaywright: async () => fakePlaywright()
    });
    const failedCheck = await runArtifactPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () =>
        fakePlaywright({
          browserResult: fakeBrowserResult({
            artifact: {
              ...fakeBrowserResult().artifact,
              version_panel: {
                ...fakeBrowserResult().artifact.version_panel,
                status: "UNAVAILABLE"
              }
            }
          })
        })
    });
    const failedLaunch = await runArtifactPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fakePlaywright({ launchFails: true })
    });

    assert.equal(missing.status, "FAIL");
    assert.equal(missing.failure_code, "required_env_missing");
    assert.equal(failedCheck.status, "FAIL");
    assert.equal(failedCheck.issues.some(issue => issue.subject === "artifact_version_panel_ready"), true);
    assert.equal(failedLaunch.status, "FAIL");
    assert.equal(failedLaunch.failure_code, "Error");
    assert.equal(formatSummary(failedLaunch), "ae_web_artifact_playwright_smoke=fail reason=Error");
  });

  it("keeps runtime config, session state, main output, and redaction explicit", async () => {
    const config = safeFetchRuntimeConfig();
    const session = browserSessionState();
    const lines = [];
    const summaryLines = [];

    assert.equal(config.ae_base_url, "/ae-api");
    assert.equal(config.features.fetch_clients_enabled, true);
    assert.equal(session.status, "authenticated");
    assert.throws(
      () => assertArtifactPlaywrightSmokeEvidenceRedacted({ leak: "storage_ref" }),
      /server material/
    );

    await main([], line => lines.push(line));
    await main(["--summary"], line => summaryLines.push(line));

    assert.equal(JSON.parse(lines.at(0)).failure_code, "required_env_missing");
    assert.match(summaryLines.at(0), /reason=required_env_missing/);
  });
});
