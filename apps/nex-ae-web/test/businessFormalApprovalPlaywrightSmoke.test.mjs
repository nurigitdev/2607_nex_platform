import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_BUSINESS_FORMAL_PLAYWRIGHT_SCHEMA_VERSION,
  assertBusinessFormalEvidenceRedacted,
  formatBusinessFormalSummary,
  runBusinessFormalApprovalPlaywrightSmoke
} from "../scripts/runBusinessFormalApprovalPlaywrightSmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);

describe("P8-S74 BUSINESS_FORMAL Playwright contract", () => {
  it("registers the protected fetch-mode smoke", () => {
    assert.equal(
      PACKAGE.scripts["smoke:business-formal-playwright"],
      "node scripts/runBusinessFormalApprovalPlaywrightSmoke.mjs --summary"
    );
    assert.equal(
      AE_WEB_BUSINESS_FORMAL_PLAYWRIGHT_SCHEMA_VERSION,
      "ae_web_business_formal_playwright.p8.v1"
    );
  });

  it("fails closed when required protected-smoke environment is absent", async () => {
    const evidence = await runBusinessFormalApprovalPlaywrightSmoke({ environ: {} });
    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.failure_code, "required_env_missing");
    assert.ok(evidence.observations.missing_count > 0);
  });

  it("formats and redacts metadata-only evidence", () => {
    const evidence = {
      status: "PASS",
      observations: { visible_gate_count: 2, visible_domain_count: 2 },
      checks: { one: true, two: true }
    };
    assert.equal(
      formatBusinessFormalSummary(evidence),
      "p8_s74_business_formal_playwright=pass gates=2 domains=2 checks=2"
    );
    assert.equal(
      formatBusinessFormalSummary({ status: "FAIL", failure_code: "blocked" }),
      "p8_s74_business_formal_playwright=fail reason=blocked"
    );
    assert.doesNotThrow(() => assertBusinessFormalEvidenceRedacted(evidence, {}));
    assert.throws(
      () =>
        assertBusinessFormalEvidenceRedacted(
          { marker: "tenant-sensitive-value" },
          { NEX_P8_S74_TENANT_ID: "tenant-sensitive-value" }
        ),
      /leaked/
    );
    assert.throws(
      () => assertBusinessFormalEvidenceRedacted({ semantic_hash: "private" }, {}),
      /protected material/
    );
  });
});
