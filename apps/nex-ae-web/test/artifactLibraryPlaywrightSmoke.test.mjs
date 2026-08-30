import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  OWNER_USER_ID_ENV,
  READY_ARTIFACT_ID_ENV,
  TENANT_ID_ENV,
  WEB_URL_ENV,
  WORKSPACE_ID_ENV,
  assertArtifactLibraryPlaywrightSmokeEvidenceRedacted,
  browserSessionState,
  formatSummary,
  main,
  runArtifactLibraryPlaywrightSmoke
} from "../scripts/runArtifactLibraryPlaywrightSmoke.mjs";

function smokeEnv() {
  return {
    [WEB_URL_ENV]: "http://127.0.0.1:5448/",
    [TENANT_ID_ENV]: "tenant-library-0448",
    [WORKSPACE_ID_ENV]: "workspace-library-0448",
    [OWNER_USER_ID_ENV]: "owner-library-0448",
    [READY_ARTIFACT_ID_ENV]: "artifact-library-ready-0448"
  };
}

function fakePlaywright({
  launchFails = false,
  browserResultFactory = fakeBrowserResult
} = {}) {
  const page = fakePage({ browserResultFactory });
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

function fakePage({ browserResultFactory }) {
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
    async evaluate(_script, { query, readyArtifactId }) {
      emitArtifactLibraryRequests(handlers, query, readyArtifactId);
      return browserResultFactory({ query, readyArtifactId });
    }
  };
}

function fakeBrowserResult({ query, readyArtifactId, overrides = {} }) {
  const result = {
    runtime: {
      client_mode: "fetch",
      fetch_mode_allowed: true,
      session_state: "authenticated"
    },
    dom: {
      artifact_panel_present: true,
      library_filter_present: true,
      library_feedback_present: true,
      library_summary_present: true,
      library_list_present: true,
      rendered_item_count: 2,
      ready_artifact_rendered: true
    },
    library: {
      collection_summary: {
        item_count: 2,
        ready_count: 1,
        downloadable_count: 1,
        previewable_count: 1,
        filter: {
          tenant_id: query.tenantId,
          workspace_id: query.workspaceId,
          owner_user_id: query.ownerUserId
        }
      },
      panel_summary: {
        status: "READY",
        item_count: 2,
        ready_count: 1,
        downloadable_count: 1,
        previewable_count: 1
      },
      ready_summary: {
        status: "READY",
        item_count: 1,
        ready_count: 1
      },
      failed_summary: {
        status: "EMPTY",
        item_count: 0
      },
      downloadable_summary: {
        status: "READY",
        item_count: 1,
        downloadable_count: 1
      },
      previewable_summary: {
        status: "READY",
        item_count: 1,
        previewable_count: 1
      },
      selected_artifact_summary: {
        artifact_id: readyArtifactId,
        status: "READY",
        content_included: false
      },
      view: {
        status: "READY",
        severity: "success",
        item_count: 2,
        html_escaped: true,
        content_rendered: false,
        storage_location_rendered: false
      }
    }
  };
  return deepMerge(result, overrides);
}

function emitArtifactLibraryRequests(handlers, query, readyArtifactId) {
  const params = new URLSearchParams();
  params.set("tenant_id", query.tenantId);
  params.set("workspace_id", query.workspaceId);
  params.set("owner_user_id", query.ownerUserId);
  params.set("limit", String(query.limit));
  for (const route of [
    `/ae-api/api/v1/artifacts?${params.toString()}`,
    `/ae-api/api/v1/artifacts/${readyArtifactId}`
  ]) {
    emitRequest(handlers, "GET", `http://127.0.0.1:5448${route}`, 200);
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

describe("AE Web artifact library Playwright smoke", () => {
  it("drives the collection client and library renderer through browser routes", async () => {
    const evidence = await runArtifactLibraryPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fakePlaywright()
    });

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.tool, "Playwright");
    assert.equal(evidence.runtime.client_mode, "fetch");
    assert.equal(evidence.browser_observations.library_status, "READY");
    assert.equal(evidence.browser_observations.library_item_count, 2);
    assert.equal(evidence.checks.artifact_collection_called, true);
    assert.equal(evidence.checks.artifact_detail_called, true);
    assert.equal(evidence.checks.artifact_library_owner_scoped, true);
    assert.equal(evidence.checks.artifact_library_metadata_only, true);
    assert.equal(evidence.request_observations.ae_api_request_count, 2);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_library_playwright_smoke=pass " +
        "browser=chromium items=2 ready=1 requests=2"
    );
  });

  it("reports missing env, failed checks, and launch failures safely", async () => {
    const missing = await runArtifactLibraryPlaywrightSmoke({
      environ: {},
      importPlaywright: async () => fakePlaywright()
    });
    const failedCheck = await runArtifactLibraryPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () =>
        fakePlaywright({
          browserResultFactory: input =>
            fakeBrowserResult({
              ...input,
              overrides: {
                library: {
                  panel_summary: {
                    status: "UNAVAILABLE",
                    item_count: 0,
                    ready_count: 0,
                    downloadable_count: 0,
                    previewable_count: 0
                  }
                }
              }
            })
        })
    });
    const failedLaunch = await runArtifactLibraryPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fakePlaywright({ launchFails: true })
    });

    assert.equal(missing.status, "FAIL");
    assert.equal(missing.failure_code, "required_env_missing");
    assert.equal(failedCheck.status, "FAIL");
    assert.equal(
      failedCheck.issues.some(
        issue => issue.subject === "artifact_library_panel_ready"
      ),
      true
    );
    assert.equal(failedLaunch.status, "FAIL");
    assert.equal(failedLaunch.failure_code, "Error");
    assert.equal(
      formatSummary(failedLaunch),
      "ae_web_artifact_library_playwright_smoke=fail reason=Error"
    );
  });

  it("keeps runtime session, main output, and redaction explicit", async () => {
    const session = browserSessionState({
      tenantId: "tenant-library-0448",
      ownerUserId: "owner-library-0448"
    });
    const lines = [];
    const summaryLines = [];

    assert.equal(session.status, "authenticated");
    assert.equal(session.tenantRef.id, "tenant-library-0448");
    assert.equal(session.subjectRef.id, "owner-library-0448");
    assert.throws(
      () =>
        assertArtifactLibraryPlaywrightSmokeEvidenceRedacted({
          leak: "storage_ref"
        }),
      /server material/
    );

    await main([], line => lines.push(line));
    await main(["--summary"], line => summaryLines.push(line));

    assert.equal(JSON.parse(lines.at(0)).failure_code, "required_env_missing");
    assert.match(summaryLines.at(0), /reason=required_env_missing/);
  });
});

function deepMerge(base, overrides) {
  const output = { ...base };
  for (const [key, value] of Object.entries(overrides || {})) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      base[key] &&
      typeof base[key] === "object" &&
      !Array.isArray(base[key])
    ) {
      output[key] = deepMerge(base[key], value);
    } else {
      output[key] = value;
    }
  }
  return output;
}
