import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MODERN_SECURITY_BOUNDARY_SMOKE_SCHEMA_VERSION,
  formatSummary
} from "../scripts/runModernSecurityBoundaryPlaywrightSmoke.mjs";

test("modern security boundary Playwright smoke remains registered and safe", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8")
  );
  const source = await readFile(
    new URL("../scripts/runModernSecurityBoundaryPlaywrightSmoke.mjs", import.meta.url),
    "utf8"
  );
  const evidence = {
    status: "PASS",
    observations: { business_request_count: 4 },
    checks: {
      same_origin: true,
      no_service_credential: true
    }
  };

  assert.equal(
    MODERN_SECURITY_BOUNDARY_SMOKE_SCHEMA_VERSION,
    "ae_web_modern_security_boundary_smoke.uxm_s07.v1"
  );
  assert.equal(
    packageJson.scripts["smoke:v2-security-playwright"],
    "node scripts/runModernSecurityBoundaryPlaywrightSmoke.mjs --summary"
  );
  assert.equal(
    formatSummary(evidence),
    "modern_security_boundary_playwright_smoke=pass requests=4 checks=2"
  );
  assert.equal(
    formatSummary({ ...evidence, status: "FAIL" }),
    "modern_security_boundary_playwright_smoke=fail reason=checks_failed"
  );
  assert.doesNotMatch(source, /NEX_(?:OA|WC|EOS|CX|MO)_.*(?:TOKEN|PASSWORD)/);
});
