import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS,
  FULL_WEB_ACCEPTANCE_V2_SCHEMA_VERSION,
  buildFullWebAcceptanceV2Receipt,
  formatSummary,
} from "../scripts/runFullWebAcceptanceV2.mjs";

test("full Web Acceptance v2 remains complete, fail-closed, and credential-safe", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  const source = await readFile(new URL("../scripts/runFullWebAcceptanceV2.mjs", import.meta.url), "utf8");
  const passing = FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS.map(id => ({
    id,
    evidence: { status: "PASS", checks: { protected: true }, observations: { screenshot_count: 2 } },
  }));
  const receipt = buildFullWebAcceptanceV2Receipt(passing);

  assert.equal(FULL_WEB_ACCEPTANCE_V2_SCHEMA_VERSION, "ae_web_full_acceptance.uxm_s19.v1");
  assert.equal(packageJson.scripts["acceptance:v2-full-web"], "node scripts/runFullWebAcceptanceV2.mjs --summary");
  assert.equal(receipt.status, "PASS");
  assert.equal(receipt.journeyCount, 6);
  assert.equal(receipt.checkCount, 6);
  assert.equal(receipt.screenshotCount, 12);
  assert.equal(formatSummary(receipt), "full_web_acceptance_v2=pass journeys=6 checks=6 screenshots=12");
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);

  const failed = buildFullWebAcceptanceV2Receipt([
    ...passing.slice(0, 5),
    { ...passing[5], evidence: { ...passing[5].evidence, status: "FAIL" } },
  ]);
  assert.equal(failed.status, "FAIL");
  assert.deepEqual(failed.failedJourneyIds, ["operations-isolation"]);
});
