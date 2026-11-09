import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { MODERN_ARTIFACT_SMOKE_SCHEMA_VERSION, formatSummary } from "../scripts/runModernArtifactPlaywrightSmoke.mjs";

test("modern artifact smoke remains registered and credential-safe", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  const source = await readFile(new URL("../scripts/runModernArtifactPlaywrightSmoke.mjs", import.meta.url), "utf8");
  const evidence = { status: "PASS", observations: { request_count: 16, screenshot_count: 2 }, checks: { preview: true, export: true } };
  assert.equal(MODERN_ARTIFACT_SMOKE_SCHEMA_VERSION, "ae_web_modern_artifact_smoke.uxm_s16.v1");
  assert.equal(packageJson.scripts["smoke:v2-artifact-playwright"], "node scripts/runModernArtifactPlaywrightSmoke.mjs --summary");
  assert.equal(formatSummary(evidence), "modern_artifact_playwright_smoke=pass requests=16 screenshots=2 checks=2");
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
