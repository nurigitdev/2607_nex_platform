import assert from "node:assert/strict";
import { test } from "node:test";

import { summaryLine } from "../scripts/captureV1ManualScreenshots.mjs";


test("v1 manual screenshot summary stays metadata only", () => {
  const summary = summaryLine({
    source_tag: "v1.0",
    source_revision: "ab7af0fc3b42225d1d71d20d517889d694a01c03",
    capture_count: 7,
    private_data_included: false
  });

  assert.equal(
    summary,
    "v1_manual_screenshots=pass tag=v1.0 revision=ab7af0fc captures=7 private_data=false"
  );
  assert.equal(summary.includes("password"), false);
  assert.equal(summary.includes("provider_url"), false);
});
