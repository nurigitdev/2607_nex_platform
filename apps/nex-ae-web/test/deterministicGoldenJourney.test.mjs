import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runDeterministicGoldenJourney } from "../src/deterministicGoldenJourney.js";

describe("AE Web deterministic Korean golden journey", () => {
  it("completes one correlated and browser-safe nine-stage journey", async () => {
    const result = await runDeterministicGoldenJourney({
      journeyId: "journey-browser-desktop"
    });

    assert.equal(result.status, "PASS");
    assert.equal(result.summary.locale, "ko");
    assert.equal(result.summary.completedStageCount, 9);
    assert.equal(result.summary.expectedStageCount, 9);
    assert.equal(result.summary.groundingQualityStatus, "VALIDATED");
    assert.equal(result.summary.renderedFormatCount, 2);
    assert.equal(result.summary.previewContentPresent, true);
    assert.equal(result.summary.downloadContentPresent, true);
    assert.equal(result.evidence.status, "COMPLETED");
    assert.equal(result.evidence.stages.at(-1).stage, "DOWNLOAD_READY");
  });

  it("returns stable redacted evidence across viewport journey ids", async () => {
    const mobile = await runDeterministicGoldenJourney({
      journeyId: "journey-browser-mobile"
    });
    const serialized = JSON.stringify(mobile);

    assert.equal(mobile.summary.journeyId, "journey-browser-mobile");
    assert.doesNotMatch(
      serialized,
      /transient-browser-value|Produce a grounded response|Generated artifact|storage_ref/
    );
    assert.deepEqual(mobile.evidence.redaction, {
      private_payload_included: false,
      credential_material_included: false,
      provider_or_database_location_included: false
    });
  });
});
