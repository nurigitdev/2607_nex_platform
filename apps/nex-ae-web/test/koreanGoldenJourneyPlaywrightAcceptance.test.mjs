import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ENV,
  assertEvidenceRedacted,
  runKoreanGoldenJourneyPlaywrightAcceptance,
  summaryLine
} from "../scripts/runKoreanGoldenJourneyPlaywrightAcceptance.mjs";

describe("AE Web Korean golden journey Playwright acceptance", () => {
  it("aggregates two passing viewport executions into redacted evidence", async () => {
    const evidence = await runKoreanGoldenJourneyPlaywrightAcceptance({
      environ: { [ENV.webUrl]: "http://127.0.0.1:5173" },
      viewportRunner: async ({ viewportName, viewport, screenshotDir }) => ({
        viewportName,
        status: "PASS",
        browserLaunched: true,
        koreanUiConfirmed: true,
        journeyStageCount: 9,
        uiActionCount: 3,
        artifactActionCount: 2,
        credentialFieldCleared: true,
        pageErrorCount: 0,
        layout: {
          status: "PASS",
          summary: {
            viewportWidth: viewport.width,
            viewportHeight: viewport.height,
            overlapCount: 0
          }
        },
        screenshotRef: `${screenshotDir}/${viewportName}.png`
      })
    });

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.viewports.length, 2);
    assert.equal(evidence.viewports[0].journey_stage_count, 9);
    assert.equal(evidence.viewports[1].layout.summary.overlapCount, 0);
    assert.equal(evidence.checks.redacted_evidence, true);
    assert.match(summaryLine(evidence), /viewports=2 stages=9 issues=0/);
  });

  it("reports missing environment and failed viewport checks without launching", async () => {
    const missing = await runKoreanGoldenJourneyPlaywrightAcceptance({
      environ: {}
    });
    assert.equal(missing.status, "FAIL");
    assert.equal(missing.issues[0].category, "required_env_missing");

    const failed = await runKoreanGoldenJourneyPlaywrightAcceptance({
      environ: { [ENV.webUrl]: "http://127.0.0.1:5173" },
      viewportRunner: async ({ viewportName }) => ({
        viewportName,
        status: "FAIL",
        browserLaunched: true,
        koreanUiConfirmed: viewportName === "desktop",
        journeyStageCount: 8,
        uiActionCount: 2,
        artifactActionCount: 1,
        credentialFieldCleared: false,
        pageErrorCount: 1,
        layout: { status: "FAIL", issues: ["NO_HORIZONTAL_OVERFLOW"] },
        screenshotRef: null
      })
    });
    assert.equal(failed.status, "FAIL");
    assert.ok(failed.issues.length >= 1);
  });

  it("validates timeout, screenshot paths, launch errors, and redaction", async () => {
    const timeout = await runKoreanGoldenJourneyPlaywrightAcceptance({
      environ: {
        [ENV.webUrl]: "http://127.0.0.1:5173",
        [ENV.timeoutMs]: "10"
      },
      viewportRunner: async () => ({})
    });
    assert.equal(timeout.status, "FAIL");

    const screenshotPath = await runKoreanGoldenJourneyPlaywrightAcceptance({
      environ: {
        [ENV.webUrl]: "http://127.0.0.1:5173",
        [ENV.screenshotDir]: "../private"
      },
      viewportRunner: async () => ({})
    });
    assert.equal(screenshotPath.status, "FAIL");

    const launch = await runKoreanGoldenJourneyPlaywrightAcceptance({
      environ: { [ENV.webUrl]: "http://127.0.0.1:5173" },
      importPlaywright: async () => {
        throw new Error("launch failed");
      }
    });
    assert.equal(launch.status, "FAIL");
    assert.throws(
      () => assertEvidenceRedacted({ value: "deterministic-password" }),
      /private material/
    );
  });
});
