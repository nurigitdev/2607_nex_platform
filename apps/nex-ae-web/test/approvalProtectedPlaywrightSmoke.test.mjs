import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_APPROVAL_PROTECTED_PLAYWRIGHT_SCHEMA_VERSION,
  assertProtectedApprovalEvidenceRedacted,
  formatProtectedApprovalSummary,
  protectedApprovalRuntimeConfig
} from "../scripts/runApprovalProtectedPlaywrightSmoke.mjs";
import { captureResponsiveScreenshotEvidence } from "../scripts/responsiveScreenshotEvidence.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);

describe("P8-S43 protected approval Playwright contract", () => {
  it("registers a fetch-mode protected smoke command", () => {
    assert.equal(
      PACKAGE.scripts["smoke:approval-protected-playwright"],
      "node scripts/runApprovalProtectedPlaywrightSmoke.mjs --summary"
    );
    assert.equal(
      AE_WEB_APPROVAL_PROTECTED_PLAYWRIGHT_SCHEMA_VERSION,
      "ae_web_approval_protected_playwright.p8.v1"
    );
    assert.deepEqual(protectedApprovalRuntimeConfig(), {
      runtime_config_schema_version: "ae_web_runtime_config.v1",
      client_mode: "fetch",
      ae_base_url: "/ae-api",
      features: {
        approval_inbox_enabled: true,
        document_detail_enabled: true,
        upload_submit_enabled: true,
        retrieval_submit_enabled: true,
        fetch_clients_enabled: true
      }
    });
  });

  it("formats and redacts protected evidence", () => {
    const evidence = {
      status: "PASS",
      observations: { visible_gate_count: 2, visible_domain_count: 2 },
      checks: { one: true, two: true }
    };
    assert.equal(
      formatProtectedApprovalSummary(evidence),
      "p8_s43_approval_playwright=pass gates=2 domains=2 checks=2"
    );
    assert.equal(
      formatProtectedApprovalSummary({ status: "FAIL", failure_code: "blocked" }),
      "p8_s43_approval_playwright=fail reason=blocked"
    );
    assert.doesNotThrow(() =>
      assertProtectedApprovalEvidenceRedacted(evidence, {})
    );
    assert.throws(
      () =>
        assertProtectedApprovalEvidenceRedacted(
          { marker: "tenant-sensitive-value" },
          { NEX_P8_S43_TENANT_ID: "tenant-sensitive-value" }
        ),
      /leaked/
    );
    assert.throws(
      () => assertProtectedApprovalEvidenceRedacted({ semantic_hash: "private" }, {}),
      /protected material/
    );
  });

  it("keeps screenshot evidence optional and rejects paths outside reports", async () => {
    assert.deepEqual(
      await captureResponsiveScreenshotEvidence({
        page: null,
        screenshotDir: "",
        prefix: "approval"
      }),
      {
        requested: false,
        captureCount: 0,
        noHorizontalOverflow: true,
        layouts: []
      }
    );
    await assert.rejects(
      captureResponsiveScreenshotEvidence({
        page: null,
        screenshotDir: "../private",
        prefix: "approval"
      }),
      /InvalidScreenshotDirectory/
    );
  });
});
