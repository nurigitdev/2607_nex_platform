import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
  ARTIFACT_ID_ENV,
  WEB_URL_ENV,
  assertArtifactLifecyclePlaywrightSmokeEvidenceRedacted,
  formatSummary,
  main,
  runArtifactLifecyclePlaywrightSmoke
} from "../scripts/runArtifactLifecyclePlaywrightSmoke.mjs";

const ENV = {
  [WEB_URL_ENV]: "http://127.0.0.1:5458/",
  [ARTIFACT_ID_ENV]: "artifact-0458"
};

function browserResult(overrides = {}) {
  return {
    runtime: {
      client_mode: "fetch",
      fetch_mode_allowed: true,
      session_state: "authenticated"
    },
    dom: {
      artifact_panel_present: true,
      artifact_summary_present: true,
      lifecycle_actions_present: true
    },
    lifecycle: {
      before_summary: { artifact_id: "artifact-0458", status: "READY" },
      before_action_set: {
        enabled_action_count: 2,
        primary_action: "ARCHIVE"
      },
      archive: {
        artifact_status: "ARCHIVED",
        transition_applied: true,
        comment_hash_present: true,
        comment_length: 23
      },
      archive_state: { status: "APPLIED" },
      restore: {
        artifact_status: "READY",
        restore_status: "READY",
        transition_applied: true
      },
      restore_state: { status: "APPLIED" },
      mark_deleted: {
        artifact_status: "DELETED",
        transition_applied: true
      },
      mark_deleted_state: { status: "APPLIED" },
      final_summary: { artifact_id: "artifact-0458", status: "DELETED" },
      deleted_action_set: {
        enabled_action_count: 1,
        primary_action: "RESTORE"
      }
    },
    ...overrides
  };
}

function fakePlaywright(result = browserResult(), { secretHeader = false } = {}) {
  const routes = [
    ["GET", "/ae-api/api/v1/artifacts/artifact-0458"],
    ["POST", "/ae-api/api/v1/artifacts/artifact-0458/lifecycle-actions"],
    ["GET", "/ae-api/api/v1/artifacts/artifact-0458"],
    ["POST", "/ae-api/api/v1/artifacts/artifact-0458/lifecycle-actions"],
    ["GET", "/ae-api/api/v1/artifacts/artifact-0458"],
    ["POST", "/ae-api/api/v1/artifacts/artifact-0458/lifecycle-actions"],
    ["GET", "/ae-api/api/v1/artifacts/artifact-0458"]
  ];
  let requestHandler = null;
  let responseHandler = null;
  let closed = false;
  const page = {
    on(eventName, handler) {
      if (eventName === "request") requestHandler = handler;
      if (eventName === "response") responseHandler = handler;
    },
    async addInitScript() {},
    async goto() {},
    async waitForSelector() {
      for (const [method, route] of routes) {
        requestHandler?.({
          url: () => `http://127.0.0.1:5458${route}`,
          method: () => method,
          headers: () => ({
            accept: "application/json",
            ...(secretHeader ? { "x-api-key": "hidden" } : {})
          })
        });
        responseHandler?.({
          url: () => `http://127.0.0.1:5458${route}`,
          status: () => 200
        });
      }
    },
    async evaluate() {
      return result;
    }
  };
  return {
    closed: () => closed,
    module: {
      chromium: {
        async launch() {
          return {
            async newPage() {
              return page;
            },
            async close() {
              closed = true;
            }
          };
        }
      }
    }
  };
}

describe("AE Web artifact lifecycle Playwright smoke harness", () => {
  it("reports required environment failures without launching a browser", async () => {
    const evidence = await runArtifactLifecyclePlaywrightSmoke({
      environ: {},
      importPlaywright: async () => fakePlaywright().module
    });

    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.failure_code, "required_env_missing");
    assert.equal(evidence.smoke_schema_version, AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_SCHEMA_VERSION);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_lifecycle_playwright_smoke=fail reason=required_env_missing"
    );
  });

  it("passes archive, restore, and logical delete checks with safe request logs", async () => {
    const fake = fakePlaywright();
    const evidence = await runArtifactLifecyclePlaywrightSmoke({
      environ: ENV,
      importPlaywright: async () => fake.module
    });
    const serialized = JSON.stringify(evidence);

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.browser_observations.lifecycle_post_count, 3);
    assert.equal(evidence.browser_observations.archive_status, "ARCHIVED");
    assert.equal(evidence.browser_observations.restore_status, "READY");
    assert.equal(evidence.browser_observations.delete_status, "DELETED");
    assert.equal(evidence.checks.browser_request_secret_header_absent, true);
    assert.equal(fake.closed(), true);
    assert.doesNotMatch(serialized, /Move out of active view|nuri1004|database_url/);
    assert.equal(
      formatSummary(evidence),
      "ae_web_artifact_lifecycle_playwright_smoke=pass browser=chromium archive=ARCHIVED restore=READY delete=DELETED requests=7"
    );
  });

  it("turns failed checks and launch failures into redacted evidence", async () => {
    const badChecks = await runArtifactLifecyclePlaywrightSmoke({
      environ: ENV,
      importPlaywright: async () =>
        fakePlaywright(
          browserResult({
            lifecycle: {
              ...browserResult().lifecycle,
              mark_deleted: { artifact_status: "READY", transition_applied: false }
            }
          })
        ).module
    });
    const failedLaunch = await runArtifactLifecyclePlaywrightSmoke({
      environ: ENV,
      importPlaywright: async () => {
        throw new Error("postgresql+psycopg://u:nuri1004@host/db");
      }
    });

    assert.equal(badChecks.status, "FAIL");
    assert.deepEqual(badChecks.issues, [
      { category: "check_failed", subject: "delete_transition_applied" }
    ]);
    assert.equal(failedLaunch.status, "FAIL");
    assert.equal(failedLaunch.failure_code, "Error");
    assert.doesNotMatch(JSON.stringify(failedLaunch), /nuri1004|postgresql/);
  });

  it("guards redaction and summary CLI output", async () => {
    assert.throws(
      () =>
        assertArtifactLifecyclePlaywrightSmokeEvidenceRedacted({
          status: "PASS",
          leak: "Move out of active view"
        }),
      /leaked server material/
    );

    const lines = [];
    const code = await main(
      ["--summary"],
      line => lines.push(line)
    );

    assert.equal(code, 1);
    assert.match(
      lines[0],
      /ae_web_artifact_lifecycle_playwright_smoke=fail reason=required_env_missing/
    );
  });
});
