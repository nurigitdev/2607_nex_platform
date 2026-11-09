import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  PRODUCTION_CUTOVER_SCHEMA_VERSION,
  formatSummary,
} from "../scripts/runProductionCutoverAcceptance.mjs";

test("production cutover acceptance stays registered and metadata-only", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  const source = await readFile(new URL("../scripts/runProductionCutoverAcceptance.mjs", import.meta.url), "utf8");
  const evidence = { status: "PASS", observations: { assetCount: 2 }, checks: { root: true, oci: true } };
  assert.equal(PRODUCTION_CUTOVER_SCHEMA_VERSION, "ae_web_production_cutover.uxm_s20.v1");
  assert.equal(packageJson.scripts["acceptance:v2-production-cutover"], "npm run build:v2 && node scripts/runProductionCutoverAcceptance.mjs --summary");
  assert.equal(formatSummary(evidence), "production_cutover_acceptance=pass assets=2 checks=2");
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
