import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_AUTH_FIRST_SHELL_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
  formatSummary
} from "../scripts/runAuthenticationFirstShellPlaywrightSmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);

describe("AE Web authentication-first shell Playwright smoke", () => {
  it("registers the protected browser smoke", () => {
    assert.equal(
      PACKAGE.scripts["smoke:auth-first-shell-playwright"],
      "node scripts/runAuthenticationFirstShellPlaywrightSmoke.mjs --summary"
    );
    assert.equal(
      AE_WEB_AUTH_FIRST_SHELL_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      "ae_web_auth_first_shell_playwright_smoke.p8_s42a.v1"
    );
  });

  it("formats pass and failure summaries", () => {
    const evidence = {
      status: "PASS",
      observations: { routed_view_count: 5, protected_service_request_count: 0 },
      checks: { one: true, two: true }
    };
    assert.equal(
      formatSummary(evidence),
      "ae_web_auth_first_shell_playwright_smoke=pass views=5 service_probes=0 checks=2"
    );
    assert.equal(
      formatSummary({ status: "FAIL" }),
      "ae_web_auth_first_shell_playwright_smoke=fail reason=checks_failed"
    );
  });
});
