import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_PLAYWRIGHT_READINESS_SCHEMA_VERSION,
  DEFAULT_BROWSER_NAME,
  PLAYWRIGHT_BROWSER_ENV,
  PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV,
  assertPlaywrightReadinessEvidenceRedacted,
  formatSummary,
  main,
  runPlaywrightReadiness
} from "../scripts/runCredentialLoginPlaywrightReadiness.mjs";

function fakePlaywright({ launchFails = false, launchOptions = [] } = {}) {
  return {
    chromium: {
      async launch(options) {
        launchOptions.push(options);
        if (launchFails) {
          throw new Error("missing browser binary");
        }
        return {
          async close() {}
        };
      }
    }
  };
}

describe("AE Web Playwright readiness", () => {
  it("passes dependency readiness without launching a browser by default", async () => {
    const evidence = await runPlaywrightReadiness({
      environ: {},
      importPlaywright: async () => fakePlaywright()
    });

    assert.equal(evidence.readiness_schema_version, AE_WEB_PLAYWRIGHT_READINESS_SCHEMA_VERSION);
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.browser, DEFAULT_BROWSER_NAME);
    assert.equal(evidence.runner.mode, "dependency_readiness");
    assert.equal(evidence.checks.launch_check_requested, false);
    assert.equal(evidence.checks.browser_launch_succeeded, null);
    assert.equal(evidence.automation_contract.browser_smoke_tool, "Playwright");
    assert.equal(evidence.automation_contract.browser_base_path, "/ae-api");
    assert.equal(formatSummary(evidence), (
      "ae_web_playwright_readiness=pass " +
      "browser=chromium mode=dependency_readiness launch=deferred"
    ));
  });

  it("can optionally prove a Chromium launch path", async () => {
    const launchOptions = [];
    const evidence = await runPlaywrightReadiness({
      environ: { [PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]: "/usr/bin/google-chrome" },
      launchCheck: true,
      importPlaywright: async () => fakePlaywright({ launchOptions })
    });

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.mode, "launch_check");
    assert.equal(evidence.runner.system_chromium_executable_configured, true);
    assert.equal(evidence.checks.browser_launch_succeeded, true);
    assert.deepEqual(launchOptions, [
      { headless: true, executablePath: "/usr/bin/google-chrome" }
    ]);
    assert.equal(formatSummary(evidence), (
      "ae_web_playwright_readiness=pass " +
      "browser=chromium mode=launch_check launch=checked"
    ));
  });

  it("reports unsupported browsers, import failures, and launch failures", async () => {
    const unsupported = await runPlaywrightReadiness({
      environ: { [PLAYWRIGHT_BROWSER_ENV]: "firefox" },
      importPlaywright: async () => fakePlaywright()
    });
    const importFailed = await runPlaywrightReadiness({
      environ: {},
      importPlaywright: async () => {
        throw new Error("module missing");
      }
    });
    const launchFailed = await runPlaywrightReadiness({
      environ: {},
      launchCheck: true,
      importPlaywright: async () => fakePlaywright({ launchFails: true })
    });

    assert.equal(unsupported.status, "FAIL");
    assert.equal(unsupported.issues[0].category, "browser_unsupported");
    assert.equal(importFailed.status, "FAIL");
    assert.equal(importFailed.issues[0].category, "dependency_import_failed");
    assert.equal(launchFailed.status, "FAIL");
    assert.equal(launchFailed.issues[0].category, "browser_launch_failed");
    assert.equal(formatSummary(launchFailed), "ae_web_playwright_readiness=fail issues=1");
  });

  it("rejects server-only evidence fragments", () => {
    assert.throws(
      () => assertPlaywrightReadinessEvidenceRedacted({ leak: "database_url" }),
      /server material/
    );
    assert.doesNotThrow(() =>
      assertPlaywrightReadinessEvidenceRedacted({ safe: "browser=chromium" })
    );
  });

  it("supports summary, JSON, failure, and exception CLI branches", async () => {
    const outputs = [];
    const passCode = await main(["--summary"], line => outputs.push(line));

    assert.equal(passCode, 0);
    assert.match(outputs.at(-1), /ae_web_playwright_readiness=pass/);

    const jsonOutputs = [];
    const jsonCode = await main(["--json"], line => jsonOutputs.push(line));
    assert.equal(jsonCode, 0);
    assert.equal(JSON.parse(jsonOutputs.at(-1)).status, "PASS");

    const failOutputs = [];
    const exceptionOutputs = [];
    const previousBrowser = process.env[PLAYWRIGHT_BROWSER_ENV];
    process.env[PLAYWRIGHT_BROWSER_ENV] = "firefox";
    try {
      const failCode = await main(["--summary"], line => failOutputs.push(line));
      assert.equal(failCode, 1);
      assert.match(failOutputs.at(-1), /issues=1/);

      process.env[PLAYWRIGHT_BROWSER_ENV] = "database_url";
      const exceptionCode = await main(["--summary"], line => exceptionOutputs.push(line));
      assert.equal(exceptionCode, 1);
      assert.match(exceptionOutputs.at(-1), /error=Error/);
    } finally {
      if (previousBrowser === undefined) {
        delete process.env[PLAYWRIGHT_BROWSER_ENV];
      } else {
        process.env[PLAYWRIGHT_BROWSER_ENV] = previousBrowser;
      }
    }
  });
});
