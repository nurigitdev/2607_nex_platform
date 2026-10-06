import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  GOLDEN_JOURNEY_NON_OVERLAP_PAIRS,
  GOLDEN_JOURNEY_REGION_SELECTORS,
  evaluateGoldenJourneyViewport,
  rectangleOverlapArea
} from "../src/goldenJourneyViewport.js";

describe("AE Web golden journey viewport acceptance", () => {
  it("accepts desktop and mobile snapshots that satisfy the frozen contract", () => {
    for (const [viewportName, width, height] of [
      ["desktop", 1440, 900],
      ["mobile", 390, 844]
    ]) {
      const evidence = evaluateGoldenJourneyViewport(
        passingSnapshot(viewportName, width, height)
      );

      assert.equal(evidence.status, "PASS");
      assert.deepEqual(evidence.issues, []);
      assert.equal(evidence.summary.regionCount, 9);
      assert.equal(evidence.summary.controlCount, 3);
      assert.equal(evidence.summary.overlapCount, 0);
    }
  });

  it("reports overflow, accessibility, target, focus, region, and overlap failures", () => {
    const snapshot = passingSnapshot("mobile", 390, 844);
    snapshot.htmlLang = "en";
    snapshot.mainLandmarkCount = 2;
    snapshot.primaryHeadingCount = 0;
    snapshot.documentWidth = 430;
    snapshot.regions.pop();
    snapshot.controls[0].namePresent = false;
    snapshot.controls[1].targetWidth = 20;
    snapshot.focusIndicatorVisible = false;
    snapshot.overlapPairs[0].overlapArea = 32;

    const evidence = evaluateGoldenJourneyViewport(snapshot);

    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.issues.length, 9);
    assert.equal(evidence.summary.unnamedControlCount, 1);
    assert.equal(evidence.summary.undersizedControlCount, 1);
    assert.equal(evidence.summary.overlapCount, 1);
  });

  it("requires exact named viewport dimensions and complete overlap evidence", () => {
    assert.throws(
      () => evaluateGoldenJourneyViewport({ viewportName: "tablet" }),
      /unsupported/
    );
    assert.throws(
      () => evaluateGoldenJourneyViewport({
        ...passingSnapshot("desktop", 1440, 900),
        viewportWidth: 1280
      }),
      /dimensions/
    );

    const missingPair = passingSnapshot("desktop", 1440, 900);
    missingPair.overlapPairs.pop();
    assert.equal(
      evaluateGoldenJourneyViewport(missingPair).checks.primary_regions_do_not_overlap,
      false
    );
  });

  it("calculates rectangle intersections without treating touching edges as overlap", () => {
    assert.equal(
      rectangleOverlapArea(
        { x: 0, y: 0, width: 100, height: 100 },
        { x: 50, y: 25, width: 100, height: 25 }
      ),
      1250
    );
    assert.equal(
      rectangleOverlapArea(
        { x: 0, y: 0, width: 100, height: 100 },
        { x: 100, y: 0, width: 100, height: 100 }
      ),
      0
    );
    assert.equal(rectangleOverlapArea(null, {}), 0);
  });
});

function passingSnapshot(viewportName, viewportWidth, viewportHeight) {
  return {
    viewportName,
    viewportWidth,
    viewportHeight,
    documentWidth: viewportWidth,
    htmlLang: "ko",
    mainLandmarkCount: 1,
    primaryHeadingCount: 1,
    regions: Object.keys(GOLDEN_JOURNEY_REGION_SELECTORS).map(name => ({
      name,
      present: true,
      width: 100,
      height: 100
    })),
    controls: [
      { visible: true, namePresent: true, targetWidth: 120, targetHeight: 38 },
      { visible: true, namePresent: true, targetWidth: 42, targetHeight: 42 },
      { visible: true, namePresent: true, targetWidth: 80, targetHeight: 30 }
    ],
    focusIndicatorVisible: true,
    overlapPairs: GOLDEN_JOURNEY_NON_OVERLAP_PAIRS.map(([first, second]) => ({
      first,
      second,
      overlapArea: 0
    }))
  };
}
