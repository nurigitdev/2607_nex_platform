import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MODERN_DOCUMENT_SMOKE_SCHEMA_VERSION,
  formatSummary,
} from "../scripts/runModernDocumentPlaywrightSmoke.mjs";

test("modern document smoke remains registered and credential-safe", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  const source = await readFile(new URL("../scripts/runModernDocumentPlaywrightSmoke.mjs", import.meta.url), "utf8");
  const evidence = { status: "PASS", observations: { request_count: 8, screenshot_count: 3 }, checks: { documents: true, retrieval: true } };
  assert.equal(MODERN_DOCUMENT_SMOKE_SCHEMA_VERSION, "ae_web_modern_document_smoke.uxm_s15.v1");
  assert.equal(packageJson.scripts["smoke:v2-document-playwright"], "node scripts/runModernDocumentPlaywrightSmoke.mjs --summary");
  assert.equal(formatSummary(evidence), "modern_document_playwright_smoke=pass requests=8 screenshots=3 checks=2");
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
