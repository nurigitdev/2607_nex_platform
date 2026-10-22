import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_APPROVAL_UI_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
  assertApprovalUiEvidenceRedacted,
  formatSummary
} from "../scripts/runApprovalUiPlaywrightSmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);

describe("AE Web approval Playwright smoke contract", () => {
  it("registers the executable browser smoke", () => {
    assert.equal(
      PACKAGE.scripts["smoke:approval-ui-playwright"],
      "node scripts/runApprovalUiPlaywrightSmoke.mjs --summary"
    );
    assert.equal(
      AE_WEB_APPROVAL_UI_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      "ae_web_approval_ui_playwright_smoke.p8.v1"
    );
  });

  it("formats pass and failure evidence without protected material", () => {
    const evidence = {
      status: "PASS",
      observations: { gate_count: 4, domain_count: 3 },
      checks: { one: true, two: true }
    };
    assert.equal(
      formatSummary(evidence),
      "ae_web_approval_ui_playwright_smoke=pass gates=4 domains=3 checks=2"
    );
    assert.equal(
      formatSummary({ status: "FAIL" }),
      "ae_web_approval_ui_playwright_smoke=fail reason=checks_failed"
    );
    assert.doesNotThrow(() => assertApprovalUiEvidenceRedacted(evidence));
    assert.throws(
      () => assertApprovalUiEvidenceRedacted({ service_token: "private" }),
      /protected material/
    );
  });
});
