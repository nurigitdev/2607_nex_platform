import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { MODERN_OPERATIONS_SMOKE_SCHEMA_VERSION, formatSummary } from "../scripts/runModernOperationsPlaywrightSmoke.mjs";

test("modern operations smoke remains registered and credential-safe", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  const source = await readFile(new URL("../scripts/runModernOperationsPlaywrightSmoke.mjs", import.meta.url), "utf8");
  const evidence = { status: "PASS", observations: { request_count: 8, screenshot_count: 2 }, checks: { role: true, facade: true } };
  assert.equal(MODERN_OPERATIONS_SMOKE_SCHEMA_VERSION, "ae_web_modern_operations_smoke.uxm_s17.v1");
  assert.equal(packageJson.scripts["smoke:v2-operations-playwright"], "node scripts/runModernOperationsPlaywrightSmoke.mjs --summary");
  assert.equal(formatSummary(evidence), "modern_operations_playwright_smoke=pass requests=8 screenshots=2 checks=2");
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
