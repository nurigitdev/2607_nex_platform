import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MODERN_APPROVAL_SMOKE_SCHEMA_VERSION,
  formatSummary,
} from "../scripts/runModernApprovalPlaywrightSmoke.mjs";

test("modern approval Playwright smoke remains registered and credential-safe", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  const source = await readFile(
    new URL("../scripts/runModernApprovalPlaywrightSmoke.mjs", import.meta.url),
    "utf8",
  );
  const evidence = {
    status: "PASS",
    observations: { business_request_count: 10, decision_request_count: 2 },
    checks: { approval: true, rejection: true },
  };

  assert.equal(
    MODERN_APPROVAL_SMOKE_SCHEMA_VERSION,
    "ae_web_modern_approval_smoke.uxm_s10.v1",
  );
  assert.equal(
    packageJson.scripts["smoke:v2-approval-playwright"],
    "node scripts/runModernApprovalPlaywrightSmoke.mjs --summary",
  );
  assert.equal(
    formatSummary(evidence),
    "modern_approval_playwright_smoke=pass requests=10 decisions=2 checks=2",
  );
  assert.equal(
    formatSummary({ ...evidence, status: "FAIL" }),
    "modern_approval_playwright_smoke=fail reason=checks_failed",
  );
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
