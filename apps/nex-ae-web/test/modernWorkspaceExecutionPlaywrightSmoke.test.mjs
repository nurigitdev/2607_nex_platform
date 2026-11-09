import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MODERN_WORKSPACE_EXECUTION_SMOKE_SCHEMA_VERSION,
  formatSummary,
} from "../scripts/runModernWorkspaceExecutionPlaywrightSmoke.mjs";

test("modern Workspace execution smoke remains registered and credential-safe", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  const source = await readFile(
    new URL("../scripts/runModernWorkspaceExecutionPlaywrightSmoke.mjs", import.meta.url),
    "utf8",
  );
  const evidence = {
    status: "PASS",
    observations: { business_request_count: 8, result_read_count: 3 },
    checks: {
      owner_scope: true,
      approval_wait: true,
      result: true,
    },
  };

  assert.equal(
    MODERN_WORKSPACE_EXECUTION_SMOKE_SCHEMA_VERSION,
    "ae_web_modern_workspace_execution_smoke.uxm_s14.v1",
  );
  assert.equal(
    packageJson.scripts["smoke:v2-workspace-playwright"],
    "node scripts/runModernWorkspaceExecutionPlaywrightSmoke.mjs --summary",
  );
  assert.equal(
    formatSummary(evidence),
    "modern_workspace_execution_playwright_smoke=pass requests=8 result_reads=3 checks=3",
  );
  assert.equal(
    formatSummary({ ...evidence, status: "FAIL" }),
    "modern_workspace_execution_playwright_smoke=fail reason=checks_failed",
  );
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
